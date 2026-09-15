"""Centralized, bounded MongoDB client construction for production adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from pymongo import MongoClient


@dataclass(frozen=True)
class MongoConnectionPolicy:
    server_selection_timeout_ms: int = 5_000
    connect_timeout_ms: int = 5_000
    socket_timeout_ms: int = 30_000
    max_pool_size: int = 20
    wait_queue_timeout_ms: int = 10_000


def mongo_connection_policy() -> MongoConnectionPolicy:
    return MongoConnectionPolicy(
        int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "5000")), int(os.getenv("MONGO_CONNECT_TIMEOUT_MS", "5000")),
        int(os.getenv("MONGO_SOCKET_TIMEOUT_MS", "30000")), int(os.getenv("MONGO_MAX_POOL_SIZE", "20")),
        int(os.getenv("MONGO_WAIT_QUEUE_TIMEOUT_MS", "10000")),
    )


def safe_mongo_uri(uri: str) -> str:
    """Return a credential-free URI suitable only for logs/errors."""
    parts = urlsplit(uri)
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, host, parts.path, parts.query, ""))


def create_mongo_client(uri: str, *, local_development: bool = False) -> MongoClient:
    """Create one topology-aware client with bounded connection behavior."""
    if os.getenv("APP_ENV") == "production" and not uri.startswith("mongodb+srv://") and not uri.startswith("mongodb://"):
        raise ValueError("MongoDB URI must use mongodb or mongodb+srv.")
    policy = mongo_connection_policy()
    return MongoClient(uri, serverSelectionTimeoutMS=policy.server_selection_timeout_ms, connectTimeoutMS=policy.connect_timeout_ms, socketTimeoutMS=policy.socket_timeout_ms, maxPoolSize=policy.max_pool_size, waitQueueTimeoutMS=policy.wait_queue_timeout_ms, retryWrites=True, tls=True if os.getenv("APP_ENV") == "production" and not local_development else None)
