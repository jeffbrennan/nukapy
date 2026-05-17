"""Unit tests for dataset pagination and iteration."""

from typing import Any, cast

import httpx
import pyarrow as pa
import pytest
import respx

from nukapy import AsyncSocrata, NukapyResult, Socrata
from nukapy.pagination import (
    PaginationConfig,
    Paginator,
    _and_where,
    _int_state,
    _updated_at_where,
    _with_system_select,
)
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
async def test_async_stream_does_not_prefetch() -> None:
    route = respx.get(TEST_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [{":id": 1, "name": "one"}]}),
        ]
    )

    async with AsyncSocrata("data.cityofnewyork.us", app_token="test-token") as client:
        stream = client.dataset("erm2-nwe9").stream(batch_size=BATCH_SIZE)
        assert route.call_count == 0

        batch = await anext(stream)

    assert isinstance(batch, pa.RecordBatch)
    assert route.call_count == 1


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
    assert route.call_count == 2
    first_call = cast("Any", respx.calls[0])
    second_call = cast("Any", respx.calls[1])
    first_request = cast("httpx.Request", first_call.request)
    second_request = cast("httpx.Request", second_call.request)
    assert first_request.url.params["$where"] == ":id > 0"
    assert second_request.url.params["$where"] == ":id > 2"
    assert iterator.checkpoint == {"id": 3}


def test_batch_size_zero_raises() -> None:
    with pytest.raises(ValueError, match="batch_size must be greater than zero"):
        PaginationConfig(batch_size=0)


def test_batch_size_negative_raises() -> None:
    with pytest.raises(ValueError, match="batch_size must be greater than zero"):
        PaginationConfig(batch_size=-1)


def test_base_params_includes_query_params() -> None:
    query = Query().where(col("status") == "Open")
    paginator = Paginator(PaginationConfig(batch_size=5, strategy="id", query=query))

    request = paginator.next_request()

    assert "$where" in request.params
    assert "Open" in str(request.params["$where"])


def test_advance_updated_at_missing_field_raises() -> None:
    paginator = Paginator(PaginationConfig(batch_size=2, strategy="updated_at"))
    with pytest.raises(ValueError, match="updated_at pagination requires"):
        paginator.advance([{":updated_at": 12345, ":id": 1}])


def test_advance_id_non_int_raises() -> None:
    paginator = Paginator(PaginationConfig(batch_size=2, strategy="id"))
    with pytest.raises(ValueError, match="id pagination requires"):
        paginator.advance([{":id": "not-an-integer"}])


def test_and_where_with_existing() -> None:
    result = _and_where("existing_clause", "cursor_clause")
    assert result == "(existing_clause) AND (cursor_clause)"


def test_and_where_without_existing() -> None:
    result = _and_where(None, "cursor_clause")
    assert result == "cursor_clause"


def test_with_system_select_appends_to_existing() -> None:
    result = _with_system_select("`name`, `amount`", (":id",))
    assert result == ":id, `name`, `amount`"


def test_with_system_select_without_existing() -> None:
    result = _with_system_select(None, (":id",))
    assert result == ":id, *"


def test_updated_at_where_empty_returns_is_not_null() -> None:
    result = _updated_at_where("", 0)
    assert result == ":updated_at IS NOT NULL"


def test_int_state_non_decimal_string_returns_default() -> None:
    result = _int_state({"key": "not-a-number"}, "key", 42)
    assert result == 42


def test_int_state_decimal_string_returns_int() -> None:
    result = _int_state({"key": "99"}, "key", 0)
    assert result == 99
