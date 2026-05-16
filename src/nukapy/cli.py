"""CLI for nukapy."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path  # noqa: TC003  -- typer resolves annotations at runtime
from typing import TYPE_CHECKING, Annotated

import httpx
import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.ipc as pa_ipc
import pyarrow.parquet as pq
import typer

from nukapy._version import __version__
from nukapy.client import Socrata
from nukapy.formats import write_arrow_ipc, write_csv, write_json, write_ndjson, write_parquet

if TYPE_CHECKING:
    from collections.abc import Iterator

    from nukapy.client import BatchIterator

app = typer.Typer(no_args_is_help=True)
datasets_app = typer.Typer(no_args_is_help=True, help="Search and inspect Socrata datasets.")
app.add_typer(datasets_app, name="datasets")

_DISCOVERY_URL = "https://api.us.socrata.com/api/catalog/v1"
_BINARY_FORMATS = {"parquet", "arrow"}
_ALL_FORMATS = {"ndjson", "json", "csv", "parquet", "arrow"}


@app.command()
def version() -> None:
    """Print the nukapy version."""
    typer.echo(__version__)


@datasets_app.command("search")
def datasets_search(
    domain: Annotated[str, typer.Argument(help="Socrata domain (e.g. data.cityofchicago.org)")],
    query: Annotated[str | None, typer.Argument(help="Search terms")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results to show")] = 10,
) -> None:
    """Search for datasets on a Socrata domain."""
    params: dict[str, str | int] = {"domains": domain, "limit": limit}
    if query:
        params["q"] = query

    try:
        response = httpx.get(_DISCOVERY_URL, params=params, timeout=15.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"Request failed: {exc}", err=True)
        raise typer.Exit(1) from exc

    results = response.json().get("results", [])
    if not results:
        typer.echo("No datasets found.")
        raise typer.Exit

    for result in results:
        resource = result.get("resource", {})
        dataset_id = resource.get("id", "?")
        name = resource.get("name", "?")
        updated = (resource.get("updatedAt") or "")[:10]
        typer.echo(f"{dataset_id}  {updated}  {name}")


@datasets_app.command("info")
def datasets_info(
    domain: Annotated[str, typer.Argument(help="Socrata domain")],
    dataset_id: Annotated[str, typer.Argument(help="Dataset 4x4 ID (e.g. erm2-nwe9)")],
) -> None:
    """Show metadata for a dataset."""
    with Socrata(domain) as client:
        meta = client.metadata(dataset_id)

    typer.echo(f"ID:          {meta.id}")
    typer.echo(f"Name:        {meta.name}")
    if meta.description:
        typer.echo(f"Description: {meta.description}")
    if meta.category:
        typer.echo(f"Category:    {meta.category}")
    if meta.tags:
        typer.echo(f"Tags:        {', '.join(meta.tags)}")
    typer.echo(f"\nColumns ({len(meta.columns)}):")
    for col in meta.columns:
        desc = f"  # {col.description}" if col.description else ""
        typer.echo(f"  {col.field_name:30s} {col.data_type_name}{desc}")


@app.command()
def fetch(
    domain: Annotated[str, typer.Argument(help="Socrata domain")],
    dataset_id: Annotated[str, typer.Argument(help="Dataset 4x4 ID (e.g. erm2-nwe9)")],
    limit: Annotated[int | None, typer.Option("--limit", "-n", help="Row limit")] = None,
    select: Annotated[str | None, typer.Option("--select", help="Columns to select")] = None,
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: ndjson, json, csv, parquet, arrow"),
    ] = "ndjson",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file (default: stdout)")
    ] = None,
) -> None:
    """Fetch rows from a dataset and write to stdout or a file."""
    _validate_format(fmt, output)
    with Socrata(domain) as client:
        rows = client.get(dataset_id, limit=limit, select=select)
    table = pa.Table.from_pylist(rows)
    _write_table(table, fmt, output)


@app.command()
def stream(
    domain: Annotated[str, typer.Argument(help="Socrata domain")],
    dataset_id: Annotated[str, typer.Argument(help="Dataset 4x4 ID (e.g. erm2-nwe9)")],
    batch_size: Annotated[int, typer.Option("--batch-size", help="Rows per batch")] = 50_000,
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: ndjson, json, csv, parquet, arrow"),
    ] = "ndjson",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Output file (default: stdout)")
    ] = None,
) -> None:
    """Stream all rows from a dataset using bounded memory."""
    _validate_format(fmt, output)
    with Socrata(domain) as client:
        iterator = client.dataset(dataset_id).iter_batches(batch_size=batch_size)
        _dispatch_stream(iterator, fmt, output)


def _dispatch_stream(
    iterator: BatchIterator,
    fmt: str,
    output: Path | None,
) -> None:
    if fmt == "ndjson":
        _stream_ndjson(iterator, output)
    elif fmt == "parquet":
        _stream_parquet(iterator, output)
    elif fmt == "arrow":
        _stream_arrow_ipc(iterator, output)
    else:
        batches = list(iterator)
        table = pa.Table.from_batches(batches) if batches else pa.table({})
        _write_table(table, fmt, output)


def _stream_ndjson(iterator: Iterator[pa.RecordBatch], output: Path | None) -> None:
    fh = output.open("w", encoding="utf-8") if output else sys.stdout
    try:
        for batch in iterator:
            for row in batch.to_pylist():
                fh.write(json.dumps(row, default=str) + "\n")
    finally:
        if output:
            fh.close()


def _stream_parquet(iterator: Iterator[pa.RecordBatch], output: Path | None) -> None:
    writer: pq.ParquetWriter | None = None
    try:
        for batch in iterator:
            if writer is None:
                writer = pq.ParquetWriter(output, batch.schema)
            writer.write_batch(batch)
    finally:
        if writer:
            writer.close()


def _stream_arrow_ipc(
    iterator: Iterator[pa.RecordBatch], output: Path | None
) -> None:
    ipc_writer: pa_ipc.RecordBatchFileWriter | None = None
    try:
        for batch in iterator:
            if ipc_writer is None:
                ipc_writer = pa_ipc.new_file(str(output), batch.schema)
            ipc_writer.write_batch(batch)
    finally:
        if ipc_writer:
            ipc_writer.close()


def _write_table(table: pa.Table, fmt: str, output: Path | None) -> None:
    if output:
        _write_table_to_file(table, fmt, output)
    else:
        _write_table_to_stdout(table, fmt)


def _write_table_to_file(table: pa.Table, fmt: str, path: Path) -> None:
    if fmt == "ndjson":
        write_ndjson(table, path)
    elif fmt == "json":
        write_json(table, path)
    elif fmt == "csv":
        write_csv(table, path)
    elif fmt == "parquet":
        write_parquet(table, path)
    elif fmt == "arrow":
        write_arrow_ipc(table, path)


def _write_table_to_stdout(table: pa.Table, fmt: str) -> None:
    if fmt == "ndjson":
        for batch in table.to_batches():
            for row in batch.to_pylist():
                sys.stdout.write(json.dumps(row, default=str) + "\n")
    elif fmt == "json":
        rows: list[object] = []
        for batch in table.to_batches():
            rows.extend(batch.to_pylist())
        sys.stdout.write(json.dumps(rows, default=str) + "\n")
    elif fmt == "csv":
        buf = io.BytesIO()
        pa_csv.write_csv(table, buf)
        sys.stdout.buffer.write(buf.getvalue())


def _validate_format(fmt: str, output: Path | None) -> None:
    if fmt not in _ALL_FORMATS:
        typer.echo(
            f"Unknown format {fmt!r}. Choose from: {', '.join(sorted(_ALL_FORMATS))}",
            err=True,
        )
        raise typer.Exit(1)
    if fmt in _BINARY_FORMATS and output is None:
        typer.echo(f"--output is required for format {fmt!r}.", err=True)
        raise typer.Exit(1)
