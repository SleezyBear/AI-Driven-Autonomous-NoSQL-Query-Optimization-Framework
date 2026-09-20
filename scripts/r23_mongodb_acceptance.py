"""Disposable MongoDB TLS, authorization, topology, and recovery acceptance."""

from __future__ import annotations

import asyncio
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from collections.abc import Callable
from uuid import uuid4

from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import AutoReconnect, ConnectionFailure, OperationFailure, ServerSelectionTimeoutError

from app.mongodb.client import create_async_mongo_client, create_mongo_client, probe_target


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "mongo:8.0"
SAFE_CONTAINER = re.compile(r"^r20r23-mongo-(?:auth|tls|rs)-[a-f0-9]{8}$")


def _run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=ROOT, check=check, text=True, capture_output=True)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait(uri: str, *, tls_ca_file: str | None = None) -> MongoClient[dict[str, object]]:
    deadline = time.monotonic() + 60
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client: MongoClient[dict[str, object]] = MongoClient(
                uri,
                tlsCAFile=tls_ca_file,
                serverSelectionTimeoutMS=1_000,
                connectTimeoutMS=1_000,
            )
            client.admin.command({"ping": 1})
            return client
        except (ConnectionFailure, OperationFailure, ServerSelectionTimeoutError) as error:
            last_error = error
            time.sleep(0.5)
    raise RuntimeError("disposable MongoDB did not become ready") from last_error


def _auth_acceptance(container: str, port: int) -> None:
    root_uri = (
        f"mongodb://r23_root:r23_root_disposable@127.0.0.1:{port}/admin"
        "?authSource=admin&directConnection=true"
    )
    root = _wait(root_uri)
    try:
        admin = root.admin
        commerce = root["r23_commerce"]
        commerce["permission_probe"].insert_one({"seed": 1})
        admin.command(
            {
                "createRole": "r23Executor",
                "privileges": [
                    {
                        "resource": {"db": "r23_commerce", "collection": ""},
                        "actions": ["find", "listCollections", "listIndexes", "createIndex", "dropIndex"],
                    }
                ],
                "roles": [],
            }
        )
        admin.command(
            {
                "createUser": "r23_executor",
                "pwd": "r23_executor_disposable",
                "roles": [{"role": "r23Executor", "db": "admin"}],
            }
        )
    finally:
        root.close()

    executor_uri = (
        f"mongodb://r23_executor:r23_executor_disposable@127.0.0.1:{port}/admin"
        "?authSource=admin&directConnection=true"
    )
    executor = create_mongo_client(executor_uri, local_development=True)
    try:
        collection = executor["r23_commerce"]["permission_probe"]
        if collection.find_one({"seed": 1}) is None:
            raise RuntimeError("executor cannot perform required read")
        collection.create_index("seed", name="r23_owned_probe")
        collection.drop_index("r23_owned_probe")
        forbidden: tuple[Callable[[], object], ...] = (
            lambda: collection.insert_one({"forbidden": True}),
            lambda: collection.drop(),
            lambda: executor.drop_database("r23_commerce"),
            lambda: executor.admin.command({"setParameter": 1, "notablescan": 1}),
        )
        for operation in forbidden:
            try:
                operation()
            except OperationFailure:
                continue
            raise RuntimeError("executor has a forbidden MongoDB permission")
    finally:
        executor.close()


def _certificates(directory: Path) -> tuple[Path, Path]:
    ca_key = directory / "ca.key"
    ca_cert = directory / "ca.pem"
    server_key = directory / "server.key"
    request = directory / "server.csr"
    server_cert = directory / "server.crt"
    server_pem = directory / "server.pem"
    extension = directory / "server.ext"
    extension.write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n", encoding="utf-8")
    _run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=R23 Test CA", "-keyout", str(ca_key), "-out", str(ca_cert))
    _run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost", "-keyout", str(server_key), "-out", str(request))
    _run("openssl", "x509", "-req", "-in", str(request), "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1", "-extfile", str(extension), "-out", str(server_cert))
    server_pem.write_bytes(server_key.read_bytes() + server_cert.read_bytes())
    server_pem.chmod(0o644)
    ca_cert.chmod(0o644)
    return ca_cert, server_pem


