"""Frozen, deterministic CommerceBench read/write workload shapes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class WorkloadKind(str, Enum):
    READ = "READ"
    WRITE = "WRITE"


@dataclass(frozen=True)
class WorkloadShape:
    """One literal-free workload shape and its deterministic scheduling weight."""

    name: str
    kind: WorkloadKind
    collection: str
    weight: int
    operation: dict[str, Any]


COMMERCEBENCH_WORKLOADS: tuple[WorkloadShape, ...] = (
    WorkloadShape("customer_by_id", WorkloadKind.READ, "customers", 20, {"find": "customers", "filter": {"_id": "<integer>"}}),
    WorkloadShape("product_by_category", WorkloadKind.READ, "products", 15, {"find": "products", "filter": {"category": "<string>"}}),
    WorkloadShape("orders_by_customer", WorkloadKind.READ, "orders", 25, {"find": "orders", "filter": {"customer_id": "<integer>"}, "sort": {"_id": -1}}),
    WorkloadShape("inventory_by_product", WorkloadKind.READ, "inventory", 10, {"find": "inventory", "filter": {"product_id": "<integer>"}}),
    WorkloadShape("order_status_update", WorkloadKind.WRITE, "orders", 12, {"update": "orders", "updates": [{"q": {"_id": "<integer>"}, "u": {"$set": {"status": "<string>"}}}]}),
    WorkloadShape("inventory_decrement", WorkloadKind.WRITE, "inventory", 10, {"update": "inventory", "updates": [{"q": {"product_id": "<integer>"}, "u": {"$inc": {"available": "<integer>"}}}]}),
    WorkloadShape("event_insert", WorkloadKind.WRITE, "events", 8, {"insert": "events", "documents": [{"customer_id": "<integer>", "event_type": "<string>"}]}),
)


def mixed_workload_shapes() -> tuple[WorkloadShape, ...]:
    """Return the frozen workload mixture; reads and writes are both mandatory."""
    return COMMERCEBENCH_WORKLOADS
