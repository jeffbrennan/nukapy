"""Socrata clients."""

import dataclasses
import warnings
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import suppress
from types import TracebackType
from typing import Any, Literal, Self, cast

import pyarrow as pa

from nukapy._internal.auth import get_app_token
from nukapy.errors import BadRequestError, NotFoundError
from nukapy.pagination import DEFAULT_BATCH_SIZE, PaginationConfig, PaginationStrategy, Paginator
from nukapy.results import NukapyResult
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
        response = await self.request_read(dataset_id, params)
        return _rows_from_response(response)

    def dataset(self, dataset_id: str) -> "AsyncDataset":
        """Return an async handle for iterating over a Socrata dataset."""
        return AsyncDataset(self, dataset_id)

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

    async def request_read(
        self, dataset_id: str, params: Mapping[str, str | int | float]
    ) -> Response:
        """Request rows from a dataset and return the raw transport response."""
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
        response = self.request_read(dataset_id, params)
        return _rows_from_response(response)

    def dataset(self, dataset_id: str) -> "Dataset":
        """Return a sync handle for iterating over a Socrata dataset."""
        return Dataset(self, dataset_id)

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

    def request_read(self, dataset_id: str, params: Mapping[str, str | int | float]) -> Response:
        """Request rows from a dataset and return the raw transport response."""
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


@dataclasses.dataclass(frozen=True)
class AsyncDataset:
    """Async dataset handle."""

    _client: AsyncSocrata
    dataset_id: str

    def stream(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        strategy: PaginationStrategy = "id",
        query: Query | None = None,
        state: Mapping[str, object] | None = None,
    ) -> "AsyncBatchStream":
        """Stream Arrow record batches without buffering ahead."""
        return AsyncBatchStream(
            self._client,
            self.dataset_id,
            PaginationConfig(
                batch_size=batch_size,
                strategy=strategy,
                query=query,
                state=state,
            ),
        )

    async def fetch(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        strategy: PaginationStrategy = "id",
        query: Query | None = None,
        state: Mapping[str, object] | None = None,
    ) -> NukapyResult:
        """Eagerly fetch all streamed batches into memory."""
        stream = self.stream(
            batch_size=batch_size,
            strategy=strategy,
            query=query,
            state=state,
        )
        batches = [batch async for batch in stream]
        return NukapyResult(batches=tuple(batches), checkpoint=stream.checkpoint)


class AsyncBatchStream(AsyncIterator[pa.RecordBatch]):
    """Async iterator over Arrow record batches."""

    def __init__(
        self,
        client: AsyncSocrata,
        dataset_id: str,
        config: PaginationConfig,
    ) -> None:
        """Create an async batch stream."""
        self._client = client
        self._dataset_id = dataset_id
        self._config = config
        self._paginator = Paginator(config)
        self._done = False

    @property
    def checkpoint(self) -> dict[str, object]:
        """Return the latest pagination checkpoint."""
        return self._paginator.checkpoint

    def __aiter__(self) -> Self:
        """Return this stream as its async iterator."""
        return self

    async def __anext__(self) -> pa.RecordBatch:
        """Fetch and return the next Arrow record batch."""
        if self._done:
            raise StopAsyncIteration

        request = self._paginator.next_request()
        response = await self._client.request_read(self._dataset_id, request.params)
        rows = _rows_from_response(response)
        if not rows:
            self._done = True
            raise StopAsyncIteration

        self._paginator.advance(rows)
        if len(rows) < self._config.batch_size:
            self._done = True
        return _record_batch_from_rows(rows)


@dataclasses.dataclass(frozen=True)
class Dataset:
    """Sync dataset handle."""

    _client: Socrata
    dataset_id: str

    def iter_batches(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        strategy: PaginationStrategy = "id",
        query: Query | None = None,
        state: Mapping[str, object] | None = None,
    ) -> "BatchIterator":
        """Iterate Arrow record batches without buffering ahead."""
        return BatchIterator(
            self._client,
            self.dataset_id,
            PaginationConfig(
                batch_size=batch_size,
                strategy=strategy,
                query=query,
                state=state,
            ),
        )

    def fetch(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        strategy: PaginationStrategy = "id",
        query: Query | None = None,
        state: Mapping[str, object] | None = None,
    ) -> NukapyResult:
        """Eagerly fetch all streamed batches into memory."""
        iterator = self.iter_batches(
            batch_size=batch_size,
            strategy=strategy,
            query=query,
            state=state,
        )
        batches = tuple(iterator)
        return NukapyResult(batches=batches, checkpoint=iterator.checkpoint)


class BatchIterator(Iterator[pa.RecordBatch]):
    """Sync iterator over Arrow record batches."""

    def __init__(
        self,
        client: Socrata,
        dataset_id: str,
        config: PaginationConfig,
    ) -> None:
        """Create a sync batch iterator."""
        self._client = client
        self._dataset_id = dataset_id
        self._config = config
        self._paginator = Paginator(config)
        self._done = False

    @property
    def checkpoint(self) -> dict[str, object]:
        """Return the latest pagination checkpoint."""
        return self._paginator.checkpoint

    def __iter__(self) -> Self:
        """Return this stream as its iterator."""
        return self

    def __next__(self) -> pa.RecordBatch:
        """Fetch and return the next Arrow record batch."""
        if self._done:
            raise StopIteration

        request = self._paginator.next_request()
        response = self._client.request_read(self._dataset_id, request.params)
        rows = _rows_from_response(response)
        if not rows:
            self._done = True
            raise StopIteration

        self._paginator.advance(rows)
        if len(rows) < self._config.batch_size:
            self._done = True
        return _record_batch_from_rows(rows)


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


def _record_batch_from_rows(rows: list[dict[str, Any]]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist(rows)


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


__all__ = [
    "AsyncBatchStream",
    "AsyncDataset",
    "AsyncSocrata",
    "BatchIterator",
    "Dataset",
    "Socrata",
]
