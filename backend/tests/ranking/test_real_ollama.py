"""Opt-in real-Ollama durability test for strictly validated candidate rankings."""

from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.contracts import Namespace
from app.adapters.fake import FakeDatabaseAdapter
from app.ai.provider import (
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    DiagnosisArtifactResult,
    DiagnosisFinding,
    DiagnosisFindingType,
    OllamaAIProvider,
)
from app.candidates.durable import CandidateGenerationService
from app.db import models
from app.diagnosis.durable import DiagnosisService
from app.ranking.durable import CandidateRankingService
from app.workloads.durable import WorkloadSnapshotService
from tests.diagnosis.test_durable_diagnosis import ControlledProvider, _run_with_snapshot


pytestmark = pytest.mark.skipif(
    os.environ.get("R19F_REAL_OLLAMA") != "1",
    reason="real Ollama acceptance gate only",
)


@pytest.mark.asyncio
async def test_real_ollama_persists_candidate_ranking(disposable_diagnosis_database: str) -> None:
    """A real model ranks exactly three fixed candidates, once, durably."""
    shapes = (
        {"hash": "rank-customer", "shape": '{"query":{"filter":{"customer_id":"<string>"},"sort":{"created_at":-1}}}'},
        {"hash": "rank-region", "shape": '{"query":{"filter":{"region":"<string>"},"sort":{"updated_at":-1}}}'},
        {"hash": "rank-status", "shape": '{"query":{"filter":{"status":"<string>"},"sort":{"priority":1}}}'},
    )
    engine = create_async_engine(disposable_diagnosis_database)
    client = httpx.AsyncClient(base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    try:
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
        generated = await CandidateGenerationService(
            engine, FakeDatabaseAdapter((Namespace("orders"),))
        ).create_for_run(run_id)
        assert generated.candidate_count == 3
        assert len(set(generated.candidate_ids)) == 3

        provider = OllamaAIProvider(
            client,
            os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:e4b"),
            os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma"),
            timeout_seconds=DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        )
        ranking_service = CandidateRankingService(engine, provider)
        first = await ranking_service.create_for_run(run_id)
        assert set(first.ordered_candidate_ids) == set(generated.candidate_ids)
        assert len(first.ordered_candidate_ids) == len(set(first.ordered_candidate_ids)) == 3
        assert await ranking_service.verify_ranking_integrity(first.artifact_id)

        async with engine.connect() as connection:
            artifact = (
                await connection.execute(
                    select(models.CandidateRankingArtifact.__table__).where(
                        models.CandidateRankingArtifact.__table__.c.id == first.artifact_id
                    )
                )
            ).mappings().one()
            invocation = (
                await connection.execute(
                    select(models.AIInvocation.__table__).where(
                        models.AIInvocation.__table__.c.id == artifact["ai_invocation_id"]
                    )
                )
            ).mappings().one()
        assert artifact["ordered_candidate_ids"] == [str(candidate_id) for candidate_id in first.ordered_candidate_ids]
        assert artifact["artifact_fingerprint"]
        assert invocation["provider"] == provider.provider_name
        assert invocation["model"] == provider.chat_model
        assert invocation["stage"] == "RANKING"
        assert invocation["prompt_version"] == "v1"
        assert invocation["schema_version"] == "candidate-ranking-v1"
        assert invocation["input_hash"] and invocation["output_hash"]
        assert set(invocation["validated_output"]["candidate_handles"]) == {"C1", "C2", "C3"}
        assert invocation["sanitized_input"]["candidate_handles"] == ["C1", "C2", "C3"]
        assert all(str(candidate_id) not in str(invocation["sanitized_input"]) for candidate_id in generated.candidate_ids)

        # A fresh engine/service reads the durable artifact, and strict reuse
        # does not make another advisory-model request.
        await client.aclose()
        await engine.dispose()
        engine = create_async_engine(disposable_diagnosis_database)
        fresh_client = httpx.AsyncClient(base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
        try:
            fresh_provider = OllamaAIProvider(
                fresh_client,
                os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:e4b"),
                os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma"),
                timeout_seconds=DEFAULT_OLLAMA_TIMEOUT_SECONDS,
            )
            recovered = await CandidateRankingService(engine, fresh_provider).create_for_run(run_id)
            assert recovered == first
            assert not fresh_provider.invocations
            assert await CandidateRankingService(engine, fresh_provider).verify_ranking_integrity(recovered.artifact_id)
        finally:
            await fresh_client.aclose()
    finally:
        await client.aclose()
        await engine.dispose()
