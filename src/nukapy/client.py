"""Socrata clients."""

import dataclasses
import warnings
from collections.abc import Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, Literal, Self, cast

from nukapy._internal.auth import get_app_token
from nukapy.errors import BadRequestError, NotFoundError
from nukapy.soql import Query
from nukapy.transport import AsyncTransport, Request, Response, Transport

ApiVersion = Literal["auto", "v3", "v2.1"]


@dataclasses.dataclass(frozen=True)
class _ClientConfig:
    domain: str
    app_token: str | None
    api_key: str | None
    secret: str | None
    username: str | None
    password: str | None
    timeout: float
    max_retries: int
    user_agent: str
    base_headers: Mapping[str, str] | None
    concurrency_limit: int
    api_version: ApiVersion


class AsyncSocrata:
    """Async client for the Socrata Open Data API."""

    def __init__(  # noqa: PLR0913
        self,
        domain: str,
        app_token: str | None = None,
        *,
        api_key: str | None = None,
        secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: str = "nukapy",
        base_headers: Mapping[str, str] | None = None,
        concurrency_limit: int = 8,
        api_version: ApiVersion = "auto",
    ) -> None:
        """Create an async client for a Socrata domain."""
        self._closed = False
        self._config = _build_config(
            domain=domain,
            app_token=app_token,
            api_key=api_key,
            secret=secret,
            username=username,
            password=password,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
            base_headers=base_headers,
            concurrency_limit=concurrency_limit,
            api_version=api_version,
        )
        self.domain = self._config.domain
        self.app_token = self._config.app_token
        self.api_key = self._config.api_key
        self.secret = self._config.secret
        self._api_version_by_dataset: dict[str, ApiVersion] = {}
        self._transport = AsyncTransport(
            domain=self.domain,
            app_token=self.app_token,
            api_key=self.api_key,
            secret=self.secret,
            username=self._config.username,
            password=self._config.password,
            timeout=self._config.timeout,
            max_retries=self._config.max_retries,
            user_agent=self._config.user_agent,
            base_headers=self._config.base_headers,
            concurrency_limit=self._config.concurrency_limit,
        )

    async def get(
        self,
        dataset_id: str,
        *,
        limit: int | None = None,
        select: str | None = None,
        query: Query | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows from a Socrata dataset."""
        params = _row_params(limit=limit, select=select, query=query)
        response = await self._request_read(dataset_id, params)
        return _rows_from_response(response)

    async def aclose(self) -> None:
        """Close the underlying transport."""
        if self._closed:
            return
        self._closed = True
        await self._transport.aclose()

    async def __aenter__(self) -> Self:
        """Enter the async client context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the async client context."""
        await self.aclose()

    def __del__(self) -> None:
        """Warn if the async client is garbage-collected while open."""
        if not vars(self).get("_closed", True):
            warnings.warn(
                "Unclosed nukapy AsyncSocrata; use 'async with' or call aclose().",
                ResourceWarning,
                stacklevel=2,
            )

    async def _request_read(
        self, dataset_id: str, params: Mapping[str, str | int | float]
    ) -> Response:
        api_version = self._api_version_by_dataset.get(dataset_id, self._config.api_version)
        if api_version == "v2.1":
            return await self._request_v21(dataset_id, params)
        if api_version == "v3":
            return await self._request_v3(dataset_id, params)

        try:
            response = await self._request_v3(dataset_id, params)
        except (BadRequestError, NotFoundError):
            self._api_version_by_dataset[dataset_id] = "v2.1"
            return await self._request_v21(dataset_id, params)

        self._cache_version_from_headers(dataset_id, response.headers)
        return response

    async def _request_v3(
        self, dataset_id: str, params: Mapping[str, str | int | float]
    ) -> Response:
        return await self._transport.request(
            Request(method="GET", path=_v3_path(dataset_id), params=params)
        )

    async def _request_v21(
        self, dataset_id: str, params: Mapping[str, str | int | float]
    ) -> Response:
        return await self._transport.request(
            Request(method="GET", path=_v21_path(dataset_id), params=params)
        )

    def _cache_version_from_headers(self, dataset_id: str, headers: Mapping[str, str]) -> None:
        version = _api_version_from_headers(headers)
        if version is not None:
            self._api_version_by_dataset[dataset_id] = version


class Socrata:
    """Sync client for the Socrata Open Data API."""

    def __init__(  # noqa: PLR0913
        self,
        domain: str,
        app_token: str | None = None,
        *,
        api_key: str | None = None,
        secret: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: str = "nukapy",
        base_headers: Mapping[str, str] | None = None,
        concurrency_limit: int = 8,
        api_version: ApiVersion = "auto",
    ) -> None:
        """Create a sync client for a Socrata domain."""
        self._closed = False
        self._config = _build_config(
            domain=domain,
            app_token=app_token,
            api_key=api_key,
            secret=secret,
            username=username,
            password=password,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
            base_headers=base_headers,
            concurrency_limit=concurrency_limit,
            api_version=api_version,
        )
        self.domain = self._config.domain
        self.app_token = self._config.app_token
        self.api_key = self._config.api_key
        self.secret = self._config.secret
        self._api_version_by_dataset: dict[str, ApiVersion] = {}
        self._transport = Transport(
            domain=self.domain,
            app_token=self.app_token,
            api_key=self.api_key,
            secret=self.secret,
            username=self._config.username,
            password=self._config.password,
            timeout=self._config.timeout,
            max_retries=self._config.max_retries,
            user_agent=self._config.user_agent,
            base_headers=self._config.base_headers,
            concurrency_limit=self._config.concurrency_limit,
        )

    def get(
        self,
        dataset_id: str,
        *,
        limit: int | None = None,
        select: str | None = None,
        query: Query | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows from a Socrata dataset."""
        params = _row_params(limit=limit, select=select, query=query)
        response = self._request_read(dataset_id, params)
        return _rows_from_response(response)

    def close(self) -> None:
        """Close the underlying transport."""
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def __enter__(self) -> Self:
        """Enter the client context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the client context."""
        self.close()

    def __del__(self) -> None:
        """Warn and best-effort close abandoned sync clients."""
        if not vars(self).get("_closed", True):
            warnings.warn(
                "Unclosed nukapy Socrata; use 'with' or call close().",
                ResourceWarning,
                stacklevel=2,
            )
        with suppress(Exception):
            self.close()

    def _request_read(self, dataset_id: str, params: Mapping[str, str | int | float]) -> Response:
        api_version = self._api_version_by_dataset.get(dataset_id, self._config.api_version)
        if api_version == "v2.1":
            return self._request_v21(dataset_id, params)
        if api_version == "v3":
            return self._request_v3(dataset_id, params)

        try:
            response = self._request_v3(dataset_id, params)
        except (BadRequestError, NotFoundError):
            self._api_version_by_dataset[dataset_id] = "v2.1"
            return self._request_v21(dataset_id, params)

        self._cache_version_from_headers(dataset_id, response.headers)
        return response

    def _request_v3(self, dataset_id: str, params: Mapping[str, str | int | float]) -> Response:
        return self._transport.request(
            Request(method="GET", path=_v3_path(dataset_id), params=params)
        )

    def _request_v21(self, dataset_id: str, params: Mapping[str, str | int | float]) -> Response:
        return self._transport.request(
            Request(method="GET", path=_v21_path(dataset_id), params=params)
        )

    def _cache_version_from_headers(self, dataset_id: str, headers: Mapping[str, str]) -> None:
        version = _api_version_from_headers(headers)
        if version is not None:
            self._api_version_by_dataset[dataset_id] = version


def _build_config(  # noqa: PLR0913
    *,
    domain: str,
    app_token: str | None,
    api_key: str | None,
    secret: str | None,
    username: str | None,
    password: str | None,
    timeout: float,
    max_retries: int,
    user_agent: str,
    base_headers: Mapping[str, str] | None,
    concurrency_limit: int,
    api_version: ApiVersion,
) -> _ClientConfig:
    return _ClientConfig(
        domain=domain.removeprefix("https://").removeprefix("http://").rstrip("/"),
        app_token=get_app_token() if app_token is None else app_token or None,
        api_key=api_key,
        secret=secret,
        username=username,
        password=password,
        timeout=timeout,
        max_retries=max_retries,
        user_agent=user_agent,
        base_headers=base_headers,
        concurrency_limit=concurrency_limit,
        api_version=api_version,
    )


def _row_params(
    *, limit: int | None, select: str | None, query: Query | None
) -> dict[str, str | int | float]:
    if query is not None:
        if select is not None or limit is not None:
            msg = "query cannot be combined with select or limit"
            raise ValueError(msg)
        return query.to_params()

    params: dict[str, str | int | float] = {}
    if select is not None:
        params["$select"] = select
    if limit is not None:
        params["$limit"] = limit
    return params


def _rows_from_response(response: Response) -> list[dict[str, Any]]:
    data = response.json()
    if isinstance(data, dict):
        data_mapping = cast("Mapping[str, object]", data)
        rows = data_mapping.get("data")
        if isinstance(rows, list):
            return cast("list[dict[str, Any]]", rows)
    return cast("list[dict[str, Any]]", data)


def _api_version_from_headers(headers: Mapping[str, str]) -> ApiVersion | None:
    version = headers.get("x-socrata-api-version", "").lower()
    if version.startswith("3") or "v3" in version:
        return "v3"
    if version.startswith("2") or "v2" in version or "x-soda2-fields" in headers:
        return "v2.1"
    return None


def _v3_path(dataset_id: str) -> str:
    return f"/api/v3/views/{dataset_id}/query.json"


def _v21_path(dataset_id: str) -> str:
    return f"/resource/{dataset_id}.json"


__all__ = ["AsyncSocrata", "Socrata"]