def _tls_acceptance(container: str, port: int, directory: Path) -> None:
    ca_cert, server_pem = _certificates(directory)
    _run(
        "docker", "run", "--detach", "--name", container,
        "--publish", f"127.0.0.1:{port}:27017",
        "--volume", f"{directory}:/certs:ro", IMAGE,
        "mongod", "--bind_ip_all", "--tlsMode", "requireTLS",
        "--tlsCertificateKeyFile", f"/certs/{server_pem.name}",
        "--tlsCAFile", f"/certs/{ca_cert.name}",
        "--tlsAllowConnectionsWithoutCertificates",
    )
    uri = f"mongodb://127.0.0.1:{port}/?tls=true"
    trusted = _wait(uri, tls_ca_file=str(ca_cert))
    trusted.close()
    with tempfile.TemporaryDirectory(prefix="r23-invalid-ca-") as invalid_directory:
        invalid_ca, _ = _certificates(Path(invalid_directory))
        invalid_failed = False
        try:
            untrusted: MongoClient[dict[str, object]] = MongoClient(
                uri,
                tlsCAFile=str(invalid_ca),
                serverSelectionTimeoutMS=2_000,
            )
            untrusted.admin.command({"ping": 1})
        except (ConnectionFailure, ServerSelectionTimeoutError):
            invalid_failed = True
        finally:
            untrusted.close()
        if not invalid_failed:
            raise RuntimeError("untrusted MongoDB CA did not fail closed")


async def _replica_acceptance(container: str, port: int) -> None:
    _run(
        "docker", "run", "--detach", "--name", container,
        "--publish", f"127.0.0.1:{port}:{port}", IMAGE,
        "mongod", "--port", str(port), "--bind_ip_all", "--replSet", "r23rs",
    )
    direct_uri = f"mongodb://127.0.0.1:{port}/?directConnection=true"
    direct = _wait(direct_uri)
    direct.admin.command(
        {"replSetInitiate": {"_id": "r23rs", "members": [{"_id": 0, "host": f"localhost:{port}"}]}}
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if direct.admin.command({"hello": 1}).get("isWritablePrimary"):
                break
        except (AutoReconnect, OperationFailure):
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError("disposable replica set did not elect a primary")
    direct.close()

    uri = f"mongodb://127.0.0.1:{port}/?replicaSet=r23rs"
    client = create_async_mongo_client(uri, local_development=True)
    state = await probe_target(client)
    if state["topology"] != "replica_set" or not state["primary"]:
        raise RuntimeError("replica-set topology discovery failed")
    collection = client["r23_recovery"]["markers"]
    await collection.insert_one({"_id": "durable", "mutations": 1})
    try:
        await client.admin.command({"replSetStepDown": 3, "force": True})
    except (AutoReconnect, OperationFailure):
        pass
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if (await client.admin.command({"hello": 1})).get("isWritablePrimary"):
                break
        except (AutoReconnect, ServerSelectionTimeoutError):
            pass
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError("driver did not recover after primary stepdown/election")
    await client.close()

    _run("docker", "stop", "--time", "10", container)
    outage = create_async_mongo_client(uri, local_development=True)
    outage_observed = False
    try:
        await outage.admin.command({"ping": 1})
    except (AutoReconnect, ServerSelectionTimeoutError):
        outage_observed = True
    finally:
        await outage.close()
    if not outage_observed:
        raise RuntimeError("MongoDB outage was not observed")
    _run("docker", "start", container)
    recovered_sync = _wait(direct_uri)
    recovered_sync.close()
    recovered: AsyncMongoClient[dict[str, object]] = create_async_mongo_client(
        uri, local_development=True
    )
    marker = await recovered["r23_recovery"]["markers"].find_one({"_id": "durable"})
    if marker is None or marker.get("mutations") != 1:
        raise RuntimeError("MongoDB durable reconciliation marker changed across outage")
    await recovered.close()


async def main() -> int:
    suffix = uuid4().hex[:8]
    auth_container = f"r20r23-mongo-auth-{suffix}"
    tls_container = f"r20r23-mongo-tls-{suffix}"
    replica_container = f"r20r23-mongo-rs-{suffix}"
    containers = (auth_container, tls_container, replica_container)
    if any(not SAFE_CONTAINER.fullmatch(name) for name in containers):
        raise RuntimeError("unsafe disposable MongoDB container name")
    try:
        auth_port = _port()
        _run(
            "docker", "run", "--detach", "--name", auth_container,
            "--publish", f"127.0.0.1:{auth_port}:27017",
            "--env", "MONGO_INITDB_ROOT_USERNAME=r23_root",
            "--env", "MONGO_INITDB_ROOT_PASSWORD=r23_root_disposable", IMAGE,
        )
        _auth_acceptance(auth_container, auth_port)
        with tempfile.TemporaryDirectory(prefix="r23-tls-") as directory:
            _tls_acceptance(tls_container, _port(), Path(directory))
        await _replica_acceptance(replica_container, _port())
        print("R23 MONGODB OPERATIONAL ACCEPTANCE: PASS")
        return 0
    finally:
        for container in containers:
            if SAFE_CONTAINER.fullmatch(container):
                _run("docker", "rm", "--force", container, check=False)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
