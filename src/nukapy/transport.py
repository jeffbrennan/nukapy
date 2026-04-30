"""HTTP transport interfaces."""

import asyncio
import dataclasses
import json
import threading
from collections.abc import Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, Self

import httpx

from nukapy._internal.rate_limit import RateLimitState
from nukapy._internal.retry import RetryPolicy, retry_after_delay
from nukapy.errors import (
    AuthenticationError,
    BadGatewayError,
    BadRequestError,
    ClientError,
    ConnectError,
    ForbiddenError,
    GatewayTimeoutError,
    HTTPError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)
from nukapy.errors import (
    TimeoutError as NukapyTimeoutError,
)

HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_INTERNAL_SERVER_ERROR = 500


@dataclasses.dataclass(frozen=True)
class Request:
    """Transport request data."""

    method: str
    url: str
    params: Mapping[str, str | int | float] | None = None
    headers: Mapping[str, str] | None = None
    body: bytes | None = None
    timeout: float | None = None


@dataclasses.dataclass(frozen=True)
class Response:
    """Transport response data."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes

    def json(self) -> Any:  # noqa: ANN401
        """Decode response content as JSON."""
        return json.loads(self.content)

    def text(self, encoding: str = "utf-8") -> str:
        """Decode response content as text."""
        return self.content.decode(encoding)


class AsyncTransport:
    """Async HTTP transport with pooling, retries, and error mapping."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        app_token: str | None = None,
        timeout: float = 30.0,
        max_connections: int = 10,
        max_retries: int = 3,
        concurrency_limit: int = 10,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Create an async transport."""
        self._app_token = app_token
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=max_connections),
            timeout=httpx.Timeout(timeout),
        )
        self._sem = asyncio.Semaphore(concurrency_limit)
        self._retry_policy = retry_policy or RetryPolicy(max_attempts=max_retries)
        self._rate_state = RateLimitState()

    @property
    def rate_limit_state(self) -> RateLimitState:
        """Return the current rate-limit state."""
        return self._rate_state

    async def request(self, req: Request) -> Response:
        """Send a request with bounded concurrency and retry handling."""
        async with self._sem:
            for attempt in range(self._retry_policy.max_attempts):
                try:
                    return await self._send_once(req)
                except _RETRYABLE_ERRORS as exc:
                    if attempt >= self._retry_policy.max_attempts - 1:
                        raise
                    headers = exc.response_headers if isinstance(exc, HTTPError) else {}
                    delay = retry_after_delay(headers, attempt, self._retry_policy)
                    await asyncio.sleep(delay)

        msg = "Retry policy must allow at least one attempt"
        raise RuntimeError(msg)

    async def _send_once(self, req: Request) -> Response:
        headers = dict(req.headers or {})
        if self._app_token:
            headers["X-App-Token"] = self._app_token

        try:
            raw = await self._client.request(
                req.method,
                req.url,
                params=req.params,
                headers=headers,
                content=req.body,
                timeout=req.timeout,
            )
        except httpx.TimeoutException as exc:
            msg = f"Request timed out for {req.url}"
            raise NukapyTimeoutError(msg, request_url=req.url) from exc
        except httpx.ConnectError as exc:
            msg = f"Connection failed for {req.url}"
            raise ConnectError(msg, request_url=req.url) from exc
        except httpx.NetworkError as exc:
            msg = f"Network error for {req.url}"
            raise NetworkError(msg, request_url=req.url) from exc

        headers = dict(raw.headers)
        self._rate_state.update(headers)
        response = Response(
            status_code=raw.status_code,
            headers=headers,
            content=raw.content,
        )
        _raise_for_status(response, req.url)
        return response

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        """Enter the async transport context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the async transport context."""
        await self.aclose()


class Transport:
    """Sync facade over the async HTTP transport."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        """Create a sync transport backed by a background event loop."""
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="nukapy-transport",
        )
        self._thread.start()
        future = asyncio.run_coroutine_threadsafe(
            _create_async_transport(**kwargs), self._loop
        )
        self._async = future.result(timeout=5.0)

    def request(self, req: Request) -> Response:
        """Send a request synchronously."""
        return asyncio.run_coroutine_threadsafe(
            self._async.request(req), self._loop
        ).result()

    def close(self) -> None:
        """Close the transport and stop the background event loop."""
        if self._closed:
            return
        self._closed = True
        asyncio.run_coroutine_threadsafe(self._async.aclose(), self._loop).result()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
        self._loop.close()

    def __enter__(self) -> Self:
        """Enter the sync transport context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the sync transport context."""
        self.close()

    def __del__(self) -> None:
        """Best-effort cleanup for abandoned transports."""
        with suppress(Exception):
            self.close()


async def _create_async_transport(**kwargs: Any) -> AsyncTransport:  # noqa: ANN401
    return AsyncTransport(**kwargs)


def _raise_for_status(resp: Response, url: str) -> None:
    if resp.status_code < HTTP_STATUS_BAD_REQUEST:
        return

    error_type = _ERROR_TYPES.get(resp.status_code)
    if error_type is None:
        error_type = (
            ClientError
            if resp.status_code < HTTP_STATUS_INTERNAL_SERVER_ERROR
            else ServerError
        )

    msg = f"HTTP {resp.status_code} for {url}"
    raise error_type(
        msg,
        status_code=resp.status_code,
        request_url=url,
        response_body=resp.text(),
        response_headers=resp.headers,
    )


_ERROR_TYPES: Mapping[int, type[HTTPError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    429: RateLimitError,
    502: BadGatewayError,
    503: ServiceUnavailableError,
    504: GatewayTimeoutError,
}

_RETRYABLE_ERRORS = (
    RateLimitError,
    BadGatewayError,
    ServiceUnavailableError,
    GatewayTimeoutError,
    NukapyTimeoutError,
)

__all__ = ["AsyncTransport", "Request", "Response", "Transport"]
