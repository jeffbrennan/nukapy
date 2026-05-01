"""Typed helpers for building Socrata SoQL read queries."""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from typing import TYPE_CHECKING, Self
from typing import Literal as TypingLiteral
from urllib.parse import urlencode

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

SoQLParamValue = str | int | float
LiteralValue = str | int | float | bool | dt.date | dt.datetime
OrderDirection = TypingLiteral["ASC", "DESC"]


class Expression:
    """Base class for renderable SoQL expressions."""

    __hash__ = object.__hash__

    def as_(self, alias: str) -> AliasedExpression:
        """Return this expression aliased for a SELECT clause."""
        return AliasedExpression(self, alias)

    def asc(self) -> OrderExpression:
        """Return this expression as an ascending ORDER BY term."""
        return OrderExpression(self, "ASC")

    def desc(self) -> OrderExpression:
        """Return this expression as a descending ORDER BY term."""
        return OrderExpression(self, "DESC")

    def in_(self, values: Iterable[object]) -> Expression:
        """Return an IN expression for the supplied values."""
        value_tuple = tuple(_as_expression(value) for value in values)
        if not value_tuple:
            msg = "IN expressions require at least one value"
            raise ValueError(msg)
        return InExpression(self, value_tuple, negated=False)

    def not_in(self, values: Iterable[object]) -> Expression:
        """Return a NOT IN expression for the supplied values."""
        value_tuple = tuple(_as_expression(value) for value in values)
        if not value_tuple:
            msg = "NOT IN expressions require at least one value"
            raise ValueError(msg)
        return InExpression(self, value_tuple, negated=True)

    def between(self, lower: object, upper: object) -> Expression:
        """Return a BETWEEN expression."""
        return BetweenExpression(self, _as_expression(lower), _as_expression(upper), negated=False)

    def not_between(self, lower: object, upper: object) -> Expression:
        """Return a NOT BETWEEN expression."""
        return BetweenExpression(self, _as_expression(lower), _as_expression(upper), negated=True)

    def is_null(self) -> Expression:
        """Return an IS NULL expression."""
        return PostfixExpression(self, "IS NULL")

    def is_not_null(self) -> Expression:
        """Return an IS NOT NULL expression."""
        return PostfixExpression(self, "IS NOT NULL")

    def render(self) -> str:
        """Render this expression as SoQL."""
        return self._render()

    def __eq__(self, other: object) -> BinaryExpression:  # type: ignore[override]
        """Return a SoQL equality comparison."""
        return BinaryExpression(self, "=", _as_expression(other))

    def __ne__(self, other: object) -> BinaryExpression:  # type: ignore[override]
        """Return a SoQL inequality comparison."""
        return BinaryExpression(self, "!=", _as_expression(other))

    def __gt__(self, other: object) -> BinaryExpression:
        """Return a SoQL greater-than comparison."""
        return BinaryExpression(self, ">", _as_expression(other))

    def __ge__(self, other: object) -> BinaryExpression:
        """Return a SoQL greater-than-or-equal comparison."""
        return BinaryExpression(self, ">=", _as_expression(other))

    def __lt__(self, other: object) -> BinaryExpression:
        """Return a SoQL less-than comparison."""
        return BinaryExpression(self, "<", _as_expression(other))

    def __le__(self, other: object) -> BinaryExpression:
        """Return a SoQL less-than-or-equal comparison."""
        return BinaryExpression(self, "<=", _as_expression(other))

    def __and__(self, other: object) -> BinaryExpression:
        """Return a SoQL AND expression."""
        return BinaryExpression(self, "AND", _as_expression(other))

    def __or__(self, other: object) -> BinaryExpression:
        """Return a SoQL OR expression."""
        return BinaryExpression(self, "OR", _as_expression(other))

    def __invert__(self) -> UnaryExpression:
        """Return a SoQL NOT expression."""
        return UnaryExpression("NOT", self)

    def __bool__(self) -> bool:
        """Reject accidental Python boolean evaluation."""
        msg = "SoQL expressions cannot be used as booleans; use '&' or '|' instead"
        raise TypeError(msg)

    def _render(self) -> str:
        msg = f"{type(self).__name__} must implement _render()"
        raise NotImplementedError(msg)


@dataclasses.dataclass(frozen=True, eq=False)
class Column(Expression):
    """A backtick-quoted SoQL column identifier."""

    name: str

    def _render(self) -> str:
        return _quote_identifier(self.name)


@dataclasses.dataclass(frozen=True, eq=False)
class Literal(Expression):
    """A safely rendered SoQL literal value."""

    value: LiteralValue

    def _render(self) -> str:
        return _render_literal(self.value)


