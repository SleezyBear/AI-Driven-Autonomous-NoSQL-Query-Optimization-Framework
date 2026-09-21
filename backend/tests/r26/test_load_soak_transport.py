from __future__ import annotations

import httpx
import pytest

from scripts.r26_load_soak import get_poll_response


@pytest.mark.asyncio
async def test_idempotent_poll_recovers_one_transport_disconnect() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.RemoteProtocolError("peer disconnected", request=request)
        return httpx.Response(200, json={"records": []}, request=request)

    async with httpx.AsyncClient(
        base_url="http://qualification.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        response, recovered = await get_poll_response(client, "/runs", headers={})

    assert response.status_code == 200
    assert recovered is True
    assert attempts == 2


@pytest.mark.asyncio
async def test_idempotent_poll_fails_after_second_transport_disconnect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer disconnected", request=request)

    async with httpx.AsyncClient(
        base_url="http://qualification.invalid",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(httpx.RemoteProtocolError):
            await get_poll_response(client, "/runs", headers={})
