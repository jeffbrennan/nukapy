# nukapy

A modern, typed, async-first Python SDK for the Socrata Open Data API (SODA).

`nukapy` is planned as a successor to [`sodapy`](https://github.com/afeld/sodapy), with a focus on typed interfaces, bounded-memory reads, and Arrow-native workflows.

This repository is currently in early scaffold stage. See `docs/planning/01-roadmap.md` for the initial roadmap.

## Development

This project uses `uv` for dependency management and `just` for common tasks.

```sh
uv sync
just quality
```

## Dataset Iteration

Use `dataset.stream()` for bounded-memory async reads. It yields Arrow
`RecordBatch` objects and makes one request at a time.

```python
from nukapy import AsyncSocrata

async with AsyncSocrata("data.cityofnewyork.us") as client:
    dataset = client.dataset("erm2-nwe9")
    async for batch in dataset.stream(batch_size=10_000):
        process(batch)
```

Use `dataset.iter_batches()` from sync code that does not have an event loop.

```python
from nukapy import Socrata

with Socrata("data.cityofnewyork.us") as client:
    dataset = client.dataset("erm2-nwe9")
    for batch in dataset.iter_batches(batch_size=10_000):
        process(batch)
```

Use `dataset.fetch()` only when you intentionally want an in-memory result.
`fetch()` consumes the iterator internally and returns a `NukapyResult`, so it
materializes every returned batch.

```python
with Socrata("data.cityofnewyork.us") as client:
    result = client.dataset("erm2-nwe9").fetch(batch_size=10_000)

print(result.num_rows)
table = result.to_table()
```

## Pagination Strategies

`strategy="id"` is the default for large reads. It uses the Socrata system `:id`
as a cursor:

```sql
WHERE :id > <last_seen_id>
ORDER BY :id
LIMIT <batch_size>
```

This is drift-free for full scans, avoids the growing server cost of deep
offsets, and scales to very large datasets because each request resumes after the
last row seen.

`strategy="offset"` uses `$limit` and `$offset`. It is useful for compatibility
and small queries, but it can drift when rows are inserted or deleted and deep
offsets get slower as the skipped prefix grows.

`strategy="updated_at"` is for incremental sync reads. It uses Socrata's
`:updated_at` system field with `:id` as a tie-breaker:

```sql
WHERE :updated_at > <checkpoint>
ORDER BY :updated_at, :id
LIMIT <batch_size>
```

Iterator constructors accept a `state` mapping and expose the latest checkpoint
as `stream.checkpoint` or `iterator.checkpoint`. Durable resumable sync is not
built yet, but the protocol is shaped so callers can persist checkpoints between
batches.

The default batch size is 10,000 rows. Smaller batches reduce first-batch latency
and memory pressure but require more requests. Larger batches reduce request
count but increase latency and per-batch memory usage.

The iterators do not prefetch. The next request is made only when the consumer
asks for the next batch, so slow consumers apply natural backpressure instead of
causing nukapy to buffer pages ahead.

Open questions for this branch are how to surface server-side query timeouts
after partial progress and how to handle mid-stream schema changes.

## Acknowledgments

`nukapy` builds on the path opened by `sodapy` and the broader Socrata open data community.
