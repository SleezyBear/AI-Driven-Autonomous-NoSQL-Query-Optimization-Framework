"""Centralized, bounded MongoDB client construction for production adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pymongo import AsyncMongoClient, MongoClient


_SENSITIVE_QUERY_KEYS = {
    "authmechanismproperties",
    "password",
    "proxyusername",
    "proxypassword",
}
_DEVELOPMENT_MARKERS = ("dev_only", "changeme", "replace-with")


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value


@dataclass(frozen=True)
class MongoConnectionPolicy:
    server_selection_timeout_ms: int
    connect_timeout_ms: int
    socket_timeout_ms: int
    max_pool_size: int
    min_pool_size: int
    wait_queue_timeout_ms: int
    max_idle_time_ms: int


def mongo_connection_policy() -> MongoConnectionPolicy:
    """Load bounded driver timeouts and process-local pool limits."""
    maximum = _integer("MONGO_MAX_POOL_SIZE", 20, 1, 200)
    minimum = _integer("MONGO_MIN_POOL_SIZE", 0, 0, maximum)
    return MongoConnectionPolicy(
        server_selection_timeout_ms=_integer(
            "MONGO_SERVER_SELECTION_TIMEOUT_MS", 5_000, 100, 120_000
        ),
        connect_timeout_ms=_integer("MONGO_CONNECT_TIMEOUT_MS", 5_000, 100, 120_000),
        socket_timeout_ms=_integer("MONGO_SOCKET_TIMEOUT_MS", 30_000, 100, 600_000),
        max_pool_size=maximum,
        min_pool_size=minimum,
        wait_queue_timeout_ms=_integer("MONGO_WAIT_QUEUE_TIMEOUT_MS", 10_000, 100, 120_000),
        max_idle_time_ms=_integer("MONGO_MAX_IDLE_TIME_MS", 60_000, 1_000, 600_000),
    )


def safe_mongo_uri(uri: str) -> str:
    """Return a credential-free URI suitable only for logs/errors."""
    parts = urlsplit(uri)
    host = parts.netloc.rsplit("@", 1)[-1]
    query = urlencode(
        [
            (key, "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_KEYS else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ],
        safe="[]",
    )
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _client_options(uri: str, *, local_development: bool) -> dict[str, Any]:
    parts = urlsplit(uri)
    if parts.scheme not in {"mongodb", "mongodb+srv"}:
        raise ValueError("MongoDB URI must use mongodb or mongodb+srv.")
    production = os.getenv("APP_ENV", "development").lower() == "production"
    query = {key.lower(): value.lower() for key, value in parse_qsl(parts.query)}
    if production:
        if query.get("directconnection") == "true":
            raise ValueError("Production MongoDB must use topology discovery, not directConnection=true.")
        password = parts.password or ""
        if not password or any(marker in password.lower() for marker in _DEVELOPMENT_MARKERS):
            raise ValueError("Production refuses development MongoDB credentials.")
    policy = mongo_connection_policy()
    options: dict[str, Any] = {
        "serverSelectionTimeoutMS": policy.server_selection_timeout_ms,
        "connectTimeoutMS": policy.connect_timeout_ms,
        "socketTimeoutMS": policy.socket_timeout_ms,
        "maxPoolSize": policy.max_pool_size,
        "minPoolSize": policy.min_pool_size,
        "waitQueueTimeoutMS": policy.wait_queue_timeout_ms,
        "maxIdleTimeMS": policy.max_idle_time_ms,
        "retryReads": True,
        "retryWrites": True,
        "appname": "nosql-optimizer",
    }
    if production:
        # local_development never disables production certificate validation.
        options["tls"] = True
        options["tlsAllowInvalidCertificates"] = False
        options["tlsAllowInvalidHostnames"] = False
        if ca_file := os.getenv("MONGO_TLS_CA_FILE"):
            if not Path(ca_file).is_file():
                raise ValueError("MONGO_TLS_CA_FILE must name a readable file.")
            options["tlsCAFile"] = ca_file
        if certificate_file := os.getenv("MONGO_TLS_CERTIFICATE_KEY_FILE"):
            if not Path(certificate_file).is_file():
                raise ValueError("MONGO_TLS_CERTIFICATE_KEY_FILE must name a readable file.")
            options["tlsCertificateKeyFile"] = certificate_file
    elif local_development:
        # Do not add a TLS option; URI configuration remains authoritative locally.
        pass
    return options


def create_mongo_client(
    uri: str, *, local_development: bool = False
) -> MongoClient[dict[str, Any]]:
    """Create a topology-aware synchronous client with bounded behavior."""
    return MongoClient(uri, **_client_options(uri, local_development=local_development))


def create_async_mongo_client(
    uri: str, *, local_development: bool = False
) -> AsyncMongoClient[dict[str, Any]]:
    """Create a topology-aware asynchronous client with the identical policy."""
    return AsyncMongoClient(uri, **_client_options(uri, local_development=local_development))


async def probe_target(client: AsyncMongoClient[dict[str, Any]]) -> dict[str, object]:
    """Perform only read-only topology/version/capability discovery."""
    hello = await client.admin.command({"hello": 1})
    build = await client.admin.command({"buildInfo": 1})
    parameters = await client.admin.command({"getParameter": 1, "featureCompatibilityVersion": 1})
    topology = "sharded" if hello.get("msg") == "isdbgrid" else (
        "replica_set" if hello.get("setName") else "standalone"
    )
    return {
        "ok": bool(hello.get("ok")),
        "version": str(build.get("version", "")),
        "topology": topology,
        "primary": bool(hello.get("isWritablePrimary")),
        "feature_compatibility_version": str(
            parameters.get("featureCompatibilityVersion", {}).get("version", "")
        ),
        "query_settings_capable": topology in {"replica_set", "sharded"}
        and bool(build.get("versionArray", [0])[0] >= 8),
    }
