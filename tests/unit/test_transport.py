"""Unit tests for the transport layer."""

import asyncio
import base64
import dataclasses
import datetime as dt
import threading
from typing import cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from nukapy._internal.retry import RetryPolicy, retry_after_delay
from nukapy.errors import (
    AuthenticationError,
    BadGatewayError,
    BadRequestError,
    ForbiddenError,
    GatewayTimeoutError,
    HTTPError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
)
from nukapy.transport import AsyncTransport, Request, Response, Transport

TEST_URL = "https://example.test/resource/abcd-1234.json"
TEST_PATH = "/resource/abcd-1234.json"
HTTP_OK = 200
RETRY_ONCE_ATTEMPTS = 2
MAX_ATTEMPTS = 3
RATE_LIMIT = 1000
CONCURRENCY_LIMIT = 3
DEFAULT_CONCURRENCY_LIMIT = 8
JITTER_MAX_DELAY = 5.0
HEADER_MAX_DELAY = 60.0


def test_request_is_frozen() -> None:
    request = Request(method="GET", path=TEST_PATH)

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.path = "/other.json"  # type: ignore[misc]


def test_response_json_and_text() -> None:
    response = Response(
        status=200,
        headers={},
        content=b'{"ok": true}',
    )

    assert response.json() == {"ok": True}
    assert response.text() == '{"ok": true}'


def test_response_json_is_lazy() -> None:
    response = Response(status=200, headers={}, content=b'{"ok": true}')

    with patch("nukapy.transport.json.loads", return_value={"ok": True}) as loads:
        assert response.json() == {"ok": True}
        assert response.json() == {"ok": True}

    loads.assert_called_once_with(b'{"ok": true}')


@respx.mock
async def test_async_transport_get_returns_json() -> None:
    route = respx.get(TEST_URL).mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with AsyncTransport(domain="example.test", app_token="token") as transport:
        response = await transport.request(Request(method="GET", path=TEST_PATH))

    assert response.status_code == HTTP_OK
    assert response.json() == {"ok": True}
    assert route.called


@respx.mock
@pytest.mark.parametrize(
    ("app_token", "expected"),
    [("abc123", "abc123"), (None, None)],
)
async def test_async_transport_auth_header(
    app_token: str | None, expected: str | None
) -> None:
    respx.get(TEST_URL).mock(return_value=httpx.Response(200, json=[]))

    async with AsyncTransport(domain="example.test", app_token=app_token) as transport:
        await transport.request(Request(method="GET", path=TEST_PATH))

    request_headers = respx.calls.last.request.headers
    if expected is None:
        assert "X-App-Token" not in request_headers
    else:
        assert request_headers["X-App-Token"] == expected


@respx.mock
async def test_async_transport_base_headers_user_agent_and_basic_auth() -> None:
    respx.get(TEST_URL).mock(return_value=httpx.Response(200, json=[]))

    async with AsyncTransport(
        domain="example.test",
        username="user",
        password="pass",
        user_agent="nukapy-test",
        base_headers={"X-Base": "base"},
    ) as transport:
        await transport.request(
            Request(method="GET", path=TEST_PATH, headers={"X-Request": "request"})
        )

    headers = respx.calls.last.request.headers
    credentials = base64.b64encode(b"user:pass").decode()
    assert headers["Authorization"] == f"Basic {credentials}"
    assert headers["User-Agent"] == "nukapy-test"
    assert headers["X-Base"] == "base"
    assert headers["X-Request"] == "request"


@respx.mock
async def test_async_transport_api_key_secret_use_basic_auth() -> None:
    respx.get(TEST_URL).mock(return_value=httpx.Response(200, json=[]))

    async with AsyncTransport(
        domain="example.test", api_key="key-id", secret="key-secret"
    ) as transport:
        await transport.request(Request(method="GET", path=TEST_PATH))

    credentials = base64.b64encode(b"key-id:key-secret").decode()
    assert respx.calls.last.request.headers["Authorization"] == f"Basic {credentials}"


@respx.mock
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, ForbiddenError),
        (404, NotFoundError),
        (429, RateLimitError),
        (418, HTTPError),
        (500, HTTPError),
        (502, BadGatewayError),
        (503, ServiceUnavailableError),
        (504, GatewayTimeoutError),
    ],
)
async def test_http_error_mapping(
    status_code: int, error_type: type[HTTPError]
) -> None:
    respx.get(TEST_URL).mock(
        return_value=httpx.Response(status_code, content=b"error body")
    )

    async with AsyncTransport(
        domain="example.test", retry_policy=RetryPolicy(max_attempts=1)
    ) as transport:
        with pytest.raises(error_type) as exc_info:
            await transport.request(Request(method="GET", path=TEST_PATH))

    assert exc_info.value.status_code == status_code
    assert exc_info.value.request_url == TEST_URL
    assert exc_info.value.response_body == "error body"


