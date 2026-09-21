"""Durable, deterministic, metadata-checked candidate generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.contracts import DatabaseAdapter, Namespace as AdapterNamespace
from app.candidates.index_generator import DeterministicIndexGenerator, FindQueryShape
from app.db import models
from app.db.repositories import CandidateActionRepository, CandidateGenerationRepository, CandidateRepository


class CandidateGenerationError(ValueError):
    """The persisted inputs cannot safely produce executable candidates."""


@dataclass(frozen=True)
class CandidateGenerationResult:
    artifact_id: UUID
    candidate_ids: tuple[UUID, ...]
    candidate_count: int


class CandidateGenerationService:
    """Create exactly one immutable generation artifact for a durable run."""

    def __init__(self, engine: AsyncEngine, adapter: DatabaseAdapter) -> None:
        self._engine = engine
        self._adapter = adapter
        self._generator = DeterministicIndexGenerator()

    async def create_for_run(self, run_id: UUID) -> CandidateGenerationResult:
        existing = await self._existing(run_id)
        if existing is not None:
            return existing
        inputs = await self._load_inputs(run_id)
        indexes = await self._index_metadata(inputs)
        definitions = self._definitions(inputs, indexes)
        # External adapter reads have completed before the short persistence transaction.
        async with self._engine.begin() as connection:
            artifact = (await connection.execute(select(models.CandidateGenerationArtifact.__table__).where(models.CandidateGenerationArtifact.__table__.c.optimization_run_id == run_id).with_for_update())).mappings().one_or_none()
            if artifact is not None:
                rows = (await connection.execute(select(models.Candidate.__table__.c.id).where(models.Candidate.__table__.c.optimization_run_id == run_id).order_by(models.Candidate.__table__.c.deterministic_fingerprint))).scalars().all()
                return CandidateGenerationResult(artifact["id"], tuple(rows), int(artifact["candidate_count"]))
            candidate_ids: list[UUID] = []
            fingerprints: list[str] = []
            for definition in definitions:
                payload = definition["action"].model_dump(mode="json")
                fingerprint = definition["fingerprint"]
                candidate_hash = _hash({"run_id": str(run_id), "fingerprint": fingerprint})
                row = await CandidateRepository(self._engine).create_in_transaction(
                    connection,
                    optimization_run_id=run_id,
                    query_shape_id=definition["query_shape_id"],
                    status=models.CandidateStatus.PROPOSED,
                    candidate_hash=candidate_hash,
                    source_snapshot_id=inputs["snapshot_id"],
                    source_diagnosis_id=inputs["diagnosis_id"],
                    deterministic_fingerprint=fingerprint,
                    generation_rule_id=self._generator.generation_rule_id,
                    generation_rule_version=self._generator.generation_rule_version,
                    affected_query_shape_ids=[str(definition["query_shape_id"])],
                    evidence_refs=definition["evidence_refs"],
                    # This value is consumed by the immutable authority boundary.
                    # It means only that the typed action may be considered for
                    # autonomy after deterministic/statistical admission; it is
                    # not itself deployment authority.
                    policy_classification="AUTO_ELIGIBLE_AFTER_ADMISSION",
                )
                await CandidateActionRepository(self._engine).create_in_transaction(
                    connection, candidate_id=row["id"], action_type="CREATE_INDEX", action_payload=payload, reversible=True
                )
                candidate_ids.append(row["id"])
                fingerprints.append(fingerprint)
            artifact_fingerprint = _hash({"run_id": str(run_id), "snapshot": str(inputs["snapshot_id"]), "diagnosis": str(inputs["diagnosis_id"]), "generator": self._generator.generation_rule_version, "candidates": fingerprints})
            artifact_row = await CandidateGenerationRepository(self._engine).create_in_transaction(
                connection,
                optimization_run_id=run_id,
                workload_snapshot_id=inputs["snapshot_id"],
                diagnosis_artifact_id=inputs["diagnosis_id"],
                generator_version=self._generator.generation_rule_version,
                candidate_count=len(candidate_ids),
                ordered_candidate_fingerprints=fingerprints,
                artifact_fingerprint=artifact_fingerprint,
                completed_at=datetime.now(timezone.utc),
            )
            return CandidateGenerationResult(artifact_row["id"], tuple(candidate_ids), len(candidate_ids))

    async def _existing(self, run_id: UUID) -> CandidateGenerationResult | None:
        async with self._engine.connect() as connection:
            artifact = (await connection.execute(select(models.CandidateGenerationArtifact.__table__).where(models.CandidateGenerationArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
            if artifact is None:
                return None
            rows = (await connection.execute(select(models.Candidate.__table__.c.id).where(models.Candidate.__table__.c.optimization_run_id == run_id).order_by(models.Candidate.__table__.c.deterministic_fingerprint))).scalars().all()
        if len(rows) != artifact["candidate_count"]:
            raise CandidateGenerationError("candidate generation artifact does not match persisted candidates")
        return CandidateGenerationResult(artifact["id"], tuple(rows), int(artifact["candidate_count"]))

    async def _load_inputs(self, run_id: UUID) -> dict[str, Any]:
        async with self._engine.connect() as connection:
            run = (await connection.execute(select(models.OptimizationRun.__table__).where(models.OptimizationRun.__table__.c.id == run_id))).mappings().one_or_none()
            if run is None or run["workload_snapshot_id"] is None:
                raise CandidateGenerationError("immutable workload snapshot is required")
            diagnosis = (await connection.execute(select(models.DiagnosisArtifact.__table__).where(models.DiagnosisArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
            if diagnosis is None or diagnosis["workload_snapshot_id"] != run["workload_snapshot_id"] or diagnosis["target_id"] != run["target_id"]:
                raise CandidateGenerationError("durable diagnosis does not match run snapshot and target")
            findings = (await connection.execute(select(models.DiagnosisFinding.__table__).where(models.DiagnosisFinding.__table__.c.diagnosis_artifact_id == diagnosis["id"]))).mappings().all()
            shapes = (await connection.execute(select(models.WorkloadSnapshotQueryShape.__table__, models.QueryShape.__table__.c.normalized_shape, models.Namespace.__table__.c.name.label("real_namespace"), models.Namespace.__table__.c.allowlisted).join(models.QueryShape.__table__, models.QueryShape.__table__.c.id == models.WorkloadSnapshotQueryShape.__table__.c.query_shape_id).join(models.Namespace.__table__, models.Namespace.__table__.c.id == models.QueryShape.__table__.c.namespace_id).where(models.WorkloadSnapshotQueryShape.__table__.c.workload_snapshot_id == run["workload_snapshot_id"]))).mappings().all()
        allowed_ids = {str(shape["query_shape_id"]) for shape in shapes}
        referenced: dict[str, list[str]] = {}
        for finding in findings:
            for shape_id in finding["query_shape_ids"]:
                if shape_id in allowed_ids:
                    referenced.setdefault(shape_id, []).extend(str(ref) for ref in finding["evidence_refs"])
        # The advisory model may legitimately return no findings. It must not
        # become a hidden veto over deterministic candidate generation when the
        # immutable snapshot itself proves an execution-time-protected find
        # shape. Admission and authority remain independent downstream gates.
        for shape in shapes:
            shape_id = str(shape["query_shape_id"])
            if (
                str(shape["operation"]) == "find"
                and bool(shape["protected_execution_time_share"])
            ):
                referenced.setdefault(shape_id, []).append(f"QS:{shape['id']}")
        return {"snapshot_id": run["workload_snapshot_id"], "diagnosis_id": diagnosis["id"], "shapes": tuple(shape for shape in shapes if str(shape["query_shape_id"]) in referenced), "evidence": referenced}

    async def _index_metadata(self, inputs: dict[str, Any]) -> dict[str, set[tuple[tuple[str, int], ...]]]:
        accessible = {namespace.collection for namespace in await self._adapter.list_namespaces()}
        result: dict[str, set[tuple[tuple[str, int], ...]]] = {}
        for shape in inputs["shapes"]:
            namespace = str(shape["real_namespace"])
            database, separator, collection = namespace.partition(".")
            if not separator or not shape["allowlisted"] or collection not in accessible:
                continue
            indexes = await self._adapter.list_indexes(AdapterNamespace(collection))
            result[namespace] = {tuple(index.keys) for index in indexes}
        return result

    def _definitions(self, inputs: dict[str, Any], indexes: dict[str, set[tuple[tuple[str, int], ...]]]) -> list[dict[str, Any]]:
        definitions: list[dict[str, Any]] = []
        seen: set[str] = set()
        evidence = inputs["evidence"]
        for shape in sorted(inputs["shapes"], key=lambda item: str(item["query_shape_id"])):
            namespace = str(shape["real_namespace"])
            database, separator, collection = namespace.partition(".")
            if not separator or namespace not in indexes:
                continue
            structural = shape["normalized_shape"]
            fields = _find_fields(structural)
            if fields is None:
                continue
            generated = self._generator.generate(FindQueryShape(str(shape["query_shape_hash"]), database, collection, *fields))
            for candidate in generated:
                keys = tuple((field.field, field.direction) for field in candidate.action.fields)
                if keys in indexes[namespace] or candidate.candidate_fingerprint in seen:
                    continue
                seen.add(candidate.candidate_fingerprint)
                definitions.append({"query_shape_id": shape["query_shape_id"], "fingerprint": candidate.candidate_fingerprint, "action": candidate.action, "evidence_refs": sorted(set(evidence[str(shape["query_shape_id"])]))})
        return definitions


def _find_fields(shape: object) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...], tuple[str, ...]] | None:
    """Extract only structural field names from canonical persisted query shape."""
    if not isinstance(shape, dict):
        return None
    query = shape.get("query", shape)
    if not isinstance(query, dict):
        return None
    filter_doc = query.get("filter", query.get("query", {}))
    if not isinstance(filter_doc, dict):
        filter_doc = {}
    equality: list[str] = []
    ranges: list[str] = []
    for field, value in filter_doc.items():
        if field.startswith("$") or not isinstance(field, str):
            continue
        if isinstance(value, dict) and any(str(operator) in {"$gt", "$gte", "$lt", "$lte"} for operator in value):
            ranges.append(field)
        else:
            equality.append(field)
    sort_doc = query.get("sort", {})
    sorts: list[tuple[str, int]] = []
    if isinstance(sort_doc, dict):
        for field, direction in sort_doc.items():
            if isinstance(field, str) and direction in (-1, 1):
                sorts.append((field, int(direction)))
    return tuple(sorted(set(equality))), tuple(sorts), tuple(sorted(set(ranges)))


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
