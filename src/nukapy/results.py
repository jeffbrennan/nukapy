"""Result wrapper interfaces."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from nukapy.formats import write_arrow_ipc, write_csv, write_json, write_ndjson, write_parquet

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd
    import polars as pl


@dataclasses.dataclass(frozen=True)
class NukapyResult:
    """Materialized result from an eager dataset fetch."""

    batches: tuple[pa.RecordBatch, ...]
    checkpoint: dict[str, object]

    @property
    def num_rows(self) -> int:
        """Return the total number of materialized rows."""
        return sum(batch.num_rows for batch in self.batches)

    def to_table(self) -> pa.Table:
        """Return all materialized batches as an Arrow table."""
        if not self.batches:
            return pa.table({})
        return pa.Table.from_batches(self.batches)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return all rows as a list of dicts."""
        rows: list[dict[str, Any]] = []
        for batch in self.batches:
            rows.extend(batch.to_pylist())
        return rows

    def to_polars(self) -> pl.DataFrame:
        """Return all rows as a Polars DataFrame.

        Requires ``polars`` to be installed (``pip install polars``).
        """
        try:
            import polars as pl  # noqa: PLC0415
        except ImportError as exc:
            msg = "polars is required: pip install polars"
            raise ImportError(msg) from exc
        return pl.from_arrow(self.to_table())

    def to_pandas(self) -> pd.DataFrame:
        """Return all rows as a pandas DataFrame.

        Requires ``pandas`` to be installed (``pip install pandas``).
        """
        try:
            import pandas as pd  # noqa: PLC0415
        except ImportError as exc:
            msg = "pandas is required: pip install pandas"
            raise ImportError(msg) from exc
        return pd.DataFrame(self.to_dicts())

    def write_parquet(self, path: str | Path, *, compression: str = "snappy") -> None:
        """Write the result to a Parquet file."""
        write_parquet(self.to_table(), path, compression=compression)

    def write_csv(self, path: str | Path) -> None:
        """Write the result to a CSV file."""
        write_csv(self.to_table(), path)

    def write_ndjson(self, path: str | Path) -> None:
        """Write the result to a newline-delimited JSON file."""
        write_ndjson(self.to_table(), path)

    def write_json(self, path: str | Path) -> None:
        """Write the result to a JSON array file."""
        write_json(self.to_table(), path)

    def write_arrow_ipc(self, path: str | Path) -> None:
        """Write the result to an Arrow IPC file."""
        write_arrow_ipc(self.to_table(), path)


__all__ = ["NukapyResult"]
