"""Durable, strictly validated advisory candidate ranking."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.provider import AIProvider, CandidateHandleRanking, RankingCandidateInput
from app.db import models
from app.db.repositories import CandidateRankingRepository, PostgresRepository


class CandidateRankingError(ValueError):
    """Advisory output cannot be used as a ranking artifact."""


@dataclass(frozen=True)
class CandidateRankingResult:
    artifact_id: UUID
    ordered_candidate_ids: tuple[UUID, ...]


class CandidateRankingService:
    """Persist an advisory ordering only after it exactly covers fixed candidates."""

    def __init__(self, engine: AsyncEngine, provider: AIProvider) -> None:
        self._engine = engine
        self._provider = provider

    async def create_for_run(self, run_id: UUID) -> CandidateRankingResult:
        existing = await self._existing(run_id)
        if existing is not None:
            return existing
        payload = await self._load(run_id)
        # Inference deliberately occurs outside a database transaction.
        transport = tuple(
            RankingCandidateInput(handle=f"C{index}", safe_summary=summary)
            for index, summary in enumerate(payload["summaries"], start=1)
        )
        handle_to_id = {candidate.handle: candidate_id for candidate, candidate_id in zip(transport, payload["candidate_ids"], strict=True)}
        result = await self._provider.rank_candidate_handles(transport)
        expected_handles = tuple(candidate.handle for candidate in transport)
        received_handles = tuple(result.candidate_handles)
        if len(received_handles) != len(expected_handles) or set(received_handles) != set(expected_handles) or len(set(received_handles)) != len(received_handles):
            raise CandidateRankingError("ranking must contain every persisted candidate exactly once")
        received = tuple(str(handle_to_id[handle]) for handle in received_handles)
        expected = tuple(str(candidate_id) for candidate_id in payload["candidate_ids"])
        if len(received) != len(expected) or set(received) != set(expected) or len(set(received)) != len(received):
            raise CandidateRankingError("ranking must contain every persisted candidate exactly once")
        invocation_payload = result.model_dump(mode="json")
        async with self._engine.begin() as connection:
            current = (await connection.execute(select(models.CandidateRankingArtifact.__table__).where(models.CandidateRankingArtifact.__table__.c.optimization_run_id == run_id).with_for_update())).mappings().one_or_none()
            if current is not None:
                return CandidateRankingResult(current["id"], tuple(UUID(value) for value in current["ordered_candidate_ids"]))
            # Generic repository needs a concrete model at runtime.
            ai: PostgresRepository[models.AIInvocation] = PostgresRepository(self._engine)
            ai.model = models.AIInvocation
            ai_row = await ai.create_in_transaction(
                connection,
                optimization_run_id=run_id,
                stage="RANKING",
                provider=self._provider.provider_name,
                model=self._provider.chat_model,
                prompt_version="v1",
                schema_version="candidate-ranking-v1",
                workload_snapshot_id=payload["snapshot_id"],
                input_hash=_hash({"candidate_handles": expected_handles, "summaries": payload["summaries"]}),
                sanitized_input={"candidate_handles": expected_handles, "candidate_summaries": payload["summaries"]},
                output_hash=_hash(invocation_payload),
                validated_output=invocation_payload,
                latency_ms=0.0,
                status="COMPLETED",
                safe_error_code=None,
                completed_at=datetime.now(timezone.utc),
                attempt_number=1,
            )
            ordered = [str(candidate_id) for candidate_id in received]
            row = await CandidateRankingRepository(self._engine).create_in_transaction(
                connection,
                optimization_run_id=run_id,
                generation_artifact_id=payload["generation_id"],
                ai_invocation_id=ai_row["id"],
                ordered_candidate_ids=ordered,
                artifact_fingerprint=_hash({"run_id": str(run_id), "generation": str(payload["generation_id"]), "ordered": ordered, "output": invocation_payload}),
            )
        return CandidateRankingResult(row["id"], tuple(UUID(value) for value in ordered))

    async def _existing(self, run_id: UUID) -> CandidateRankingResult | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(models.CandidateRankingArtifact.__table__).where(models.CandidateRankingArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
        return None if row is None else CandidateRankingResult(row["id"], tuple(UUID(value) for value in row["ordered_candidate_ids"]))

    async def verify_ranking_integrity(self, artifact_id: UUID) -> bool:
        """Verify that a persisted ranking still binds its validated AI output.

        The artifact is append-only in PostgreSQL, but this explicit verifier is
        also useful after a process restart and makes the durable boundary
        independently auditable.
        """
        async with self._engine.connect() as connection:
            artifact = (
                await connection.execute(
                    select(models.CandidateRankingArtifact.__table__).where(
                        models.CandidateRankingArtifact.__table__.c.id == artifact_id
                    )
                )
            ).mappings().one_or_none()
            if artifact is None:
                return False
            invocation = (
                await connection.execute(
                    select(models.AIInvocation.__table__).where(
                        models.AIInvocation.__table__.c.id == artifact["ai_invocation_id"]
                    )
                )
            ).mappings().one_or_none()
        if invocation is None or invocation["stage"] != "RANKING" or invocation["status"] != "COMPLETED":
            return False
        output = invocation["validated_output"]
        if not isinstance(output, dict):
            return False
        try:
            validated = CandidateHandleRanking.model_validate(output)
            ordered = tuple(str(value) for value in artifact["ordered_candidate_ids"])
            async with self._engine.connect() as connection:
                candidates = (
                    await connection.execute(
                        select(models.Candidate.__table__.c.id)
                        .where(models.Candidate.__table__.c.optimization_run_id == artifact["optimization_run_id"])
                        .order_by(models.Candidate.__table__.c.deterministic_fingerprint)
                    )
                ).scalars().all()
            handles = tuple(f"C{index}" for index, _ in enumerate(candidates, start=1))
            if len(validated.candidate_handles) != len(handles) or set(validated.candidate_handles) != set(handles) or len(set(validated.candidate_handles)) != len(validated.candidate_handles):
                return False
            handle_to_id = {handle: str(candidate_id) for handle, candidate_id in zip(handles, candidates, strict=True)}
            if tuple(handle_to_id[handle] for handle in validated.candidate_handles) != ordered:
                return False
        except (TypeError, ValueError):
            return False
        expected = _hash({"run_id": str(artifact["optimization_run_id"]), "generation": str(artifact["generation_artifact_id"]), "ordered": list(ordered), "output": output})
        return bool(artifact["artifact_fingerprint"] == expected)

    async def _load(self, run_id: UUID) -> dict[str, Any]:
        async with self._engine.connect() as connection:
            run = (await connection.execute(select(models.OptimizationRun.__table__).where(models.OptimizationRun.__table__.c.id == run_id))).mappings().one_or_none()
            generation = (await connection.execute(select(models.CandidateGenerationArtifact.__table__).where(models.CandidateGenerationArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
            diagnosis = (await connection.execute(select(models.DiagnosisArtifact.__table__).where(models.DiagnosisArtifact.__table__.c.optimization_run_id == run_id))).mappings().one_or_none()
            candidates = (await connection.execute(select(models.Candidate.__table__).where(models.Candidate.__table__.c.optimization_run_id == run_id).order_by(models.Candidate.__table__.c.deterministic_fingerprint))).mappings().all()
            actions = (await connection.execute(select(models.CandidateAction.__table__).where(models.CandidateAction.__table__.c.candidate_id.in_([candidate["id"] for candidate in candidates])))).mappings().all() if candidates else []
            findings = (await connection.execute(select(models.DiagnosisFinding.__table__.c.evidence_refs).where(models.DiagnosisFinding.__table__.c.diagnosis_artifact_id == diagnosis["id"]))).scalars().all() if diagnosis else []
        if run is None or run["workload_snapshot_id"] is None or generation is None or diagnosis is None or generation["candidate_count"] == 0:
            raise CandidateRankingError("a non-empty completed generation artifact is required")
        if len(candidates) != generation["candidate_count"]:
            raise CandidateRankingError("generation artifact candidate count mismatch")
        action_by_candidate = {action["candidate_id"]: action for action in actions}
        summaries = []
        for candidate in candidates:
            action = action_by_candidate.get(candidate["id"])
            if action is None:
                raise CandidateRankingError("candidate action is missing")
            # Candidate identity is assigned by PostgreSQL.  The advisory
            # transport receives only an opaque handle plus this safe summary.
            summaries.append(json.dumps({"action_type": action["action_type"], "typed_action": action["action_payload"], "policy_classification": candidate["policy_classification"]}, sort_keys=True, separators=(",", ":")))
        return {"snapshot_id": run["workload_snapshot_id"], "generation_id": generation["id"], "candidate_ids": tuple(candidate["id"] for candidate in candidates), "summaries": tuple(summaries), "evidence_refs": sorted({ref for refs in findings for ref in refs})}


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
