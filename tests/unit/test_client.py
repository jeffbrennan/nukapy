"""Unit tests for the Socrata client."""

import httpx
import pytest
import respx

from nukapy import AsyncSocrata, Socrata

ROW_LIMIT = 5


@pytest.mark.vcr
def test_get_replays_nyc_311_rows() -> None:
    with Socrata("data.cityofnewyork.us", api_version="v2.1") as client:
        rows = client.get("erm2-nwe9", limit=ROW_LIMIT)

    assert len(rows) == ROW_LIMIT
    assert all(isinstance(row, dict) for row in rows)


@respx.mock
def test_get_returns_rows() -> None:
    mock_rows = [{"unique_key": "42", "complaint_type": "Noise"}]
    respx.get("https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json").mock(
        return_value=httpx.Response(200, json={"data": mock_rows})
    )
    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        rows = client.get("erm2-nwe9", limit=1)

    assert rows == mock_rows


@respx.mock
async def test_async_get_returns_rows() -> None:
    mock_rows = [{"unique_key": "42", "complaint_type": "Noise"}]
    respx.get("https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json").mock(
        return_value=httpx.Response(200, json={"data": mock_rows})
    )

    async with AsyncSocrata("data.cityofnewyork.us", app_token="test-token") as client:
        rows = await client.get("erm2-nwe9", limit=1)

    assert rows == mock_rows


@respx.mock
def test_get_falls_back_to_v21_when_v3_is_unavailable() -> None:
    mock_rows = [{"unique_key": "42", "complaint_type": "Noise"}]
    v3_route = respx.get("https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json").mock(
        return_value=httpx.Response(404)
    )
    v21_route = respx.get("https://data.cityofnewyork.us/resource/erm2-nwe9.json").mock(
        return_value=httpx.Response(200, json=mock_rows)
    )

    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        rows = client.get("erm2-nwe9", limit=1)

    assert rows == mock_rows
    assert v3_route.called
    assert v21_route.called


@respx.mock
def test_get_accepts_select_param() -> None:
    respx.get("https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    with Socrata("data.cityofnewyork.us", app_token="test-token") as client:
        client.get("erm2-nwe9", limit=1, select="unique_key,complaint_type")

    assert respx.calls.last.request.url.params["$select"] == "unique_key,complaint_type"


@respx.mock
def test_get_sends_app_token_header() -> None:
    respx.get("https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    with Socrata("data.cityofnewyork.us", app_token="abc123") as client:
        client.get("erm2-nwe9")

    assert respx.calls.last.request.headers["X-App-Token"] == "abc123"


@respx.mock
def test_get_omits_header_when_no_token() -> None:
    respx.get("https://data.cityofnewyork.us/api/v3/views/erm2-nwe9/query.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    with Socrata("data.cityofnewyork.us", app_token="") as client:
        client.get("erm2-nwe9")

    assert "X-App-Token" not in respx.calls.last.request.headers


def test_sync_client_del_warns_when_unclosed() -> None:
    client = Socrata("data.cityofnewyork.us", app_token="")

    with pytest.warns(ResourceWarning, match="Unclosed nukapy Socrata"):
        client.__del__()


async def test_async_client_del_warns_when_unclosed() -> None:
    client = AsyncSocrata("data.cityofnewyork.us", app_token="")

    with pytest.warns(ResourceWarning, match="Unclosed nukapy AsyncSocrata"):
        client.__del__()
    await client.aclose()
