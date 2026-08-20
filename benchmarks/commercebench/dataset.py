"""Deterministic CommerceBench datasets for comparable benchmark resets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from random import Random
from typing import Any

COMMERCEBENCH_SEED = 42
GENERATOR_VERSION = "1"
COLLECTIONS = ("customers", "products", "orders", "events", "inventory")


class WorkloadProfile(str, Enum):
    """The fixed CommerceBench data volumes used in development and reproduction."""

    SMOKE = "smoke"
    STANDARD = "standard"
    PUBLICATION = "publication"


@dataclass(frozen=True)
class DatasetSnapshot:
    """An immutable generated dataset with a stable, content-derived fingerprint."""

    profile: WorkloadProfile
    seed: int
    collections: tuple[tuple[str, tuple[dict[str, Any], ...]], ...]
    fingerprint: str

    def documents_for(self, collection: str) -> tuple[dict[str, Any], ...]:
        """Return documents for a declared CommerceBench collection."""
        return dict(self.collections)[collection]


class CommerceBench:
    """Generate deterministic, literal-free CommerceBench datasets from seed 42."""

    _VOLUMES: dict[WorkloadProfile, tuple[int, int, int, int]] = {
        WorkloadProfile.SMOKE: (10, 20, 40, 60),
        WorkloadProfile.STANDARD: (100, 200, 500, 750),
        WorkloadProfile.PUBLICATION: (1000, 2000, 5000, 7500),
    }

    def reset(self, profile: WorkloadProfile) -> DatasetSnapshot:
        """Generate a fresh deterministic snapshot; repeated resets have identical content."""
        customer_count, product_count, order_count, event_count = self._VOLUMES[profile]
        random = Random(COMMERCEBENCH_SEED)
        customers = tuple(
            {"_id": customer_id, "segment": ("consumer", "business")[customer_id % 2], "region": customer_id % 5}
            for customer_id in range(1, customer_count + 1)
        )
        products = tuple(
            {"_id": product_id, "category": f"category-{product_id % 8}", "price_cents": random.randint(100, 50000)}
            for product_id in range(1, product_count + 1)
        )
        orders = tuple(
            {
                "_id": order_id,
                "customer_id": ((order_id - 1) % customer_count) + 1,
                "product_id": ((order_id * 7 - 1) % product_count) + 1,
                "quantity": random.randint(1, 5),
                "status": ("created", "paid", "shipped")[order_id % 3],
            }
            for order_id in range(1, order_count + 1)
        )
        events = tuple(
            {
                "_id": event_id,
                "customer_id": ((event_id - 1) % customer_count) + 1,
                "event_type": ("view", "cart", "purchase")[event_id % 3],
                "sequence": event_id,
            }
            for event_id in range(1, event_count + 1)
        )
        inventory = tuple(
            {"_id": product_id, "product_id": product_id, "available": random.randint(0, 1000)}
            for product_id in range(1, product_count + 1)
        )
        collections: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = (
            ("customers", customers),
            ("products", products),
            ("orders", orders),
            ("events", events),
            ("inventory", inventory),
        )
        fingerprint = self._fingerprint(profile, collections)
        return DatasetSnapshot(profile, COMMERCEBENCH_SEED, collections, fingerprint)

    @staticmethod
    def _fingerprint(
        profile: WorkloadProfile, collections: tuple[tuple[str, tuple[dict[str, Any], ...]], ...]
    ) -> str:
        payload = {
            "generator_version": GENERATOR_VERSION,
            "profile": profile.value,
            "seed": COMMERCEBENCH_SEED,
            "collection_counts": {name: len(documents) for name, documents in collections},
            "index_state": {},
            "query_settings_state": {},
            "collections": dict(collections),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
