"""HTTP transport interfaces."""

import asyncio
import dataclasses
import json
import threading
import warnings
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
from nukapy.errors import TimeoutError as NukapyTimeoutError

HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_INTERNAL_SERVER_ERROR = 500
DEFAULT_CONCURRENCY_LIMIT = 8
DEFAULT_USER_AGENT = "nukapy"

_JSON_UNSET = object()


@dataclasses.dataclass(frozen=True)
class Request:
    """Transport request data."""

    method: str
    path: str
    params: Mapping[str, str | int | float] | None = None
    body: bytes | None = None
    headers: Mapping[str, str] | None = None
    idempotent: bool = True
    timeout: float | None = None


@dataclasses.dataclass(frozen=True)
class Response:
    """Transport response data."""

    status: int
    headers: Mapping[str, str]
    content: bytes
    _json: object = dataclasses.field(
        default=_JSON_UNSET, init=False, repr=False, compare=False
    )

    @property
    def status_code(self) -> int:
        """Return the HTTP status code."""
        return self.status

    def json(self) -> Any:  # noqa: ANN401
        """Decode response content as JSON once and cache the parsed value."""
        if self._json is _JSON_UNSET:
            object.__setattr__(self, "_json", json.loads(self.content))
        return self._json

    def text(self, encoding: str = "utf-8") -> str:
        """Decode response content as text."""
        return self.content.decode(encoding)


class AsyncTransport:
    """Async HTTP transport with pooling, retries, and error mapping."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        domain: str,
        app_token: str | None = None,
        api_key: str | None = None,
        secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        max_connections: int = 10,
        max_retries: int = 3,
        concurrency_limit: int = DEFAULT_CONCURRENCY_LIMIT,
        retry_policy: RetryPolicy | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        base_headers: Mapping[str, str] | None = None,
    ) -> None:
        """Create an async transport."""
        self._closed = False
        self._domain = _normalize_domain(domain)
        self._app_token = app_token
        self._api_key = api_key
        self._secret = secret
        self._base_headers = dict(base_headers or {})
        self._user_agent = user_agent
        self._auth = _build_auth(
            username=username,
            password=password,
            api_key=api_key,
            secret=secret,
        )
        self._client = httpx.AsyncClient(
            base_url=f"https://{self._domain}",
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
                    final_attempt = attempt >= self._retry_policy.max_attempts - 1
                    if not req.idempotent or final_attempt:
                        raise
                    headers = exc.response_headers if isinstance(exc, HTTPError) else {}
                    delay = retry_after_delay(headers, attempt, self._retry_policy)
                    await asyncio.sleep(delay)

        msg = "Retry policy must allow at least one attempt"
        raise RuntimeError(msg)

    async def _send_once(self, req: Request) -> Response:
        headers = self._request_headers(req.headers)
        url = self._request_url(req.path)

        try:
            if req.timeout is None:
                raw = await self._client.request(
                    req.method,
                    req.path,
                    params=req.params,
                    headers=headers,
                    content=req.body,
                    auth=self._auth,
                )
            else:
                raw = await self._client.request(
                    req.method,
                    req.path,
                    params=req.params,
                    headers=headers,
                    content=req.body,
                    timeout=req.timeout,
                    auth=self._auth,
                )
        except httpx.TimeoutException as exc:
            msg = f"Request timed out for {url}"
            raise NukapyTimeoutError(msg, request_url=url) from exc
        except httpx.ConnectError as exc:
            msg = f"Connection failed for {url}"
            raise ConnectError(msg, request_url=url) from exc
        except httpx.NetworkError as exc:
            msg = f"Network error for {url}"
            raise NetworkError(msg, request_url=url) from exc

        response_headers = dict(raw.headers)
        self._rate_state.update(response_headers)
        response = Response(
            status=raw.status_code,
            headers=response_headers,
            content=raw.content,
        )
        _raise_for_status(response, str(raw.request.url))
        return response

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._closed:
            return
        self._closed = True
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

    def __del__(self) -> None:
        """Warn if the async transport is garbage-collected while open."""
        if not vars(self).get("_closed", True):
            warnings.warn(
                "Unclosed nukapy AsyncTransport; use 'async with' or call aclose().",
                ResourceWarning,
                stacklevel=2,
            )

    def _request_headers(
        self, request_headers: Mapping[str, str] | None
    ) -> dict[str, str]:
        headers = dict(self._base_headers)
        headers.setdefault("User-Agent", self._user_agent)
        headers.update(request_headers or {})
        if self._app_token:
            headers["X-App-Token"] = self._app_token
        return headers

    def _request_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"https://{self._domain}/{path.lstrip('/')}"


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
        """Warn and best-effort close abandoned sync transports."""
        if not vars(self).get("_closed", True):
            warnings.warn(
                "Unclosed nukapy Transport; use 'with' or call close().",
                ResourceWarning,
                stacklevel=2,
            )
        with suppress(Exception):
            self.close()


async def _create_async_transport(**kwargs: Any) -> AsyncTransport:  # noqa: ANN401
    return AsyncTransport(**kwargs)


def _build_auth(
    *,
    username: str | None,
    password: str | None,
    api_key: str | None,
    secret: str | None,
) -> httpx.Auth | None:
    if (username is None) != (password is None):
        msg = "username and password must be provided together"
        raise ValueError(msg)
    if (api_key is None) != (secret is None):
        msg = "api_key and secret must be provided together"
        raise ValueError(msg)

    if username is not None and password is not None:
        return httpx.BasicAuth(username, password)
    if api_key is not None and secret is not None:
        return httpx.BasicAuth(api_key, secret)
    return None


def _normalize_domain(domain: str) -> str:
    return domain.removeprefix("https://").removeprefix("http://").rstrip("/")


def _raise_for_status(resp: Response, url: str) -> None:
    if resp.status < HTTP_STATUS_BAD_REQUEST:
        return

    error_type = _ERROR_TYPES.get(resp.status)
    if error_type is None:
        error_type = (
            ClientError
            if resp.status < HTTP_STATUS_INTERNAL_SERVER_ERROR
            else ServerError
        )

    msg = f"HTTP {resp.status} for {url}"
    raise error_type(
        msg,
        status_code=resp.status,
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
