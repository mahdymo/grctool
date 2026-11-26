import httpx
import pytest
import respx

from app.resend_client import ResendClient, SendFailed


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds():
    client = ResendClient("re_test", base_url="https://api.resend.test", max_attempts=5)
    client.client = httpx.AsyncClient(
        base_url="https://api.resend.test",
        transport=httpx.MockTransport(
            _sequence([_resp(500), _resp(500), _resp(201, {"id": "email_123"})])
        ),
    )
    # no real sleeping in tests
    import app.resend_client as rc

    original_sleep = rc.asyncio.sleep
    rc.asyncio.sleep = _no_sleep
    try:
        email_id = await client.send(
            sender="a@b.c", to="x@y.z", subject="s", html="<p>h</p>",
            text="t", idempotency_key="k1",
        )
    finally:
        rc.asyncio.sleep = original_sleep
    assert email_id == "email_123"


@pytest.mark.asyncio
async def test_permanent_4xx_fails_immediately():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(422, json={"message": "invalid from"})

    client = ResendClient("re_test", base_url="https://api.resend.test", max_attempts=5)
    client.client = httpx.AsyncClient(
        base_url="https://api.resend.test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SendFailed):
        await client.send(
            sender="bad", to="x@y.z", subject="s", html="<p>h</p>",
            text="t", idempotency_key="k2",
        )
    assert len(calls) == 1


def _resp(status, body=None):
    return httpx.Response(status, json=body or {"message": "err"})


def _sequence(responses):
    iterator = iter(responses)

    def handler(request):
        return next(iterator)

    return handler


async def _no_sleep(_):
    return None