@dataclasses.dataclass(frozen=True, eq=False)
class Function(Expression):
    """A SoQL function call."""

    name: str
    args: tuple[Expression, ...]

    def _render(self) -> str:
        rendered_args = ", ".join(arg.render() for arg in self.args)
        return f"{self.name}({rendered_args})"


@dataclasses.dataclass(frozen=True, eq=False)
class BinaryExpression(Expression):
    """A binary SoQL expression."""

    left: Expression
    operator: str
    right: Expression

    def _render(self) -> str:
        return f"({self.left.render()} {self.operator} {self.right.render()})"


@dataclasses.dataclass(frozen=True, eq=False)
class UnaryExpression(Expression):
    """A unary SoQL expression."""

    operator: str
    expression: Expression

    def _render(self) -> str:
        return f"({self.operator} {self.expression.render()})"


@dataclasses.dataclass(frozen=True, eq=False)
class PostfixExpression(Expression):
    """A postfix SoQL expression such as IS NULL."""

    expression: Expression
    operator: str

    def _render(self) -> str:
        return f"({self.expression.render()} {self.operator})"


@dataclasses.dataclass(frozen=True, eq=False)
class InExpression(Expression):
    """An IN or NOT IN SoQL expression."""

    expression: Expression
    values: tuple[Expression, ...]
    negated: bool

    def _render(self) -> str:
        operator = "NOT IN" if self.negated else "IN"
        rendered_values = ", ".join(value.render() for value in self.values)
        return f"({self.expression.render()} {operator} ({rendered_values}))"


@dataclasses.dataclass(frozen=True, eq=False)
class BetweenExpression(Expression):
    """A BETWEEN or NOT BETWEEN SoQL expression."""

    expression: Expression
    lower: Expression
    upper: Expression
    negated: bool

    def _render(self) -> str:
        operator = "NOT BETWEEN" if self.negated else "BETWEEN"
        return (
            f"({self.expression.render()} {operator} "
            f"{self.lower.render()} AND {self.upper.render()})"
        )


@dataclasses.dataclass(frozen=True, eq=False)
class AliasedExpression(Expression):
    """A SELECT expression with an alias."""

    expression: Expression
    alias: str

    def _render(self) -> str:
        return f"{self.expression.render()} AS {_quote_identifier(self.alias)}"


@dataclasses.dataclass(frozen=True, eq=False)
class OrderExpression(Expression):
    """An ORDER BY expression."""

    expression: Expression
    direction: OrderDirection

    def _render(self) -> str:
        return f"{self.expression.render()} {self.direction}"


@dataclasses.dataclass(frozen=True, eq=False)
class RawExpression(Expression):
    """An explicitly raw SoQL fragment with safely rendered placeholders."""

    fragment: str
    params: tuple[LiteralValue, ...] = ()

    def _render(self) -> str:
        return _render_raw_fragment(self.fragment, self.params)


