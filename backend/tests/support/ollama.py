"""Test-only Ollama runtime isolation for expensive real-AI acceptance cases."""

from __future__ import annotations

import asyncio
import os
import time

import httpx


async def unload_chat_model() -> None:
    """Release the configured model and wait until Ollama reports it nonresident.

    This is intentionally test-harness behavior.  Production provider requests
    retain their configured residency policy.
    """
    model = os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:e4b")
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        response = await client.post("/api/generate", json={"model": model, "keep_alive": 0})
        response.raise_for_status()
        deadline = time.monotonic() + 30.0
        while True:
            resident = (await client.get("/api/ps")).json().get("models", [])
            if not any(isinstance(item, dict) and item.get("name") == model for item in resident):
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Ollama model remained resident after test unload: {model}")
            await asyncio.sleep(0.25)
