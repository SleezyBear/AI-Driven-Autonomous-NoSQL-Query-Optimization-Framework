"""Opt-in R19F real Ollama persistence integration."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from pymongo import AsyncMongoClient

from app.ai.provider import DEFAULT_OLLAMA_TIMEOUT_SECONDS, OllamaAIProvider
from app.diagnosis.durable import DiagnosisService
from app.telemetry.persistence import TelemetryPersistenceService
from app.telemetry.providers import CurrentOpTelemetryProvider
from app.workloads.durable import WorkloadSnapshotService

from tests.diagnosis.test_durable_diagnosis import _run_with_snapshot
from tests.workloads.test_durable_snapshot import _run


pytestmark = pytest.mark.skipif(os.environ.get("R19F_REAL_OLLAMA") != "1", reason="real Ollama acceptance gate only")


@pytest.mark.asyncio
async def test_real_ollama_persists_grounded_diagnosis(disposable_diagnosis_database: str) -> None:
    """A real configured chat model produces a durable, literal-free artifact."""
    engine = create_async_engine(disposable_diagnosis_database)
    client = httpx.AsyncClient(base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    try:
        _, run, _ = await _run_with_snapshot(engine)
        provider = OllamaAIProvider(
            client,
            os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:e4b"),
            os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma"),
            timeout_seconds=DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        )
        diagnosis = await DiagnosisService(engine, provider).create_for_run(run)
        assert await DiagnosisService(engine, provider).verify_diagnosis_integrity(diagnosis.diagnosis_id)
        assert diagnosis.schema_version == "r19f-diagnosis-v1"
        async with engine.connect() as connection:
            from sqlalchemy import text

            recorded = str((await connection.execute(text("SELECT provider || ':' || model || ':' || prompt_version || ':' || input_hash FROM ai_invocations WHERE id=:id"), {"id": diagnosis.ai_invocation_id})).scalar_one())
        assert provider.provider_name in recorded and provider.chat_model in recorded
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_currentop_snapshot_to_diagnosis_remains_non_autonomous(disposable_diagnosis_database: str) -> None:
    """Observe first, then infer: currentOp remains non-autonomous evidence."""
    engine = create_async_engine(disposable_diagnosis_database)
    client = httpx.AsyncClient(base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    mongo = AsyncMongoClient("mongodb://control_plane_root:control_plane_root_dev_only@127.0.0.1:27017/admin?authSource=admin&directConnection=true")
    try:
        _, target, run = await _run(engine)
        collection = mongo.get_database(f"r19f_currentop_acceptance_{uuid4().hex}").get_collection("orders")
        inserted = await collection.insert_one({"customer_email": "R19F_CURRENTOP_CANARY@example.test"})

        async def slow_query() -> None:
            await collection.find_one({"$where": "sleep(2500) || true"})

        pending = asyncio.create_task(slow_query())
        await asyncio.sleep(0.25)
        provider = CurrentOpTelemetryProvider(mongo.get_database("admin"))
        assert await provider.available()
        await TelemetryPersistenceService(engine).collect_and_persist(target, provider)
        await pending
        snapshot = await WorkloadSnapshotService(engine).create_for_run(run)
        async with engine.begin() as connection:
            from sqlalchemy import text

            await connection.execute(text("UPDATE optimization_runs SET status='DIAGNOSING' WHERE id=:id"), {"id": run})
        ai_provider = OllamaAIProvider(client, os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:e4b"), os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma"), timeout_seconds=DEFAULT_OLLAMA_TIMEOUT_SECONDS)
        diagnosis = await DiagnosisService(engine, ai_provider).create_for_run(run)
        read = await WorkloadSnapshotService(engine).read(snapshot.snapshot_id)
        assert read.metadata["completeness"]["production_autonomy_eligible"] is False
        assert await DiagnosisService(engine, ai_provider).verify_diagnosis_integrity(diagnosis.diagnosis_id)
    finally:
        if "inserted" in locals():
            await collection.delete_one({"_id": inserted.inserted_id})
        await mongo.close()
        await client.aclose()
        await engine.dispose()
