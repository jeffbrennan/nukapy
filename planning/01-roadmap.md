# nukapy roadmap

## Vision

nukapy is a modern, typed, async Python client for the Socrata Open Data API
(SODA). It is the successor to sodapy, which has been unmaintained since 2022.

It exists to serve data engineers, analysts, and civic-tech / public-health
practitioners who consume open data from Socrata-powered portals (NYC Open Data,
data.cdc.gov, data.cityofchicago.org, healthdata.gov, and hundreds more).

The core value proposition is:

- **Typed**: Pydantic v2 models for metadata, a typed SoQL query builder,
  pyright strict throughout
- **Async-first**: httpx-based, with bounded-memory iteration over multi-million
  row datasets
- **Arrow-native**: Polars and Arrow are first-class outputs; pandas is optional
- **SODA v3 ready**: built for the v3 endpoint shape, with v2.1 fallback

## Non-goals for v1

These are deliberately excluded to keep scope tight. Each may be revisited
later; none is on the v1 critical path.

- Socrata Data Management API (dataset creation, transforms). Out of scope
  permanently — that is a different API and `socrata-py` covers it.
- Built-in sync engine with state and config (`nukapy sync`, `nukapy check`).
  Deferred to v0.2 or punted to a dlt source.
- Codegen of dataset-specific Pydantic models. Designed in v1, implemented in
  v0.2.
- Geospatial DataFrame support (geopandas, GeoParquet). Deferred to v0.2.
- Dagster, Airflow, dbt integrations. Designed in v1, separate packages later.
- Delta Lake / Iceberg output formats. Deferred.
- Write operations (PUT, POST, DELETE on datasets). Designed for via the API
  key + secret slot, but not implemented.

## Milestones

### M1 — Walking skeleton

A package that installs, imports, and successfully fetches five rows from NYC
311. Proves the toolchain end-to-end. Most of the code is throwaway.

- Project scaffolding (uv, hatchling, ruff, pyright, pytest, GHA)
- Hello-world sync client: `Socrata(domain).get(dataset_id, limit=5)`
- One live integration test, one cassette-replay unit test
- CI green on Python 3.11, 3.12, 3.13

### M2 — Core read path

The architecture proper. Async transport, pagination, query builder MVP, output
formats. By the end of M2, you can pull 10M rows of 311 to Parquet in bounded
memory.

- Async transport layer with sync facade, retries, rate limit awareness
- `:id`-cursor pagination with async iterator yielding Arrow RecordBatches
- SoQL query builder MVP: select, where, order, limit, group, basic functions
- Output formats: Parquet, NDJSON, CSV, JSON, Arrow IPC
- In-memory returns: Polars, Arrow, dict iterator, optional pandas
- Pydantic models for metadata and Discovery API responses
- Error hierarchy and exception types

### M3 — Polish and v0.1 release

- CLI: `datasets search`, `datasets info`, `fetch`, `stream`, `version`
- Structured logging with structlog (lazy, off by default)
- Test coverage 80%+ with hypothesis property tests on SoQL
- Benchmark suite producing the README charts
- README with quickstart, performance section, examples, attribution
- CHANGELOG, CONTRIBUTING, MIT license, semver discipline
- PyPI release as `0.1.0`

### M4 — v0.2 and beyond (deferred)
- Dataset codegen (`nukapy codegen DATASET_ID`)
- dlt source for `nukapy` (probably the right path instead of in-tree sync)
- OpenTelemetry tracing
- Geospatial: GeoParquet writes, geopandas conversion, geo-aware SoQL functions
- Delta Lake output
- Bundled models for the top ~10 most-used datasets

## Build order

The natural reading order of the planning docs is not the right build order.
This is the build order, with rationale.

1. **Scaffolding** (`01`) — locks tooling decisions, blocks everything
2. **Hello-world** (`02`) — proves toolchain works before any real architecture
3. **Testing strategy** (`11`) — written early because it shapes every module
4. **Transport layer** (`03`) — the foundation; everything sits on it
5. **Pagination and iteration** (`06`) — needs transport, blocks anything large
6. **Output formats** (`07`) — needs iteration to produce batches
7. **SoQL query builder** (`04`) — parallelizable with 6/7, doesn't block them
8. **Error handling and retries** (`09`) — woven through transport, formalize once shape is clear
9. **Typed models** (`05`) — Pydantic for metadata; defer codegen
10. **CLI** (`08`) — sits on top of everything above
11. **Observability** (`10`) — minimal logging in v0.1, full OTel later
12. **Benchmarks** (`12`) — once core path is stable
13. **Documentation and release** (`13`) — final mile

## Definition of done for v0.1

A concrete checklist. v0.1 ships when all are true.

- [ ] Published to PyPI as `nukapy==0.1.0`
- [ ] `pip install nukapy` works on Python 3.11, 3.12, 3.13
- [ ] Pyright strict mode passes with zero errors
- [ ] Ruff format and lint pass
- [ ] Test coverage ≥ 80% overall, ≥ 90% on transport / soql / pagination
- [ ] CI green on Ubuntu and macOS
- [ ] README under 400 lines with: quickstart, why-nukapy, performance charts,
      five examples, comparison table, install, roadmap, attribution
- [ ] Three working examples in `examples/`: NYC 311 incremental pattern, CDC
      PLACES public health pull, Chicago Crimes geo query
- [ ] Benchmarks reproducible via `benchmarks/run.py`, results checked in
- [ ] CHANGELOG follows Keep a Changelog format
- [ ] sodapy attribution paragraph in README and ACKNOWLEDGMENTS.md
- [ ] GitHub release tagged with notes
