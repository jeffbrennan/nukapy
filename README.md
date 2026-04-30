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

## Acknowledgments

`nukapy` builds on the path opened by `sodapy` and the broader Socrata open data community.
