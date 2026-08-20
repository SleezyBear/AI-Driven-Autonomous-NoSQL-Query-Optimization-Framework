"""One shared lock preventing overlap between benchmarks and Ollama inference."""

from __future__ import annotations

from asyncio import Lock
from contextlib import asynccontextmanager
from typing import AsyncIterator


class BenchmarkOllamaIsolationLock:
    """Serialize benchmark measurement windows and all Ollama requests."""

    def __init__(self) -> None:
        self._lock = Lock()

    @asynccontextmanager
    async def benchmark_window(self) -> AsyncIterator[None]:
        """Acquire exclusive access for a controlled benchmark measurement window."""
        async with self._lock:
            yield

    @asynccontextmanager
    async def ollama_request(self) -> AsyncIterator[None]:
        """Acquire the same exclusive access for Ollama generation or embeddings."""
        async with self._lock:
            yield


shared_measurement_lock = BenchmarkOllamaIsolationLock()
