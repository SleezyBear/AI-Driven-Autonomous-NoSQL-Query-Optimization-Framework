"""Disposable three-member MongoDB partition/election qualification for R25."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pymongo import MongoClient, ReadPreference, WriteConcern
from pymongo.errors import PyMongoError


ROOT = Path(__file__).resolve().parents[1]
DOCKER_HOSTNAME = "host.docker.internal"


def command(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, check=check, capture_output=True, text=True)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_client(uri: str, timeout: float = 60) -> MongoClient[dict[str, object]]:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        client: MongoClient[dict[str, object]] = MongoClient(
            uri,
            serverSelectionTimeoutMS=2_000,
            connectTimeoutMS=2_000,
            socketTimeoutMS=30_000,
            retryReads=True,
            retryWrites=True,
        )
        try:
            client.admin.command({"ping": 1})
            return client
        except PyMongoError as error:
            last = error
            client.close()
            time.sleep(1)
    raise RuntimeError("replica set did not become selectable") from last


def wait_for_marker(uri: str, marker_id: str, sequence: int, timeout: float = 30) -> None:
    """Wait until a specific member has applied the latest majority write."""
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        client: MongoClient[dict[str, object]] = MongoClient(
            uri,
            directConnection=True,
            serverSelectionTimeoutMS=1_000,
            connectTimeoutMS=1_000,
            socketTimeoutMS=2_000,
        )
        try:
            collection = client.get_database("r24r27_partition").get_collection(
                "markers",
                read_preference=ReadPreference.SECONDARY_PREFERRED,
            )
            marker = collection.find_one({"_id": marker_id})
            if marker is not None and marker.get("sequence") == sequence:
                return
        except PyMongoError as error:
            last = error
        finally:
            client.close()
        time.sleep(0.5)
    raise RuntimeError("replica member did not apply the durable marker") from last


def install_split_horizon_resolver() -> Any:
    """Resolve Docker Desktop's host gateway from both sides of the port mapping.

    Replica members must advertise ``host.docker.internal`` so that peer containers
    can reach one another through their published ports. Docker Desktop injects that
    name into containers, but it is not a DNS name on the macOS host. The host-side
    qualification client therefore maps only that exact synthetic name to loopback.
    """
    native_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if host == DOCKER_HOSTNAME or host == DOCKER_HOSTNAME.encode():
            host = "127.0.0.1"
        return native_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    return native_getaddrinfo


def main() -> None:
    token = uuid4().hex[:10]
    replica_set = f"r24r27rs{token}"
    names = [f"r24r27-partition-{token}-{index}" for index in range(3)]
    ports = [free_port() for _ in names]
    marker_id = f"r24r27-marker-{token}"
    client: MongoClient[dict[str, object]] | None = None
    native_getaddrinfo = install_split_horizon_resolver()
    try:
        for name, port in zip(names, ports, strict=True):
            command(
                "docker", "run", "--rm", "-d", "--name", name,
                "--label", "qualification.owner=r24r27",
                "-p", f"127.0.0.1:{port}:27017",
                "mongo:8.0", "--replSet", replica_set, "--bind_ip_all",
            )
        time.sleep(3)
        members = ",".join(
            f'{{_id:{index},host:"{DOCKER_HOSTNAME}:{port}"}}'
            for index, port in enumerate(ports)
        )
        command(
            "docker", "exec", names[0], "mongosh", "--quiet", "--eval",
            f'rs.initiate({{_id:"{replica_set}",members:[{members}]}})',
        )
        uri = (
            "mongodb://"
            + ",".join(f"127.0.0.1:{port}" for port in ports)
            + f"/?replicaSet={replica_set}"
        )
        client = wait_client(uri)
        collection = client.get_database("r24r27_partition").get_collection("markers")
        collection.with_options(write_concern=WriteConcern("majority", wtimeout=3_000)).insert_one(
            {"_id": marker_id, "sequence": 1}
        )
        primary = str(client.admin.command({"hello": 1})["primary"])
        primary_index = next(
            index for index, port in enumerate(ports) if primary.endswith(f":{port}")
        )
        secondaries = [index for index in range(3) if index != primary_index]

        # One secondary loss retains majority and must remain usable.
        command("docker", "pause", names[secondaries[0]])
        collection.with_options(write_concern=WriteConcern("majority", wtimeout=3_000)).update_one(
            {"_id": marker_id}, {"$set": {"sequence": 2}}
        )
        command("docker", "unpause", names[secondaries[0]])
        wait_for_marker(
            f"mongodb://127.0.0.1:{ports[secondaries[0]]}", marker_id, sequence=2
        )

        # Primary loss with two members alive must elect and recover.
        command("docker", "pause", names[primary_index])
        election_client = wait_client(uri, timeout=45)
        election_client.get_database("r24r27_partition").get_collection("markers").with_options(
            write_concern=WriteConcern("majority", wtimeout=20_000)
        ).update_one({"_id": marker_id}, {"$set": {"sequence": 3}})
        election_client.close()
        command("docker", "unpause", names[primary_index])
        client.close()
        client = wait_client(uri)

        # Loss of majority is uncertainty, never a reported successful write.
        hello = client.admin.command({"hello": 1})
        current_primary = str(hello["primary"])
        current_primary_index = next(
            index for index, port in enumerate(ports) if current_primary.endswith(f":{port}")
        )
        paused = [index for index in range(3) if index != current_primary_index]
        for index in paused:
            command("docker", "pause", names[index])
        uncertain_failed = False
        try:
            collection = client.get_database("r24r27_partition").get_collection("markers")
            collection.with_options(write_concern=WriteConcern("majority", wtimeout=2_000)).update_one(
                {"_id": marker_id}, {"$set": {"sequence": 4}}
            )
        except PyMongoError:
            uncertain_failed = True
        if not uncertain_failed:
            raise AssertionError("loss of majority was incorrectly treated as successful")
        for index in paused:
            command("docker", "unpause", names[index])
        client.close()
        client = wait_client(uri)
        collection = client.get_database("r24r27_partition").get_collection("markers")
        collection.with_options(write_concern=WriteConcern("majority", wtimeout=20_000)).update_one(
            {"_id": marker_id}, {"$set": {"sequence": 5}}
        )
        marker = collection.find_one({"_id": marker_id})
        if marker is None or marker["sequence"] != 5 or collection.count_documents({"_id": marker_id}) != 1:
            raise AssertionError("durable marker was not recovered exactly once")
        artifact = {
            "status": "PASS",
            "members": 3,
            "one_secondary_loss": "majority retained",
            "primary_loss": "election recovered",
            "majority_loss": "failed closed",
            "majority_restoration": "recovered",
            "durable_marker_count": 1,
        }
        output = ROOT / "artifacts" / "generated" / "r25-network-partition.json"
        output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
        print("R25 NETWORK PARTITION PASS: 3 members, majority loss failed closed")
    finally:
        socket.getaddrinfo = native_getaddrinfo
        if client is not None:
            client.close()
        for name in names:
            command("docker", "unpause", name, check=False)
            command("docker", "stop", "-t", "2", name, check=False)


if __name__ == "__main__":
    main()
