"""Phase 21 acceptance tests for structured advisory-only providers."""

import json

import httpx
import pytest

from app.ai.provider import DEFAULT_AI_PROVIDER, Diagnosis, FakeAIProvider, OllamaAIProvider, OpenAICompatibleAIProvider


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
    assert calls[0]["format"] == Diagnosis.model_json_schema()


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


@pytest.mark.asyncio
async def test_openai_compatible_provider_uses_local_fake_server_and_structured_contract() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"summary": "diagnosis", "evidence": ["metric"]})}}]})
        return httpx.Response(200, json={"data": [{"embedding": [1.0, 2.0]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://local-fake-server") as client:
        provider = OpenAICompatibleAIProvider(client, "chat", "embed")
        diagnosis = await provider.diagnose("evidence")
        embedding = await provider.embed_experience("experience")

    assert diagnosis.summary == "diagnosis"
    assert embedding.vector == (1.0, 2.0)
    assert calls[0][0] == "/v1/chat/completions"
    assert calls[0][1]["temperature"] == 0
    assert calls[0][1]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Diagnosis", "schema": Diagnosis.model_json_schema()},
    }
    assert calls[1] == ("/v1/embeddings", {"model": "embed", "input": "experience"})


@pytest.mark.asyncio
async def test_openai_compatible_provider_retries_malformed_output_and_ollama_stays_default() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://local-fake-server") as client:
        with pytest.raises(ValueError, match="twice"):
            await OpenAICompatibleAIProvider(client, "chat", "embed").diagnose("evidence")

    assert calls == 2
    assert DEFAULT_AI_PROVIDER == "ollama"


@pytest.mark.asyncio
async def test_provider_records_versioned_sanitized_structured_invocation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": json.dumps({"summary": "diagnosis", "evidence": []})})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama") as client:
        provider = OllamaAIProvider(client, "chat-model", "embed-model")
        await provider.diagnose("metric:p95")

    assert len(provider.invocations) == 1
    record = provider.invocations[0]
    assert record.prompt_version == "v1"
    assert record.model == "chat-model"
    assert len(record.input_hash) == 64
    assert "metric:p95" in record.sanitized_input
    assert record.structured_result["summary"] == "diagnosis"
    assert record.latency_ms >= 0
