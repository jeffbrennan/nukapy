# Pagination and iteration plan

## Goals

Support bounded-memory reads over Socrata datasets with async-first iteration,
sync iteration for users without an event loop, and an eager convenience API for
small or intentionally materialized reads.

## Public API

```python
async for batch in dataset.stream(batch_size=10_000):
    process(batch)
```

`dataset.stream(...)` is the primary API. It yields Arrow `RecordBatch` objects
and requests the next page only when the consumer advances the iterator.

```python
for batch in dataset.iter_batches(batch_size=10_000):
    process(batch)
```

`dataset.iter_batches(...)` is the sync equivalent for code that does not run an
event loop.

```python
result = dataset.fetch()
```

`dataset.fetch(...)` is the eager API. It consumes the iterator internally and
returns a `NukapyResult`. This materializes every batch in memory, so it is for
small reads or cases where the caller explicitly wants an in-memory result.

## Pagination strategies

### `:id` cursor

The default strategy for large reads is the Socrata system `:id` cursor:

```sql
WHERE :id > <last_seen_id>
ORDER BY :id
LIMIT <batch_size>
```

This is the default because it is drift-free for full-dataset scans, avoids the
increasing server work of deep offsets, and scales to very large datasets. Each
page resumes after the last row seen instead of asking the server to skip an
ever-growing prefix.

### Offset

Offset pagination uses:

```sql
LIMIT <batch_size>
OFFSET <offset>
```

This is kept for compatibility and small queries. It is simple and works with
existing SoQL patterns, but it is not ideal for large reads because deep offsets
get more expensive and concurrent inserts/deletes can cause drift.

### `:updated_at` incremental sync

Incremental reads use:

```sql
WHERE :updated_at > <checkpoint>
ORDER BY :updated_at, :id
LIMIT <batch_size>
```

This strategy is for sync-style workloads that only need rows changed after the
last checkpoint. The iterator should accept a `state` mapping now so durable
resumable sync can be layered on later without changing the protocol.

## Resumability slot

Iterator constructors should accept `state: Mapping[str, object] | None = None`
and expose the latest checkpoint as a dict. Do not build a full resumable sync
engine yet. The important design constraint is that callers can persist the
checkpoint between yielded batches without changing the batch-yielding protocol.

## Batch sizing

Default `batch_size` is 10,000 rows and should be configurable. Smaller batches
reduce first-row latency and per-request memory pressure but require more HTTP
requests. Larger batches reduce request count and overhead but increase latency,
payload size, and memory used per batch.

## Backpressure

The iterator should not eagerly buffer ahead. The default semantics are a
bounded channel of size zero: one request is made for the next batch only after
the consumer asks for it. If a consumer is slow, nukapy should apply natural
backpressure instead of accumulating unprocessed pages in memory.

## Open questions

- How should server-side query timeouts be surfaced when they happen after one
  or more batches have already been yielded?
- How should mid-stream schema changes be handled if later batches have columns
  or types that differ from earlier batches?

## Verification

- Unit tests for all three pagination strategies.
- Tests for async and sync iterators yielding Arrow `RecordBatch` objects.
- Tests proving eager `fetch()` consumes the iterator and materializes batches.
- Tests proving no extra request is made before the consumer advances.
- Run `just format`, `just lint`, `just typecheck`, and `just test`.
