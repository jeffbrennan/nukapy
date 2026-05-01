"""Result wrapper interfaces."""

import dataclasses

import pyarrow as pa


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


__all__ = ["NukapyResult"]
