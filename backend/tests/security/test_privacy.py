"""Phase 40 acceptance tests for privacy modes and external evidence boundaries."""

import json

import httpx
import pytest

from app.ai.provider import OllamaAIProvider
from app.security.privacy import PrivacyBoundary, PrivacyMode


KNOWN_EMAIL = "alice.private@example.test"
KNOWN_ID = "customer-123456"


@pytest.mark.parametrize("mode", (PrivacyMode.LOCAL_NORMALIZED, PrivacyMode.STRICT_HASHED))
def test_privacy_modes_keep_known_literals_out_of_logs_and_postgres_evidence(mode: PrivacyMode) -> None:
    boundary = PrivacyBoundary(mode, hmac_key="test-privacy-key")
    source = {"email": KNOWN_EMAIL, "customer_id": KNOWN_ID, "count": 7}

    log_payload = json.dumps(boundary.for_log(source), sort_keys=True)
    postgres_evidence = boundary.serialize_for_postgres(source)

    assert KNOWN_EMAIL not in log_payload
    assert KNOWN_ID not in log_payload
    assert KNOWN_EMAIL not in postgres_evidence
    assert KNOWN_ID not in postgres_evidence
    if mode is PrivacyMode.LOCAL_NORMALIZED:
        assert "<string>" in postgres_evidence
    else:
        assert "hmac-sha256:" in postgres_evidence


@pytest.mark.asyncio
async def test_known_literals_are_absent_from_the_captured_ollama_request() -> None:
    captured: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append({"path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": json.dumps({"summary": "safe", "evidence": []})}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama.test") as client:
        await OllamaAIProvider(client, "chat", "embed").diagnose(f"email={KNOWN_EMAIL}; id={KNOWN_ID}")

    captured_request = captured[0]
    assert captured_request["path"] == "/api/chat"
    request_body = captured_request["body"]
    assert isinstance(request_body, dict)
    assert request_body["stream"] is False
    assert isinstance(request_body["format"], dict)
    assert isinstance(request_body["messages"], list)
    assert request_body["options"] == {"temperature": 0}

    serialized_request = json.dumps(captured_request, sort_keys=True)
    assert KNOWN_EMAIL not in serialized_request
    assert KNOWN_ID not in serialized_request
