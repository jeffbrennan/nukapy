"""Unit tests for output format writers."""

import inspect
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.ipc as pa_ipc
import pyarrow.parquet as pq
import pytest

from nukapy.formats import write_arrow_ipc, write_csv, write_json, write_ndjson, write_parquet

SAMPLE_ROWS = [
    {"id": "1", "name": "Alice", "score": 95},
    {"id": "2", "name": "Bob", "score": 87},
    {"id": "3", "name": "Carol", "score": 72},
]

SAMPLE_TABLE = pa.Table.from_pylist(SAMPLE_ROWS)


def test_write_parquet_roundtrips(tmp_path: Path) -> None:
    dest = tmp_path / "out.parquet"
    write_parquet(SAMPLE_TABLE, dest)
    result = pq.read_table(dest)
    assert result.num_rows == 3
    assert result.schema.names == ["id", "name", "score"]


def test_write_parquet_accepts_str_path(tmp_path: Path) -> None:
    dest = str(tmp_path / "out.parquet")
    write_parquet(SAMPLE_TABLE, dest)
    assert pq.read_table(dest).num_rows == 3


def test_write_parquet_compression(tmp_path: Path) -> None:
    dest = tmp_path / "out.parquet"
    write_parquet(SAMPLE_TABLE, dest, compression="zstd")
    meta = pq.read_metadata(dest)
    assert meta.row_group(0).column(0).compression == "ZSTD"


def test_write_csv_roundtrips(tmp_path: Path) -> None:
    dest = tmp_path / "out.csv"
    write_csv(SAMPLE_TABLE, dest)
    result = pa_csv.read_csv(dest)
    assert result.num_rows == 3
    assert set(result.schema.names) == {"id", "name", "score"}


def test_write_csv_accepts_str_path(tmp_path: Path) -> None:
    dest = str(tmp_path / "out.csv")
    write_csv(SAMPLE_TABLE, dest)
    assert pa_csv.read_csv(dest).num_rows == 3


def test_write_ndjson_produces_one_line_per_row(tmp_path: Path) -> None:
    dest = tmp_path / "out.ndjson"
    write_ndjson(SAMPLE_TABLE, dest)
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0]) == SAMPLE_ROWS[0]
    assert json.loads(lines[2]) == SAMPLE_ROWS[2]


def test_write_ndjson_accepts_str_path(tmp_path: Path) -> None:
    dest = str(tmp_path / "out.ndjson")
    write_ndjson(SAMPLE_TABLE, dest)
    lines = Path(dest).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_write_ndjson_handles_empty_table(tmp_path: Path) -> None:
    dest = tmp_path / "empty.ndjson"
    write_ndjson(pa.table({}), dest)
    assert dest.read_text(encoding="utf-8") == ""


def test_write_json_produces_array(tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    write_json(SAMPLE_TABLE, dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 3
    assert data[1] == SAMPLE_ROWS[1]


def test_write_json_accepts_str_path(tmp_path: Path) -> None:
    dest = str(tmp_path / "out.json")
    write_json(SAMPLE_TABLE, dest)
    data = json.loads(Path(dest).read_text(encoding="utf-8"))
    assert len(data) == 3


def test_write_json_handles_empty_table(tmp_path: Path) -> None:
    dest = tmp_path / "empty.json"
    write_json(pa.table({}), dest)
    assert json.loads(dest.read_text(encoding="utf-8")) == []


def test_write_arrow_ipc_roundtrips(tmp_path: Path) -> None:
    dest = tmp_path / "out.arrow"
    write_arrow_ipc(SAMPLE_TABLE, dest)
    with pa_ipc.open_file(dest) as reader:
        result = reader.read_all()
    assert result.num_rows == 3
    assert result.schema.names == ["id", "name", "score"]


def test_write_arrow_ipc_accepts_str_path(tmp_path: Path) -> None:
    dest = str(tmp_path / "out.arrow")
    write_arrow_ipc(SAMPLE_TABLE, dest)
    with pa_ipc.open_file(dest) as reader:
        assert reader.read_all().num_rows == 3


def test_write_arrow_ipc_preserves_schema(tmp_path: Path) -> None:
    dest = tmp_path / "out.arrow"
    write_arrow_ipc(SAMPLE_TABLE, dest)
    with pa_ipc.open_file(dest) as reader:
        assert reader.schema == SAMPLE_TABLE.schema


@pytest.mark.parametrize(
    ("writer", "suffix", "kwargs"),
    [
        (write_parquet, ".parquet", {}),
        (write_csv, ".csv", {}),
        (write_ndjson, ".ndjson", {}),
        (write_json, ".json", {}),
        (write_arrow_ipc, ".arrow", {}),
    ],
)
def test_all_writers_create_nonempty_file(
    tmp_path: Path,
    writer: object,
    suffix: str,
    kwargs: dict[str, object],
) -> None:
    dest = tmp_path / f"out{suffix}"
    assert callable(writer)
    sig = inspect.signature(writer)  # type: ignore[arg-type]
    all_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    writer(SAMPLE_TABLE, dest, **all_kwargs)  # type: ignore[call-arg]
    assert dest.exists()
    assert dest.stat().st_size > 0
