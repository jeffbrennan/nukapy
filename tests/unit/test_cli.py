"""Unit tests for the nukapy CLI."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pyarrow.ipc as pa_ipc
import pyarrow.parquet as pq
import respx
from typer.testing import CliRunner

from nukapy._version import __version__
from nukapy.cli import app

runner = CliRunner()

_DOMAIN = "data.cityofnewyork.us"
_DATASET_ID = "erm2-nwe9"
_META_URL = f"https://{_DOMAIN}/api/views/{_DATASET_ID}.json"
_V3_URL = f"https://{_DOMAIN}/api/v3/views/{_DATASET_ID}/query.json"

_MOCK_ROWS = [
    {"unique_key": "1", "complaint_type": "Noise"},
    {"unique_key": "2", "complaint_type": "Heat"},
]

# Stream tests use id-cursor pagination, which requires :id in each row.
_STREAM_ROWS = [
    {"unique_key": "1", "complaint_type": "Noise", ":id": 1},
    {"unique_key": "2", "complaint_type": "Heat", ":id": 2},
]


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


def test_version_prints_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


# ---------------------------------------------------------------------------
# datasets search
# ---------------------------------------------------------------------------


def test_datasets_search_prints_results() -> None:
    discovery_payload = {
        "results": [
            {
                "resource": {
                    "id": _DATASET_ID,
                    "name": "311 Service Requests",
                    "updatedAt": "2024-01-15T00:00:00.000Z",
                }
            }
        ]
    }

    with patch("nukapy.cli.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: discovery_payload,
            raise_for_status=lambda: None,
        )
        result = runner.invoke(app, ["datasets", "search", _DOMAIN, "311"])

    assert result.exit_code == 0
    assert _DATASET_ID in result.stdout
    assert "311 Service Requests" in result.stdout
    assert "2024-01-15" in result.stdout


def test_datasets_search_no_results_exits_cleanly() -> None:
    with patch("nukapy.cli.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": []},
            raise_for_status=lambda: None,
        )
        result = runner.invoke(app, ["datasets", "search", _DOMAIN])

    assert result.exit_code == 0
    assert "No datasets found" in result.stdout


def test_datasets_search_passes_query_and_limit() -> None:
    with patch("nukapy.cli.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"results": []},
            raise_for_status=lambda: None,
        )
        runner.invoke(app, ["datasets", "search", _DOMAIN, "crime", "--limit", "5"])
        call_kwargs = mock_get.call_args
    params = call_kwargs.kwargs.get(
        "params",
        call_kwargs.args[1] if len(call_kwargs.args) > 1 else {},
    )
    assert params.get("q") == "crime"
    assert params.get("limit") == 5


def test_datasets_search_handles_http_error() -> None:
    req = MagicMock()
    resp = MagicMock()
    with patch("nukapy.cli.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(
            raise_for_status=MagicMock(
                side_effect=httpx.HTTPStatusError("error", request=req, response=resp)
            )
        )
        result = runner.invoke(app, ["datasets", "search", _DOMAIN])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# datasets info
# ---------------------------------------------------------------------------


@respx.mock
def test_datasets_info_prints_metadata() -> None:
    respx.get(_META_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": _DATASET_ID,
                "name": "311 Service Requests",
                "description": "NYC 311 complaints",
                "category": "Public Safety",
                "tags": ["311", "nyc"],
                "columns": [
                    {"fieldName": "unique_key", "name": "Unique Key", "dataTypeName": "text"},
                    {
                        "fieldName": "complaint_type",
                        "name": "Complaint Type",
                        "dataTypeName": "text",
                    },
                ],
            },
        )
    )

    result = runner.invoke(app, ["datasets", "info", _DOMAIN, _DATASET_ID])

    assert result.exit_code == 0
    assert "311 Service Requests" in result.stdout
    assert "unique_key" in result.stdout
    assert "complaint_type" in result.stdout
    assert "Public Safety" in result.stdout
    assert "311, nyc" in result.stdout


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


@respx.mock
def test_fetch_writes_ndjson_to_stdout() -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _MOCK_ROWS})
    )

    result = runner.invoke(app, ["fetch", _DOMAIN, _DATASET_ID])

    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.strip().splitlines() if ln]
    assert len(lines) == 2
    parsed = [json.loads(ln) for ln in lines]
    assert parsed[0]["unique_key"] == "1"
    assert parsed[1]["complaint_type"] == "Heat"


@respx.mock
def test_fetch_writes_json_to_stdout() -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _MOCK_ROWS})
    )

    result = runner.invoke(app, ["fetch", _DOMAIN, _DATASET_ID, "--format", "json"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout.strip())
    assert isinstance(parsed, list)
    assert len(parsed) == 2


@respx.mock
def test_fetch_writes_csv_to_stdout() -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _MOCK_ROWS})
    )

    result = runner.invoke(app, ["fetch", _DOMAIN, _DATASET_ID, "--format", "csv"])

    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert "unique_key" in lines[0]
    assert "complaint_type" in lines[0]


@respx.mock
def test_fetch_writes_parquet_to_file(tmp_path: Path) -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _MOCK_ROWS})
    )
    out = tmp_path / "out.parquet"

    result = runner.invoke(
        app,
        ["fetch", _DOMAIN, _DATASET_ID, "--format", "parquet", "--output", str(out)],
    )

    assert result.exit_code == 0
    assert out.exists()
    table = pq.read_table(out)
    assert table.num_rows == 2


def test_fetch_rejects_parquet_without_output() -> None:
    result = runner.invoke(app, ["fetch", _DOMAIN, _DATASET_ID, "--format", "parquet"])
    assert result.exit_code == 1
    assert "--output is required" in result.output


def test_fetch_rejects_unknown_format() -> None:
    result = runner.invoke(app, ["fetch", _DOMAIN, _DATASET_ID, "--format", "xlsx"])
    assert result.exit_code == 1
    assert "Unknown format" in result.output


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


@respx.mock
def test_stream_writes_ndjson_to_stdout() -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _STREAM_ROWS})
    )

    result = runner.invoke(app, ["stream", _DOMAIN, _DATASET_ID, "--batch-size", "1000"])

    assert result.exit_code == 0
    lines = [ln for ln in result.stdout.strip().splitlines() if ln]
    assert len(lines) == 2


@respx.mock
def test_stream_writes_ndjson_to_file(tmp_path: Path) -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _STREAM_ROWS})
    )
    out = tmp_path / "out.ndjson"

    result = runner.invoke(
        app,
        ["stream", _DOMAIN, _DATASET_ID, "--output", str(out), "--batch-size", "1000"],
    )

    assert result.exit_code == 0
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["unique_key"] == "1"


@respx.mock
def test_stream_writes_parquet_to_file(tmp_path: Path) -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _STREAM_ROWS})
    )
    out = tmp_path / "out.parquet"

    result = runner.invoke(
        app,
        [
            "stream", _DOMAIN, _DATASET_ID,
            "--format", "parquet", "--output", str(out), "--batch-size", "1000",
        ],
    )

    assert result.exit_code == 0
    assert out.exists()
    assert pq.read_table(out).num_rows == 2


@respx.mock
def test_stream_writes_arrow_to_file(tmp_path: Path) -> None:
    respx.get(_V3_URL).mock(
        return_value=httpx.Response(200, json={"data": _STREAM_ROWS})
    )
    out = tmp_path / "out.arrow"

    result = runner.invoke(
        app,
        [
            "stream", _DOMAIN, _DATASET_ID,
            "--format", "arrow", "--output", str(out), "--batch-size", "1000",
        ],
    )

    assert result.exit_code == 0
    assert out.exists()
    with pa_ipc.open_file(out) as reader:
        assert reader.read_all().num_rows == 2


def test_stream_rejects_binary_format_without_output() -> None:
    result = runner.invoke(app, ["stream", _DOMAIN, _DATASET_ID, "--format", "arrow"])
    assert result.exit_code == 1
    assert "--output is required" in result.output
