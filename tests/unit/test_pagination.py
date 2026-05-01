"""Unit tests for dataset pagination and iteration."""

from typing import Any, cast

import httpx
import pyarrow as pa
import pytest
import respx

from nukapy import AsyncSocrata, NukapyResult, Socrata
from nukapy.pagination import PaginationConfig, Paginator
from nukapy.soql import Query, col

TEST_URL = "https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json"
BATCH_SIZE = 2


def test_default_id_paginator_params() -> None:
    paginator = Paginator(PaginationConfig(batch_size=BATCH_SIZE))

    request = paginator.next_request()

    assert request.params == {
        "$limit": BATCH_SIZE,
        "$select": ":id, *",
        "$where": ":id > 0",
        "$order": ":id",
    }


def test_offset_paginator_params_and_checkpoint() -> None:
    paginator = Paginator(
        PaginationConfig(batch_size=BATCH_SIZE, strategy="offset", state={"offset": 4})
    )

    request = paginator.next_request()
    paginator.advance([{"name": "one"}, {"name": "two"}])

    assert request.params == {"$limit": 2, "$offset": 4}
    assert paginator.checkpoint == {"offset": 6}


def test_updated_at_paginator_params_and_checkpoint() -> None:
    paginator = Paginator(
        PaginationConfig(
            batch_size=BATCH_SIZE,
            strategy="updated_at",
            state={"updated_at": "2024-01-01T00:00:00", "id": 5},
        )
    )

    request = paginator.next_request()
    paginator.advance([{":updated_at": "2024-01-02T00:00:00", ":id": "7"}])

    assert request.params["$select"] == ":updated_at, :id, *"
    assert request.params["$order"] == ":updated_at, :id"
    assert request.params["$where"] == (
        "(:updated_at > '2024-01-01T00:00:00') OR (:updated_at = '2024-01-01T00:00:00' AND :id > 5)"
    )
    assert paginator.checkpoint == {"updated_at": "2024-01-02T00:00:00", "id": 7}


def test_streaming_query_rejects_limit_offset_and_order() -> None:
    invalid_queries = [
        Query().limit(1),
        Query().offset(1),
        Query().order_by(col("name")),
    ]

    for query in invalid_queries:
        with pytest.raises(ValueError, match="streaming queries cannot include"):
            PaginationConfig(query=query)


@respx.mock
def test_sync_iter_batches_yields_arrow_batches_and_does_not_prefetch() -> None:
    route = respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [{":id": 1, "name": "one"}]}),
        ]
    )

    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        iterator = client.dataset("erm2-nwe9").iter_batches(batch_size=BATCH_SIZE)
        assert route.call_count == 0

        batch = next(iterator)

    assert isinstance(batch, pa.RecordBatch)
    assert batch.num_rows == 1
    assert iterator.checkpoint == {"id": 1}
    assert route.call_count == 1
    params = respx.calls.last.request.url.params
    assert params["$select"] == ":id, *"
    assert params["$where"] == ":id > 0"
    assert params["$order"] == ":id"
    assert params["$limit"] == str(BATCH_SIZE)


@respx.mock
async def test_async_stream_yields_arrow_batches() -> None:
    respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [{":id": 1, "name": "one"}]}),
        ]
    )

    async with AsyncSocrata("data.cityofnewyork.us", app_token="test-token") as client:
        stream = client.dataset("erm2-nwe9").stream(batch_size=BATCH_SIZE)
        batch = await anext(stream)

    assert isinstance(batch, pa.RecordBatch)
    assert batch.num_rows == 1
    assert stream.checkpoint == {"id": 1}


@respx.mock
def test_fetch_materializes_batches() -> None:
    respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [{":id": 1, "name": "one"}]}),
        ]
    )

    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        result = client.dataset("erm2-nwe9").fetch(batch_size=BATCH_SIZE)

    assert isinstance(result, NukapyResult)
    assert result.num_rows == 1
    assert result.checkpoint == {"id": 1}
    assert result.to_table().num_rows == 1


@respx.mock
def test_fetch_empty_result_converts_to_empty_table() -> None:
    respx.get(TEST_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        result = client.dataset("erm2-nwe9").fetch(batch_size=BATCH_SIZE)

    assert result.num_rows == 0
    assert result.to_table().num_rows == 0


@respx.mock
def test_iterator_uses_next_id_checkpoint() -> None:
    route = respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [{":id": 1}, {":id": 2}]}),
            httpx.Response(200, json={"data": [{":id": 3}]}),
        ]
    )

    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        iterator = client.dataset("erm2-nwe9").iter_batches(batch_size=BATCH_SIZE)
        first = next(iterator)
        second = next(iterator)

    assert first.num_rows == BATCH_SIZE
    assert second.num_rows == 1
    assert route.call_count == BATCH_SIZE
    first_call = cast("Any", respx.calls[0])
    second_call = cast("Any", respx.calls[1])
    first_request = cast("httpx.Request", first_call.request)
    second_request = cast("httpx.Request", second_call.request)
    assert first_request.url.params["$where"] == ":id > 0"
    assert second_request.url.params["$where"] == ":id > 2"
    assert iterator.checkpoint == {"id": 3}
