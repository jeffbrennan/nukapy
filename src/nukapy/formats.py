"""Output format writers for Arrow tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.ipc as pa_ipc
import pyarrow.parquet as pq


def write_parquet(
    table: pa.Table,
    path: str | Path,
    *,
    compression: str = "snappy",
) -> None:
    """Write an Arrow table to a Parquet file."""
    pq.write_table(table, path, compression=compression)


def write_csv(table: pa.Table, path: str | Path) -> None:
    """Write an Arrow table to a CSV file."""
    pa_csv.write_csv(table, path)


def write_ndjson(table: pa.Table, path: str | Path) -> None:
    """Write an Arrow table to a newline-delimited JSON (NDJSON) file."""
    dest = Path(path)
    with dest.open("w", encoding="utf-8") as fh:
        for batch in table.to_batches():
            for row in batch.to_pylist():
                fh.write(json.dumps(row, default=_json_default) + "\n")


def write_json(table: pa.Table, path: str | Path) -> None:
    """Write an Arrow table to a JSON array file."""
    rows: list[dict[str, Any]] = []
    for batch in table.to_batches():
        rows.extend(batch.to_pylist())
    Path(path).write_text(json.dumps(rows, default=_json_default), encoding="utf-8")


def write_arrow_ipc(table: pa.Table, path: str | Path) -> None:
    """Write an Arrow table to an Arrow IPC file (random-access format)."""
    with pa_ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table)


def _json_default(obj: object) -> str:
    """Fallback serializer for types not natively handled by json.dumps."""
    return str(obj)


__all__ = [
    "write_arrow_ipc",
    "write_csv",
    "write_json",
    "write_ndjson",
    "write_parquet",
]
