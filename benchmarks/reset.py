"""Provably-equivalent fast dataset reset for CommerceBench arms.

Mutation analysis of ``RealMongoBenchmarkExecutor._execute`` (frozen workload):

* ``order_status_update`` writes only ``orders`` documents with
  ``_id in [1, 10_000]``.
* ``inventory_decrement`` writes only ``inventory`` documents whose
  ``product_id in [1, 500]``.
* ``event_insert`` inserts only ``events`` documents with
  ``_id >= 10_000_000`` (a synthetic, experiment-owned range).

Reads never mutate state.  The only DDL is the optimizer-owned index created by
the candidate setup.  Therefore the pristine state can be restored exactly by:
dropping optimizer-owned indexes, deleting the synthetic event range, and
restoring the bounded mutated projections to their frozen pristine values.
Collection documents outside those projections are immutable by construction and
are left untouched, preserving the exact equivalent starting state.

Equivalence is proven by a content digest over the mutated projections, the
optimizer index namespace, the synthetic-event namespace, collection counts, and
deterministic samples of the immutable collections.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pymongo.database import Database

from benchmarks.commercebench import DatasetSnapshot
from benchmarks.commercebench.dataset import COLLECTIONS

EVENT_INSERT_BASE = 10_000_000
OPTIMIZER_INDEX_PREFIX = "optimizer_"
MUTATED_ORDER_IDS = tuple(range(1, 10_001))
MUTATED_INVENTORY_PRODUCT_IDS = tuple(range(1, 501))


def _sample_ids(count: int) -> tuple[int, ...]:
    """Deterministic immutable-document samples valid for any profile size."""
    candidates = {1, 2, max(1, count // 1_000), max(1, count // 2), max(1, count - 1), count}
    return tuple(sorted(doc_id for doc_id in candidates if 1 <= doc_id <= count))


@dataclass(frozen=True)
class ResetPlan:
    """Frozen pristine values and expected state for one dataset snapshot."""

    dataset_fingerprint: str
    counts: tuple[tuple[str, int], ...]
    orders_status: tuple[tuple[int, str], ...]
    inventory_available: tuple[tuple[int, int], ...]
    sample_hashes: tuple[tuple[str, tuple[tuple[int, str], ...]], ...]

    @property
    def expected_digest(self) -> str:
        payload = {
            "counts": dict(self.counts),
            "indexes": {name: ["_id_"] for name in COLLECTIONS},
            "orders_status": [[order_id, status] for order_id, status in self.orders_status],
            "inventory_available": [[doc_id, available] for doc_id, available in self.inventory_available],
            "synthetic_events": 0,
            "sample_hashes": {name: dict(hashes) for name, hashes in self.sample_hashes},
        }
        return _digest(payload)


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _doc_hash(document: Any) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _sample(collection: tuple[dict[str, Any], ...], ids: tuple[int, ...]) -> tuple[tuple[int, str], ...]:
    # CommerceBench collections are generated in ascending ``_id`` order with
    # ``_id == index + 1``, so samples are taken directly without building a
    # full-collection mapping.
    return tuple((doc_id, _doc_hash(collection[doc_id - 1])) for doc_id in ids)


def build_reset_plan(snapshot: DatasetSnapshot) -> ResetPlan:
    """Extract the pristine mutable projections and immutable sample hashes."""
    documents = dict(snapshot.collections)
    orders = documents["orders"]
    inventory = documents["inventory"]

    orders_status = tuple((index + 1, orders[index]["status"]) for index in range(len(MUTATED_ORDER_IDS)))
    product_filter = set(MUTATED_INVENTORY_PRODUCT_IDS)
    inventory_available = tuple(
        (index + 1, inventory[index]["available"]) for index in range(len(inventory)) if inventory[index]["product_id"] in product_filter
    )
    sample_hashes = (
        ("customers", _sample(documents["customers"], _sample_ids(len(documents["customers"])))),
        ("products", _sample(documents["products"], _sample_ids(len(documents["products"])))),
        ("orders", _sample(documents["orders"], tuple(doc_id for doc_id in _sample_ids(len(documents["orders"])) if doc_id > 10_000))),
        ("events", _sample(documents["events"], _sample_ids(len(documents["events"])))),
        ("inventory", _sample(documents["inventory"], _sample_ids(len(documents["inventory"])))),
    )
    return ResetPlan(
        dataset_fingerprint=snapshot.fingerprint,
        counts=tuple(sorted(snapshot.collection_counts.items())),
        orders_status=orders_status,
        inventory_available=inventory_available,
        sample_hashes=sample_hashes,
    )


def observed_digest(database: Database[Any], plan: ResetPlan) -> str:
    """Content digest of the live database's reset-relevant state."""
    sample_hashes = tuple(
        (name, tuple((doc_id, _doc_hash(database[name].find_one({"_id": doc_id}))) for doc_id, _ in hashes))
        for name, hashes in plan.sample_hashes
    )
    payload = {
        "counts": {name: int(database[name].estimated_document_count()) for name in COLLECTIONS},
        "indexes": {name: sorted(database[name].index_information().keys()) for name in COLLECTIONS},
        "orders_status": [
            [document["_id"], document["status"]]
            for document in database["orders"].find({"_id": {"$in": list(MUTATED_ORDER_IDS)}}, {"_id": 1, "status": 1}).sort("_id", 1)
        ],
        "inventory_available": [
            [document["_id"], document["available"]]
            for document in database["inventory"]
            .find({"product_id": {"$in": list(MUTATED_INVENTORY_PRODUCT_IDS)}}, {"_id": 1, "available": 1})
            .sort("_id", 1)
        ],
        "synthetic_events": int(database["events"].count_documents({"_id": {"$gte": EVENT_INSERT_BASE}})),
        "sample_hashes": {name: dict(hashes) for name, hashes in sample_hashes},
    }
    return _digest(payload)


def drop_optimizer_indexes(database: Database[Any]) -> list[str]:
    """Drop only optimizer-owned indexes; never touch human/non-optimizer indexes."""
    dropped: list[str] = []
    for name in COLLECTIONS:
        for index_name in list(database[name].index_information().keys()):
            if index_name.startswith(OPTIMIZER_INDEX_PREFIX):
                database[name].drop_index(index_name)
                dropped.append(f"{name}.{index_name}")
    return dropped


def delta_reset(database: Database[Any], plan: ResetPlan) -> dict[str, object]:
    """Restore the exact pristine starting state using bounded bulk operations."""
    from pymongo import UpdateOne

    dropped = drop_optimizer_indexes(database)
    removed_events = int(database["events"].delete_many({"_id": {"$gte": EVENT_INSERT_BASE}}).deleted_count)
    if plan.orders_status:
        database["orders"].bulk_write(
            [UpdateOne({"_id": order_id}, {"$set": {"status": status}}) for order_id, status in plan.orders_status],
            ordered=False,
        )
    if plan.inventory_available:
        database["inventory"].bulk_write(
            [UpdateOne({"_id": doc_id}, {"$set": {"available": available}}) for doc_id, available in plan.inventory_available],
            ordered=False,
        )
    digest = observed_digest(database, plan)
    if digest != plan.expected_digest:
        raise RuntimeError("delta reset failed to restore the exact equivalent starting state")
    return {
        "reset_implementation": "delta",
        "reset_fingerprint": digest,
        "dropped_optimizer_indexes": dropped,
        "removed_synthetic_events": removed_events,
    }
