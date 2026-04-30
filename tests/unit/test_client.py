"""Unit tests for the Socrata client."""

import httpx
import pytest
import respx

from nukapy import Socrata

ROW_LIMIT = 5


@pytest.mark.vcr
def test_get_replays_nyc_311_rows() -> None:
    rows = Socrata("data.cityofnewyork.us").get("erm2-nwe9", limit=ROW_LIMIT)

    assert len(rows) == ROW_LIMIT
    assert all(isinstance(row, dict) for row in rows)


@respx.mock
def test_get_returns_rows() -> None:
    mock_rows = [{"unique_key": "42", "complaint_type": "Noise"}]
    respx.get("https://data.cityofnewyork.us/resource/erm2-nwe9.json").mock(
        return_value=httpx.Response(200, json=mock_rows)
    )
    client = Socrata("data.cityofnewyork.us", app_token="test-token")
    rows = client.get("erm2-nwe9", limit=1)
    assert rows == mock_rows


@respx.mock
def test_get_sends_app_token_header() -> None:
    respx.get("https://data.cityofnewyork.us/resource/erm2-nwe9.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = Socrata("data.cityofnewyork.us", app_token="abc123")
    client.get("erm2-nwe9")
    assert respx.calls.last.request.headers["X-App-Token"] == "abc123"


@respx.mock
def test_get_omits_header_when_no_token() -> None:
    respx.get("https://data.cityofnewyork.us/resource/erm2-nwe9.json").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = Socrata("data.cityofnewyork.us", app_token="")
    client.get("erm2-nwe9")
    assert "X-App-Token" not in respx.calls.last.request.headers
