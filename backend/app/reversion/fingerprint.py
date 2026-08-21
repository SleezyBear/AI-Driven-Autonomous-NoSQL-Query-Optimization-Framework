"""Canonical fingerprints for complete optimizer-managed reversion checks."""

from __future__ import annotations

import hashlib
import json

from app.adapters.contracts import DatabaseAdapter, Namespace


async def optimizer_managed_fingerprint(
    adapter: DatabaseAdapter,
    namespace: Namespace,
    query_shape_hash: str,
) -> str:
    """Hash exactly the index and allowed-indexes state the optimizer manages."""
    indexes = await adapter.list_indexes(namespace)
    query_hint = await adapter.get_query_settings_index_hint(namespace, query_shape_hash)
    state = {
        "collection": namespace.collection,
        "indexes": [{"name": index.name, "keys": index.keys} for index in indexes],
        "query_settings_allowed_indexes": query_hint.allowed_indexes if query_hint is not None else None,
        "query_shape_hash": query_shape_hash,
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