@dataclasses.dataclass(frozen=True)
class Query:
    """Immutable fluent SoQL query builder."""

    select_expressions: tuple[Expression, ...] = ()
    where_expressions: tuple[Expression, ...] = ()
    group_expressions: tuple[Expression, ...] = ()
    having_expressions: tuple[Expression, ...] = ()
    order_expressions: tuple[Expression, ...] = ()
    limit_value: int | None = None
    offset_value: int | None = None

    def select(self, *expressions: object) -> Self:
        """Return a query with additional SELECT expressions."""
        return dataclasses.replace(
            self,
            select_expressions=self.select_expressions
            + tuple(_as_expression(expression) for expression in expressions),
        )

    def where(self, *expressions: object) -> Self:
        """Return a query with additional WHERE expressions joined by AND."""
        return dataclasses.replace(
            self,
            where_expressions=self.where_expressions
            + tuple(_as_expression(expression) for expression in expressions),
        )

    def raw_where(self, fragment: str, *params: LiteralValue) -> Self:
        """Return a query with a raw WHERE fragment."""
        return self.where(RawExpression(fragment, params))

    def group_by(self, *expressions: object) -> Self:
        """Return a query with additional GROUP BY expressions."""
        return dataclasses.replace(
            self,
            group_expressions=self.group_expressions
            + tuple(_as_expression(expression) for expression in expressions),
        )

    def having(self, *expressions: object) -> Self:
        """Return a query with additional HAVING expressions joined by AND."""
        return dataclasses.replace(
            self,
            having_expressions=self.having_expressions
            + tuple(_as_expression(expression) for expression in expressions),
        )

    def order_by(self, *expressions: object) -> Self:
        """Return a query with additional ORDER BY expressions."""
        return dataclasses.replace(
            self,
            order_expressions=self.order_expressions
            + tuple(_as_order_expression(expression) for expression in expressions),
        )

    def limit(self, value: int) -> Self:
        """Return a query with a LIMIT value."""
        return dataclasses.replace(self, limit_value=_non_negative_int(value, "limit"))

    def offset(self, value: int) -> Self:
        """Return a query with an OFFSET value."""
        return dataclasses.replace(self, offset_value=_non_negative_int(value, "offset"))

    def to_soql(self) -> str:
        """Render this query as a full SoQL statement."""
        clauses = [f"SELECT {self._render_select_clause()}"]
        if self.where_expressions:
            clauses.append(f"WHERE {self._render_joined(self.where_expressions, 'AND')}")
        if self.group_expressions:
            clauses.append(f"GROUP BY {self._render_list(self.group_expressions)}")
        if self.having_expressions:
            clauses.append(f"HAVING {self._render_joined(self.having_expressions, 'AND')}")
        if self.order_expressions:
            clauses.append(f"ORDER BY {self._render_list(self.order_expressions)}")
        if self.limit_value is not None:
            clauses.append(f"LIMIT {self.limit_value}")
        if self.offset_value is not None:
            clauses.append(f"OFFSET {self.offset_value}")
        return " ".join(clauses)

    def to_params(self) -> dict[str, SoQLParamValue]:
        """Render this query as individual SODA query parameters."""
        params: dict[str, SoQLParamValue] = {}
        if self.select_expressions:
            params["$select"] = self._render_select_clause()
        if self.where_expressions:
            params["$where"] = self._render_joined(self.where_expressions, "AND")
        if self.group_expressions:
            params["$group"] = self._render_list(self.group_expressions)
        if self.having_expressions:
            params["$having"] = self._render_joined(self.having_expressions, "AND")
        if self.order_expressions:
            params["$order"] = self._render_list(self.order_expressions)
        if self.limit_value is not None:
            params["$limit"] = self.limit_value
        if self.offset_value is not None:
            params["$offset"] = self.offset_value
        return params

    def to_url(self, domain: str, dataset_id: str) -> str:
        """Render this query as a v2.1 resource URL for debugging."""
        normalized_domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        query_string = urlencode(self.to_params())
        url = f"https://{normalized_domain}/resource/{dataset_id}.json"
        if query_string:
            return f"{url}?{query_string}"
        return url

    def explain(self) -> str:
        """Return a readable description of this query."""
        lines = ["SoQL query:", f"  {self.to_soql()}", "Params:"]
        params = self.to_params()
        if params:
            lines.extend(f"  {key}: {value}" for key, value in params.items())
        else:
            lines.append("  <none>")
        warnings = self._warnings()
        if warnings:
            lines.append("Warnings:")
            lines.extend(f"  {warning}" for warning in warnings)
        return "\n".join(lines)

    def _render_select_clause(self) -> str:
        if not self.select_expressions:
            return "*"
        return self._render_list(self.select_expressions)

    def _render_list(self, expressions: Sequence[Expression]) -> str:
        return ", ".join(expression.render() for expression in expressions)

    def _render_joined(self, expressions: Sequence[Expression], operator: str) -> str:
        if len(expressions) == 1:
            return expressions[0].render()
        return f" {operator} ".join(expression.render() for expression in expressions)

    def _warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.limit_value is None:
            warnings.append("Query has no LIMIT clause")
        if _contains_raw_expression((*self.where_expressions, *self.having_expressions)):
            warnings.append("Query contains raw SoQL fragments")
        return warnings


def col(name: str) -> Column:
    """Return a column expression."""
    return Column(name)


def count(expression: object = RawExpression("*")) -> Function:
    """Return a count aggregate expression."""
    return _function("count", expression)


def sum_(expression: object) -> Function:
    """Return a sum aggregate expression."""
    return _function("sum", expression)


def avg(expression: object) -> Function:
    """Return an average aggregate expression."""
    return _function("avg", expression)


def min_(expression: object) -> Function:
    """Return a minimum aggregate expression."""
    return _function("min", expression)


def max_(expression: object) -> Function:
    """Return a maximum aggregate expression."""
    return _function("max", expression)


def upper(expression: object) -> Function:
    """Return an uppercase string expression."""
    return _function("upper", expression)


def lower(expression: object) -> Function:
    """Return a lowercase string expression."""
    return _function("lower", expression)


def starts_with(expression: object, prefix: object) -> Function:
    """Return a prefix-match string expression."""
    return _function("starts_with", expression, prefix)


def date_trunc_y(expression: object) -> Function:
    """Return a year-truncated date expression."""
    return _function("date_trunc_y", expression)


def date_trunc_ym(expression: object) -> Function:
    """Return a year-month-truncated date expression."""
    return _function("date_trunc_ym", expression)


