"""PostgreSQL contracts for durable, exact candidate ranking."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.adapters.contracts import Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.ai.provider import CandidateHandleRanking, DiagnosisArtifactResult, DiagnosisFinding, DiagnosisFindingType, FakeAIProvider, RankingCandidateInput
from app.candidates.durable import CandidateGenerationService
from app.db import models
from app.diagnosis.durable import DiagnosisService
from app.ranking.durable import CandidateRankingError, CandidateRankingService
from app.workloads.durable import WorkloadSnapshotService
from tests.diagnosis.test_durable_diagnosis import ControlledProvider, _run_with_snapshot


class RankingProvider(FakeAIProvider):
    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
        self.calls = 0

    async def rank_candidate_handles(self, candidates: tuple[RankingCandidateInput, ...]) -> CandidateHandleRanking:
        self.calls += 1
        candidate_ids = tuple(candidate.handle for candidate in candidates)
        if self.mode == "valid":
            candidate_ids = (candidate_ids[1], candidate_ids[0], candidate_ids[2])
        elif self.mode == "unknown":
            candidate_ids = (*candidate_ids[:-1], "C4")
        elif self.mode == "foreign_uuid":
            candidate_ids = (*candidate_ids[:-1], "00000000-0000-0000-0000-000000000000")
        elif self.mode == "duplicate":
            candidate_ids = (candidate_ids[0], candidate_ids[0], candidate_ids[2])
        elif self.mode == "missing":
            candidate_ids = candidate_ids[:-1]
        elif self.mode == "extra":
            candidate_ids = (*candidate_ids, candidate_ids[-1])
        return CandidateHandleRanking(candidate_handles=candidate_ids, rationale="fixed advisory ordering")


async def _prepared_run(engine: AsyncEngine) -> tuple[UUID, tuple[UUID, ...]]:
    shapes = (
        {"hash": "rank-customer", "shape": '{"query":{"filter":{"customer_id":"<string>"},"sort":{"created_at":-1}}}'},
        {"hash": "rank-region", "shape": '{"query":{"filter":{"region":"<string>"},"sort":{"updated_at":-1}}}'},
        {"hash": "rank-status", "shape": '{"query":{"filter":{"status":"<string>"},"sort":{"priority":1}}}'},
    )
    _, run_id, snapshot_id = await _run_with_snapshot(engine, shapes)
    snapshot = await WorkloadSnapshotService(engine).read(snapshot_id)
    findings = tuple(
        DiagnosisFinding(
            finding_id=f"ranking-finding-{index}",
            finding_type=DiagnosisFindingType.SORT_INDEX_MISMATCH,
            summary="Observed structural filter and sort evidence needs an index review.",
            rationale="The immutable snapshot contains a high-cost normalized find shape.",
            query_shape_ids=(str(shape["query_shape_id"]),),
            evidence_refs=("QS:" + str(shape["id"]),),
        )
        for index, shape in enumerate(snapshot.query_shapes, start=1)
    )
    await DiagnosisService(engine, ControlledProvider(DiagnosisArtifactResult(findings=findings))).create_for_run(run_id)
    generated = await CandidateGenerationService(engine, FakeDatabaseAdapter((Namespace("orders"),))).create_for_run(run_id)
    assert generated.candidate_count == 3
    return run_id, generated.candidate_ids


@pytest.mark.asyncio
async def test_ranking_is_exact_durable_reusable_and_restart_safe(disposable_diagnosis_database: str) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    try:
        run_id, candidate_ids = await _prepared_run(engine)
        provider = RankingProvider()
        service = CandidateRankingService(engine, provider)
        async with engine.connect() as connection:
            deterministic_order = tuple(
                (
                    await connection.execute(
                        select(models.Candidate.__table__.c.id)
                        .where(models.Candidate.__table__.c.optimization_run_id == run_id)
                        .order_by(models.Candidate.__table__.c.deterministic_fingerprint)
                    )
                ).scalars().all()
            )
        first = await service.create_for_run(run_id)
        assert set(first.ordered_candidate_ids) == set(candidate_ids)
        assert first.ordered_candidate_ids == (deterministic_order[1], deterministic_order[0], deterministic_order[2])
        assert provider.calls == 1 and await service.verify_ranking_integrity(first.artifact_id)
        assert await service.create_for_run(run_id) == first and provider.calls == 1
        await engine.dispose()
        engine = create_async_engine(disposable_diagnosis_database)
        recovered = await CandidateRankingService(engine, RankingProvider()).create_for_run(run_id)
        assert recovered == first
        assert await CandidateRankingService(engine, RankingProvider()).verify_ranking_integrity(recovered.artifact_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_advisory_diagnosis_cannot_veto_measured_deterministic_candidates(
    disposable_diagnosis_database: str,
) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    shapes = (
        {
            "hash": "measured-find",
            "shape": '{"query":{"filter":{"customer_id":"<string>"}}}',
        },
    )
    try:
        _, run_id, _snapshot_id = await _run_with_snapshot(engine, shapes)
        diagnosis = await DiagnosisService(
            engine, ControlledProvider(DiagnosisArtifactResult())
        ).create_for_run(run_id)
        assert diagnosis.findings == ()
        generated = await CandidateGenerationService(
            engine, FakeDatabaseAdapter((Namespace("orders"),))
        ).create_for_run(run_id)
        assert generated.candidate_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("unknown", "foreign_uuid", "duplicate", "missing", "extra"))
async def test_ranking_rejects_unknown_duplicate_or_missing_candidate_ids(disposable_diagnosis_database: str, mode: str) -> None:
    engine = create_async_engine(disposable_diagnosis_database)
    try:
        run_id, _ = await _prepared_run(engine)
        with pytest.raises(CandidateRankingError, match="every persisted candidate exactly once"):
            await CandidateRankingService(engine, RankingProvider(mode)).create_for_run(run_id)
    finally:
        await engine.dispose()
