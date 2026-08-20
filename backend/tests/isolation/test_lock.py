"""Phase 22 acceptance tests for bidirectional benchmark/Ollama exclusion."""

import asyncio

import pytest

from app.isolation.lock import BenchmarkOllamaIsolationLock


@pytest.mark.asyncio
async def test_ollama_waits_for_active_benchmark() -> None:
    lock = BenchmarkOllamaIsolationLock()
    benchmark_started = asyncio.Event()
    benchmark_release = asyncio.Event()
    ollama_entered = asyncio.Event()

    async def benchmark() -> None:
        async with lock.benchmark_window():
            benchmark_started.set()
            await benchmark_release.wait()

    async def ollama() -> None:
        async with lock.ollama_request():
            ollama_entered.set()

    benchmark_task = asyncio.create_task(benchmark())
    await benchmark_started.wait()
    ollama_task = asyncio.create_task(ollama())
    await asyncio.sleep(0)
    assert not ollama_entered.is_set()
    benchmark_release.set()
    await benchmark_task
    await ollama_task
    assert ollama_entered.is_set()


@pytest.mark.asyncio
async def test_benchmark_waits_for_active_ollama_request() -> None:
    lock = BenchmarkOllamaIsolationLock()
    ollama_started = asyncio.Event()
    ollama_release = asyncio.Event()
    benchmark_entered = asyncio.Event()

    async def ollama() -> None:
        async with lock.ollama_request():
            ollama_started.set()
            await ollama_release.wait()

    async def benchmark() -> None:
        async with lock.benchmark_window():
            benchmark_entered.set()

    ollama_task = asyncio.create_task(ollama())
    await ollama_started.wait()
    benchmark_task = asyncio.create_task(benchmark())
    await asyncio.sleep(0)
    assert not benchmark_entered.is_set()
    ollama_release.set()
    await ollama_task
    await benchmark_task
    assert benchmark_entered.is_set()
