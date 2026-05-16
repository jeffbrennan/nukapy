"""Unit tests for NukapyResult conversion and write methods."""

import builtins
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.ipc as pa_ipc
import pyarrow.parquet as pq
import pytest

from nukapy.results import NukapyResult

SAMPLE_ROWS = [
    {"id": "1", "city": "New York", "count": 100},
    {"id": "2", "city": "Chicago", "count": 55},
]

SAMPLE_BATCH = pa.RecordBatch.from_pylist(SAMPLE_ROWS)
SAMPLE_RESULT = NukapyResult(batches=(SAMPLE_BATCH,), checkpoint={})

EMPTY_RESULT = NukapyResult(batches=(), checkpoint={})


def test_to_dicts_returns_all_rows() -> None:
    rows = SAMPLE_RESULT.to_dicts()
    assert rows == SAMPLE_ROWS


def test_to_dicts_preserves_order() -> None:
    rows = SAMPLE_RESULT.to_dicts()
    assert rows[0]["id"] == "1"
    assert rows[1]["id"] == "2"


def test_to_dicts_empty_result() -> None:
    assert EMPTY_RESULT.to_dicts() == []


def test_to_dicts_multi_batch() -> None:
    batch_a = pa.RecordBatch.from_pylist([{"x": 1}])
    batch_b = pa.RecordBatch.from_pylist([{"x": 2}])
    result = NukapyResult(batches=(batch_a, batch_b), checkpoint={})
    assert result.to_dicts() == [{"x": 1}, {"x": 2}]


def test_to_polars_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "polars":
            msg = "No module named 'polars'"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    with pytest.raises(ImportError, match="pip install polars"):
        SAMPLE_RESULT.to_polars()


def test_to_pandas_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "pandas":
            msg = "No module named 'pandas'"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    with pytest.raises(ImportError, match="pip install pandas"):
        SAMPLE_RESULT.to_pandas()


def test_write_parquet_creates_readable_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.parquet"
    SAMPLE_RESULT.write_parquet(dest)
    result = pq.read_table(dest)
    assert result.num_rows == 2


def test_write_parquet_accepts_compression(tmp_path: Path) -> None:
    dest = tmp_path / "out.parquet"
    SAMPLE_RESULT.write_parquet(dest, compression="zstd")
    assert dest.exists()


def test_write_csv_creates_readable_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.csv"
    SAMPLE_RESULT.write_csv(dest)
    result = pa_csv.read_csv(dest)
    assert result.num_rows == 2


def test_write_ndjson_creates_correct_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.ndjson"
    SAMPLE_RESULT.write_ndjson(dest)
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["city"] == "New York"


def test_write_json_creates_correct_file(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    SAMPLE_RESULT.write_json(dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[1]["city"] == "Chicago"


def test_write_arrow_ipc_roundtrips(tmp_path: Path) -> None:
    dest = tmp_path / "out.arrow"
    SAMPLE_RESULT.write_arrow_ipc(dest)
    with pa_ipc.open_file(dest) as reader:
        result = reader.read_all()
    assert result.num_rows == 2


def test_write_methods_return_none(tmp_path: Path) -> None:
    assert SAMPLE_RESULT.write_parquet(tmp_path / "a.parquet") is None
    assert SAMPLE_RESULT.write_csv(tmp_path / "a.csv") is None
    assert SAMPLE_RESULT.write_ndjson(tmp_path / "a.ndjson") is None
    assert SAMPLE_RESULT.write_json(tmp_path / "a.json") is None
    assert SAMPLE_RESULT.write_arrow_ipc(tmp_path / "a.arrow") is None
