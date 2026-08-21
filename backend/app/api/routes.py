"""Phase 44 read-only completion of the documented API resource groups."""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict


class ApiGroup(str, Enum):
    """Stable resource groups exposed in the public OpenAPI contract."""

    AUTH = "auth"
    TARGETS = "targets"
    TELEMETRY = "telemetry"
    WORKLOADS = "workloads"
    QUERY_SHAPES = "query-shapes"
    RUNS = "runs"
    CANDIDATES = "candidates"
    EVALUATIONS = "evaluations"
    ADMISSIONS = "admissions"
    APPROVALS = "approvals"
    LEDGER = "ledger"
    ROLLBACKS = "rollbacks"
    EXPERIENCE = "experience"
    BENCHMARKS = "benchmarks"
    SETTINGS = "settings"
    SYSTEM = "system"


class ApiGroupResponse(BaseModel):
    """An intentionally empty, truthful response until a durable read model is connected."""

    model_config = ConfigDict(frozen=True)

    group: ApiGroup
    status: str = "not_configured"
    records: tuple[()] = ()


router = APIRouter(prefix="/api/v1")


def _empty_group_response(group: ApiGroup) -> ApiGroupResponse:
    """Expose the completed route without fabricating unavailable control-plane records."""
    return ApiGroupResponse(group=group)


def _add_group_route(group: ApiGroup) -> None:
    async def get_group() -> ApiGroupResponse:
        return _empty_group_response(group)

    router.add_api_route(
        f"/{group.value}",
        get_group,
        methods=["GET"],
        response_model=ApiGroupResponse,
        tags=[group.value],
        operation_id=f"list_{group.value.replace('-', '_')}",
        summary=f"List {group.value}",
    )


for _group in ApiGroup:
    _add_group_route(_group)
