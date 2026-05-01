# Transport layer

## Architecture decision

nukapy uses a single async transport core. `AsyncTransport` owns one
`httpx.AsyncClient` per client instance, so connection pooling, retries,
authentication, rate-limit tracking, and error mapping all live in one place.

The sync `Transport` facade runs that same async path on a private event loop in a
background thread. This avoids duplicating sync and async HTTP logic. The tradeoff
is that sync users pay a small event-loop and thread startup cost when they create
a client.

Public clients follow the same split:

- `AsyncSocrata` wraps `AsyncTransport` directly.
- `Socrata` wraps the sync `Transport` facade.

Both public clients share request construction, authentication configuration, and
SODA URL selection behavior.

## SODA versions

nukapy is SODA v3 ready but still supports SODA v2.1 endpoints. Read requests
default to the v3 endpoint shape and fall back to v2.1 if v3 is unavailable for a
domain or dataset.

The URL shapes are different:

- SODA v3 query endpoint: `/api/v3/views/{id}/query.json`
- SODA v2.1 resource endpoint: `/resource/{id}.json`

Version support can be inferred from Socrata metadata and version headers when a
domain exposes them. The transport also keeps a pragmatic fallback path: if the v3
query shape returns an unsupported-path style client error, the client retries the
same read through the v2.1 resource shape.
