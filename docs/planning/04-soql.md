# SoQL query builder plan

## Goals

Build a typed, fluent, IDE-autocomplete-friendly SoQL query builder for read
queries. The builder should cover common filtering, projection, aggregation,
ordering, and geospatial use cases while keeping a raw escape hatch for advanced
SoQL fragments.

## Non-goals

- Full SQL or SoQL parsing.
- Dataset write operations. Those belong to Socrata's Data Management API and
  are out of scope for nukapy v1.
- v3 POST JSON query bodies in the first pass. Use individual SODA query params
  for now and revisit POST bodies with pagination/read-path work.
- Top-level `nukapy` exports for query helpers. Query APIs are exported from
  `nukapy.soql` only.

## Public API

```python
from nukapy.soql import Query, col, count, within_circle

query = (
    Query()
    .select(col("complaint_type"), count().as_("count"))
    .where(col("created_date") >= "2024-01-01T00:00:00")
    .group_by(col("complaint_type"))
    .having(count() > 10)
    .order_by(count().desc())
    .limit(100)
)

rows = client.get("erm2-nwe9", query=query)
```

## Core abstractions

- `Expression`: base renderable object for all SoQL expressions.
- `Column`: identifier-backed expression created with `col("field")`.
- `Literal`: safely escaped Python value.
- `Function`: function call expression.
- `BinaryExpression`: comparison and boolean join expression.
- `UnaryExpression`: `NOT` and similar unary expressions.
- `AliasedExpression`: `expr AS alias` for selections.
- `OrderExpression`: `expr ASC` or `expr DESC` for ordering.
- `RawExpression`: explicit escape hatch for advanced fragments.
- `Query`: immutable fluent object holding select, where, group, having, order,
  limit, and offset clauses.

Use frozen dataclasses and tuple fields where possible so chained calls return
new objects instead of mutating existing queries.

## Operator strategy

Python operators map to SoQL as follows:

| Python | SoQL |
| --- | --- |
| `col("x") == 5` | `` `x` = 5 `` |
| `col("x") != 5` | `` `x` != 5 `` |
| `>` / `>=` / `<` / `<=` | same SoQL operators |
| `(a) & (b)` | `(a AND b)` |
| `(a) \| (b)` | `(a OR b)` |
| `~expr` | `NOT expr` |
| `col("x").in_([...])` | `` `x` IN (...) `` |
| `col("x").not_in([...])` | `` `x` NOT IN (...) `` |
| `col("x").between(a, b)` | `` `x` BETWEEN a AND b `` |
| `col("x").is_null()` | `` `x` IS NULL `` |
| `col("x").is_not_null()` | `` `x` IS NOT NULL `` |

`Expression.__bool__` raises `TypeError` so accidental Python `and` / `or`
usage fails loudly. Users should parenthesize comparisons before combining them
with `&` or `|`.

## V1 functions

- Aggregates: `count`, `sum_`, `avg`, `min_`, `max_`.
- String functions: `upper`, `lower`, `starts_with`.
- Date functions: `date_trunc_y`, `date_trunc_ym`, `date_trunc_ymd`.
- Geospatial functions: `within_circle`, `within_box`, `distance_in_meters`.

Use underscore suffixes where helper names would shadow Python builtins.

## Quoting and escaping

This is the most security-sensitive part of the module.

- Identifiers render as backticked SoQL names, for example `col("created_date")`
  renders as `` `created_date` ``.
- Identifiers containing backticks or NUL bytes are rejected.
- String literals render with single quotes, and embedded single quotes are
  doubled.
- `date` and `datetime` values render as ISO strings in single quotes.
- Boolean values render as `true` or `false`.
- Numeric values must be finite; `nan` and infinity are rejected.
- `None` should be expressed through `is_null()` or `is_not_null()` rather than
  raw equality.
- Raw fragments do not bypass escaping for supplied placeholder values.

## Raw escape hatch

`Query.raw_where(fragment, *params)` accepts an arbitrary SoQL fragment. Question
mark placeholders are replaced client-side with values rendered through the same
literal escaper used by typed expressions.

```python
query = Query().raw_where("`status` = ? AND `amount` > ?", "Open", 100)
```

Fragments without placeholders are allowed, but this is explicitly the "I know
what I'm doing" path.

## Query introspection

- `query.to_soql()` returns a full SoQL statement.
- `query.to_params()` returns individual SODA params: `$select`, `$where`,
  `$group`, `$having`, `$order`, `$limit`, and `$offset`.
- `query.to_url(domain, dataset_id)` builds a debugging URL.
- `query.explain()` returns a readable multiline debug string with rendered
  clauses and warnings such as raw fragment usage or a missing limit.

## Client integration

Add `query: Query | None = None` to sync and async `get()` methods.

```python
client.get("erm2-nwe9", query=query)
```

If `query` is provided, reject simultaneous `select` or `limit` arguments with a
`ValueError` to avoid ambiguous merging. Existing `select` and `limit` behavior
continues to work unchanged.

## Examples to document

- Select columns and limit rows.
- Filter with comparison, dates, and boolean operators.
- Case-normalized text filtering with `lower()` and `starts_with()`.
- Aggregation with `group_by()`, `count()`, `having()`, and `order_by()`.
- Geospatial `within_circle()` query.
- `distance_in_meters()` query ordered by nearest distance.

## Verification

- Unit tests for each rendered clause.
- Operator precedence and parentheses tests.
- Escaping tests for strings, identifiers, datetimes, booleans, and invalid
  floats.
- Injection-focused tests around quotes and raw placeholders.
- Function rendering tests for aggregate, string, date, and geospatial helpers.
- Client tests proving `query.to_params()` is passed to requests.
- Run `just format`, `just lint`, `just typecheck`, and `just test`.