@respx.mock
async def test_retry_on_503_then_success() -> None:
    route = respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(503, content=b"try again"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        async with AsyncTransport(
            domain="example.test", retry_policy=RetryPolicy(base_delay=0.1)
        ) as transport:
            response = await transport.request(Request(method="GET", path=TEST_PATH))

    assert response.json() == {"ok": True}
    assert route.call_count == RETRY_ONCE_ATTEMPTS
    sleep_mock.assert_awaited_once()


@respx.mock
async def test_exhausted_retries_raises_last_error() -> None:
    route = respx.get(TEST_URL).mock(return_value=httpx.Response(503))

    with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        async with AsyncTransport(
            domain="example.test",
            retry_policy=RetryPolicy(max_attempts=MAX_ATTEMPTS, base_delay=0.1),
        ) as transport:
            with pytest.raises(ServiceUnavailableError):
                await transport.request(Request(method="GET", path=TEST_PATH))

    assert route.call_count == MAX_ATTEMPTS
    assert sleep_mock.await_count == RETRY_ONCE_ATTEMPTS


@respx.mock
async def test_no_retry_on_401() -> None:
    route = respx.get(TEST_URL).mock(return_value=httpx.Response(401))

    with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        async with AsyncTransport(
            domain="example.test", retry_policy=RetryPolicy(max_attempts=MAX_ATTEMPTS)
        ) as transport:
            with pytest.raises(AuthenticationError):
                await transport.request(Request(method="GET", path=TEST_PATH))

    assert route.call_count == 1
    sleep_mock.assert_not_awaited()


@respx.mock
async def test_retry_after_header_controls_delay() -> None:
    respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json=[]),
        ]
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
        async with AsyncTransport(
            domain="example.test",
            retry_policy=RetryPolicy(max_attempts=RETRY_ONCE_ATTEMPTS),
        ) as transport:
            await transport.request(Request(method="GET", path=TEST_PATH))

    sleep_mock.assert_awaited_once_with(7.0)


@respx.mock
async def test_rate_limit_state_updates_from_headers() -> None:
    reset_at = int((dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)).timestamp())
    respx.get(TEST_URL).mock(
        return_value=httpx.Response(
            200,
            headers={
                "x-ratelimit-limit": str(RATE_LIMIT),
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": str(reset_at),
            },
        )
    )

    async with AsyncTransport(domain="example.test") as transport:
        await transport.request(Request(method="GET", path=TEST_PATH))

        assert transport.rate_limit_state.limit == RATE_LIMIT
        assert transport.rate_limit_state.remaining == 0
        assert transport.rate_limit_state.reset_at == dt.datetime.fromtimestamp(
            reset_at, tz=dt.UTC
        )
        assert transport.rate_limit_state.is_exhausted()
        assert transport.rate_limit_state.seconds_until_reset() > 0


@respx.mock
async def test_concurrency_limit_bounds_in_flight_requests() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)

        await asyncio.sleep(0.01)

        async with lock:
            active -= 1
        return httpx.Response(200, json={"ok": True})

    respx.get(TEST_URL).mock(side_effect=handler)

    async with AsyncTransport(
        domain="example.test", concurrency_limit=CONCURRENCY_LIMIT
    ) as transport:
        responses = await asyncio.gather(
            *(
                transport.request(Request(method="GET", path=TEST_PATH))
                for _ in range(10)
            )
        )

    assert all(response.status_code == HTTP_OK for response in responses)
    assert peak <= CONCURRENCY_LIMIT


@respx.mock
async def test_default_concurrency_limit_is_eight() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        async with lock:
            active += 1
            peak = max(peak, active)

        await asyncio.sleep(0.01)

        async with lock:
            active -= 1
        return httpx.Response(200, json={"ok": True})

    respx.get(TEST_URL).mock(side_effect=handler)

    async with AsyncTransport(domain="example.test") as transport:
        await asyncio.gather(
            *(
                transport.request(Request(method="GET", path=TEST_PATH))
                for _ in range(DEFAULT_CONCURRENCY_LIMIT + 1)
            )
        )

    assert peak <= DEFAULT_CONCURRENCY_LIMIT


@respx.mock
def test_sync_transport_request_and_thread_lifecycle() -> None:
    respx.get(TEST_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    with Transport(domain="example.test") as transport:
        response = transport.request(Request(method="GET", path=TEST_PATH))
        assert response.json() == {"ok": True}
        thread = cast("threading.Thread", vars(transport)["_thread"])
        assert isinstance(thread, threading.Thread)
        assert thread.is_alive()

    assert not thread.is_alive()


@respx.mock
def test_sync_transport_raises_on_404() -> None:
    respx.get(TEST_URL).mock(return_value=httpx.Response(404))

    with Transport(domain="example.test") as transport, pytest.raises(NotFoundError):
        transport.request(Request(method="GET", path=TEST_PATH))


def test_sync_transport_del_warns_when_unclosed() -> None:
    transport = Transport(domain="example.test")

    with pytest.warns(ResourceWarning, match="Unclosed nukapy Transport"):
        transport.__del__()


async def test_async_transport_del_warns_when_unclosed() -> None:
    transport = AsyncTransport(domain="example.test")

    with pytest.warns(ResourceWarning, match="Unclosed nukapy AsyncTransport"):
        transport.__del__()
    await transport.aclose()


def test_retry_policy_delay_within_bounds() -> None:
    policy = RetryPolicy(base_delay=2.0, max_delay=JITTER_MAX_DELAY, backoff_factor=3.0)

    for attempt in range(5):
        delay = policy.delay(attempt)
        assert 0.0 <= delay <= JITTER_MAX_DELAY


def test_retry_after_http_date_and_fallback() -> None:
    policy = RetryPolicy(max_delay=HEADER_MAX_DELAY)
    retry_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)
    headers: dict[str, str] = {
        "retry-after": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    }

    assert 0.0 <= retry_after_delay(headers, 0, policy) <= HEADER_MAX_DELAY
    assert 0.0 <= retry_after_delay({"retry-after": "not-a-date"}, 0, policy) <= 1.0
