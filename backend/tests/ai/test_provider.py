"""Phase 21 acceptance tests for structured advisory-only providers."""

import json

import httpx
import pytest

from app.ai.provider import FakeAIProvider, OllamaAIProvider


@pytest.mark.asyncio
async def test_ollama_uses_temperature_zero_and_returns_structured_output() -> None:
    calls: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps({"summary": "diagnosis", "evidence": ["metric"]})})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama") as client:
        result = await OllamaAIProvider(client, "chat", "embed").diagnose("evidence")

    assert result.summary == "diagnosis"
    assert calls[0]["options"] == {"temperature": 0}
    assert calls[0]["format"] == "json"


@pytest.mark.asyncio
async def test_ollama_retries_malformed_structured_output_once_then_fails() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"response": "not-json"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama") as client:
        with pytest.raises(ValueError, match="twice"):
            await OllamaAIProvider(client, "chat", "embed").diagnose("evidence")

    assert calls == 2


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic_and_advisory_only() -> None:
    provider = FakeAIProvider()

    assert (await provider.rank_candidates(("b", "a"))).candidate_ids == ("a", "b")
    assert (await provider.embed_experience("abc")).vector == (3.0,)
