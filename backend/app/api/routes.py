"""Persisted, paginated control-plane resource APIs."""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.auth.routes import current_principal
from app.auth.security import Principal


class ApiGroup(str, Enum):
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


class Page(BaseModel):
    group: ApiGroup
    records: list[dict[str, Any]]
    limit: int
    offset: int


class TargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    connection_label: str = Field(min_length=1, max_length=256)


router = APIRouter(prefix="/api/v1")
_REPOS = {
    ApiGroup.TELEMETRY: "telemetry",
    ApiGroup.WORKLOADS: "workloads",
    ApiGroup.QUERY_SHAPES: "query_shapes",
    ApiGroup.RUNS: "runs",
    ApiGroup.CANDIDATES: "candidates",
    ApiGroup.EVALUATIONS: "evaluations",
    ApiGroup.ADMISSIONS: "admissions",
    ApiGroup.APPROVALS: "approvals",
    ApiGroup.ROLLBACKS: "rollback",
    ApiGroup.EXPERIENCE: "experience",
    ApiGroup.BENCHMARKS: "jobs",
    ApiGroup.SETTINGS: "settings",
}


def _record(row: Any) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, (UUID, datetime)) else value
        for key, value in dict(row).items()
    }


async def _list(
    group: ApiGroup, request: Request, principal: Principal, limit: int, offset: int
) -> Page:
    if group is ApiGroup.SYSTEM:
        return Page(
            group=group,
            records=[{"status": "ready", "principal_id": principal.user_id}],
            limit=limit,
            offset=offset,
        )
    if group is ApiGroup.LEDGER:
        from sqlalchemy import text

        engine = request.app.state.control_plane.ledger._engine
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT * FROM production_ledger_entries ORDER BY created_at LIMIT :limit OFFSET :offset"
                        ),
                        {"limit": limit, "offset": offset},
                    )
                )
                .mappings()
                .all()
            )
        return Page(group=group, records=[_record(row) for row in rows], limit=limit, offset=offset)
    repository = getattr(
        request.app.state.control_plane, "targets" if group is ApiGroup.TARGETS else _REPOS[group]
    )
    rows = await repository.list()
    if group is ApiGroup.TARGETS:
        rows = tuple(row for row in rows if str(row["owner_user_id"]) == principal.user_id)
    return Page(
        group=group,
        records=[_record(row) for row in rows[offset : offset + limit]],
        limit=limit,
        offset=offset,
    )


def _add_read_route(group: ApiGroup) -> None:
    async def get_group(
        request: Request,
        principal: Principal = Depends(current_principal),
        limit: int = 50,
        offset: int = 0,
    ) -> Page:
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(status_code=422, detail="invalid pagination")
        return await _list(group, request, principal, limit, offset)

    router.add_api_route(
        f"/{group.value}",
        get_group,
        methods=["GET"],
        response_model=Page,
        tags=[group.value],
        operation_id=f"list_{group.value.replace('-', '_')}",
    )


for _group in ApiGroup:
    _add_read_route(_group)


@router.post("/targets", response_model=dict[str, Any])
async def create_target(
    body: TargetCreate, request: Request, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    created = await request.app.state.control_plane.targets.create(
        owner_user_id=UUID(principal.user_id),
        name=body.name,
        connection_label=body.connection_label,
        deployment_mode="APPROVAL_CONTROLLED",
        state="ACTIVE",
        is_active=True,
    )
    return _record(created)