def date_trunc_ymd(expression: object) -> Function:
    """Return a year-month-day-truncated date expression."""
    return _function("date_trunc_ymd", expression)


def within_circle(
    location: object, latitude: float, longitude: float, radius_meters: float
) -> Function:
    """Return a circular geospatial predicate."""
    return _function("within_circle", location, latitude, longitude, radius_meters)


def within_box(
    location: object,
    northwest_latitude: float,
    northwest_longitude: float,
    southeast_latitude: float,
    southeast_longitude: float,
) -> Function:
    """Return a bounding-box geospatial predicate."""
    return _function(
        "within_box",
        location,
        northwest_latitude,
        northwest_longitude,
        southeast_latitude,
        southeast_longitude,
    )


def distance_in_meters(first_point: object, second_point: object) -> Function:
    """Return a point distance geospatial expression."""
    return _function("distance_in_meters", first_point, second_point)


def raw(fragment: str, *params: LiteralValue) -> RawExpression:
    """Return a raw expression fragment."""
    return RawExpression(fragment, params)


def _function(name: str, *args: object) -> Function:
    return Function(name, tuple(_as_expression(arg) for arg in args))


def _as_expression(value: object) -> Expression:
    if isinstance(value, Expression):
        return value
    if isinstance(value, str | int | float | bool | dt.datetime | dt.date):
        return Literal(value)
    if value is None:
        msg = "None cannot be rendered as a literal; use is_null() or is_not_null()"
        raise TypeError(msg)
    msg = f"Unsupported SoQL expression value: {type(value).__name__}"
    raise TypeError(msg)


def _as_order_expression(value: object) -> Expression:
    expression = _as_expression(value)
    if isinstance(expression, OrderExpression):
        return expression
    return expression.asc()


def _quote_identifier(identifier: str) -> str:
    if not identifier:
        msg = "SoQL identifiers cannot be empty"
        raise ValueError(msg)
    if "`" in identifier or "\x00" in identifier:
        msg = "SoQL identifiers cannot contain backticks or NUL bytes"
        raise ValueError(msg)
    return f"`{identifier}`"


def _render_literal(value: LiteralValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = "SoQL numeric literals must be finite"
            raise ValueError(msg)
        return str(value)
    if isinstance(value, dt.datetime):
        return _quote_string(value.isoformat())
    if isinstance(value, dt.date):
        return _quote_string(value.isoformat())
    return _quote_string(value)


def _quote_string(value: str) -> str:
    if "\x00" in value:
        msg = "SoQL string literals cannot contain NUL bytes"
        raise ValueError(msg)
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _render_raw_fragment(fragment: str, params: tuple[LiteralValue, ...]) -> str:
    parts = fragment.split("?")
    expected_param_count = len(parts) - 1
    if expected_param_count != len(params):
        msg = f"Raw fragment expects {expected_param_count} parameter(s), got {len(params)}"
        raise ValueError(msg)

    rendered = [parts[0]]
    for param, part in zip(params, parts[1:], strict=True):
        rendered.append(_render_literal(param))
        rendered.append(part)
    return "".join(rendered)


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or value < 0:
        msg = f"{name} must be a non-negative integer"
        raise ValueError(msg)
    return value


def _contains_raw_expression(expressions: Iterable[Expression]) -> bool:
    return any(_is_raw_expression(expression) for expression in expressions)


def _is_raw_expression(expression: Expression) -> bool:
    result = False
    if isinstance(expression, RawExpression):
        result = True
    elif isinstance(expression, BinaryExpression):
        result = _is_raw_expression(expression.left) or _is_raw_expression(expression.right)
    elif isinstance(expression, UnaryExpression | PostfixExpression):
        result = _is_raw_expression(expression.expression)
    elif isinstance(expression, InExpression):
        result = _is_raw_expression(expression.expression) or any(
            _is_raw_expression(value) for value in expression.values
        )
    elif isinstance(expression, BetweenExpression):
        result = any(
            _is_raw_expression(value)
            for value in (expression.expression, expression.lower, expression.upper)
        )
    elif isinstance(expression, AliasedExpression | OrderExpression):
        result = _is_raw_expression(expression.expression)
    elif isinstance(expression, Function):
        result = any(_is_raw_expression(arg) for arg in expression.args)
    return result


__all__ = [
    "AliasedExpression",
    "BinaryExpression",
    "Column",
    "Expression",
    "Function",
    "OrderExpression",
    "Query",
    "RawExpression",
    "avg",
    "col",
    "count",
    "date_trunc_y",
    "date_trunc_ym",
    "date_trunc_ymd",
    "distance_in_meters",
    "lower",
    "max_",
    "min_",
    "raw",
    "starts_with",
    "sum_",
    "upper",
    "within_box",
    "within_circle",
]
