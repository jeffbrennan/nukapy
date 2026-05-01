"""Typed helpers for building Socrata SoQL read queries."""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from enum import StrEnum
from typing import TYPE_CHECKING, Self, TypeAlias, TypeVar, cast
from urllib.parse import urlencode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

SoQLParamValue = str | int | float
LiteralValue = str | int | float | bool | dt.date | dt.datetime
_Token = TypeVar("_Token", bound=StrEnum)


class _BinaryOperator(StrEnum):
    """Supported binary SoQL operators."""

    EQUAL = "="
    NOT_EQUAL = "!="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    AND = "AND"
    OR = "OR"


class _UnaryOperator(StrEnum):
    """Supported unary SoQL operators."""

    NOT = "NOT"


class _PostfixOperator(StrEnum):
    """Supported postfix SoQL operators."""

    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"


class _OrderDirection(StrEnum):
    """Supported SoQL order directions."""

    ASC = "ASC"
    DESC = "DESC"


OrderDirection: TypeAlias = str | _OrderDirection


class _FunctionName(StrEnum):
    """Built-in SoQL function names exposed by helper functions."""

    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    UPPER = "upper"
    LOWER = "lower"
    STARTS_WITH = "starts_with"
    DATE_TRUNC_Y = "date_trunc_y"
    DATE_TRUNC_YM = "date_trunc_ym"
    DATE_TRUNC_YMD = "date_trunc_ymd"
    WITHIN_CIRCLE = "within_circle"
    WITHIN_BOX = "within_box"
    DISTANCE_IN_METERS = "distance_in_meters"


class Expression:
    """Base class for renderable SoQL expressions."""

    __hash__ = object.__hash__

    def as_(self, alias: str) -> AliasedExpression:
        """Return this expression aliased for a SELECT clause."""
        return AliasedExpression(self, alias)

    def asc(self) -> OrderExpression:
        """Return this expression as an ascending ORDER BY term."""
        return OrderExpression(self, _OrderDirection.ASC)

    def desc(self) -> OrderExpression:
        """Return this expression as a descending ORDER BY term."""
        return OrderExpression(self, _OrderDirection.DESC)

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
        return PostfixExpression(self, _PostfixOperator.IS_NULL)

    def is_not_null(self) -> Expression:
        """Return an IS NOT NULL expression."""
        return PostfixExpression(self, _PostfixOperator.IS_NOT_NULL)

    def render(self) -> str:
        """Render this expression as SoQL."""
        return self._render()

    def __eq__(self, other: object) -> BinaryExpression:  # type: ignore[override]
        """Return a SoQL equality comparison."""
        return BinaryExpression(self, _BinaryOperator.EQUAL, _as_expression(other))

    def __ne__(self, other: object) -> BinaryExpression:  # type: ignore[override]
        """Return a SoQL inequality comparison."""
        return BinaryExpression(self, _BinaryOperator.NOT_EQUAL, _as_expression(other))

    def __gt__(self, other: object) -> BinaryExpression:
        """Return a SoQL greater-than comparison."""
        return BinaryExpression(self, _BinaryOperator.GREATER_THAN, _as_expression(other))

    def __ge__(self, other: object) -> BinaryExpression:
        """Return a SoQL greater-than-or-equal comparison."""
        return BinaryExpression(self, _BinaryOperator.GREATER_THAN_OR_EQUAL, _as_expression(other))

    def __lt__(self, other: object) -> BinaryExpression:
        """Return a SoQL less-than comparison."""
        return BinaryExpression(self, _BinaryOperator.LESS_THAN, _as_expression(other))

    def __le__(self, other: object) -> BinaryExpression:
        """Return a SoQL less-than-or-equal comparison."""
        return BinaryExpression(self, _BinaryOperator.LESS_THAN_OR_EQUAL, _as_expression(other))

    def __and__(self, other: object) -> BinaryExpression:
        """Return a SoQL AND expression."""
        return BinaryExpression(self, _BinaryOperator.AND, _as_expression(other))

    def __or__(self, other: object) -> BinaryExpression:
        """Return a SoQL OR expression."""
        return BinaryExpression(self, _BinaryOperator.OR, _as_expression(other))

    def __invert__(self) -> UnaryExpression:
        """Return a SoQL NOT expression."""
        return UnaryExpression(_UnaryOperator.NOT, self)

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

    def __post_init__(self) -> None:
        """Validate the function token before rendering."""
        _validate_function_name(self.name)

    def _render(self) -> str:
        rendered_args = ", ".join(arg.render() for arg in self.args)
        return f"{self.name}({rendered_args})"


@dataclasses.dataclass(frozen=True, eq=False)
class BinaryExpression(Expression):
    """A binary SoQL expression."""

    left: Expression
    operator: str | _BinaryOperator
    right: Expression

    def __post_init__(self) -> None:
        """Validate the operator token before rendering."""
        object.__setattr__(
            self, "operator", _coerce_token(self.operator, _BinaryOperator, "binary operator")
        )

    def _render(self) -> str:
        return f"({self.left.render()} {self.operator} {self.right.render()})"


@dataclasses.dataclass(frozen=True, eq=False)
class UnaryExpression(Expression):
    """A unary SoQL expression."""

    operator: str | _UnaryOperator
    expression: Expression

    def __post_init__(self) -> None:
        """Validate the operator token before rendering."""
        object.__setattr__(
            self, "operator", _coerce_token(self.operator, _UnaryOperator, "unary operator")
        )

    def _render(self) -> str:
        return f"({self.operator} {self.expression.render()})"


@dataclasses.dataclass(frozen=True, eq=False)
class PostfixExpression(Expression):
    """A postfix SoQL expression such as IS NULL."""

    expression: Expression
    operator: str | _PostfixOperator

    def __post_init__(self) -> None:
        """Validate the operator token before rendering."""
        object.__setattr__(
            self, "operator", _coerce_token(self.operator, _PostfixOperator, "postfix operator")
        )

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

    def __post_init__(self) -> None:
        """Validate the direction token before rendering."""
        object.__setattr__(
            self, "direction", _coerce_token(self.direction, _OrderDirection, "order direction")
        )

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
class _QueryClause:
    """Rendered query clause metadata."""

    keyword: str
    param_name: str | None
    value: SoQLParamValue
    include_param: bool = True


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
        return self._append_expressions("select_expressions", expressions, _as_expression)

    def where(self, *expressions: object) -> Self:
        """Return a query with additional WHERE expressions joined by AND."""
        return self._append_expressions("where_expressions", expressions, _as_expression)

    def raw_where(self, fragment: str, *params: LiteralValue) -> Self:
        """Return a query with a raw WHERE fragment."""
        return self.where(RawExpression(fragment, params))

    def group_by(self, *expressions: object) -> Self:
        """Return a query with additional GROUP BY expressions."""
        return self._append_expressions("group_expressions", expressions, _as_expression)

    def having(self, *expressions: object) -> Self:
        """Return a query with additional HAVING expressions joined by AND."""
        return self._append_expressions("having_expressions", expressions, _as_expression)

    def order_by(self, *expressions: object) -> Self:
        """Return a query with additional ORDER BY expressions."""
        return self._append_expressions("order_expressions", expressions, _as_order_expression)

    def limit(self, value: int) -> Self:
        """Return a query with a LIMIT value."""
        return dataclasses.replace(self, limit_value=_non_negative_int(value, "limit"))

    def offset(self, value: int) -> Self:
        """Return a query with an OFFSET value."""
        return dataclasses.replace(self, offset_value=_non_negative_int(value, "offset"))

    def to_soql(self) -> str:
        """Render this query as a full SoQL statement."""
        return " ".join(f"{clause.keyword} {clause.value}" for clause in self._clauses())

    def to_params(self) -> dict[str, SoQLParamValue]:
        """Render this query as individual SODA query parameters."""
        return {
            clause.param_name: clause.value
            for clause in self._clauses()
            if clause.param_name is not None and clause.include_param
        }

    def to_url(self, domain: str, dataset_id: str) -> str:
        """Render this query as a v2.1 resource URL for debugging."""
        normalized_domain = domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        query_string = urlencode(self.to_params())
        url = f"https://{normalized_domain}/resource/{dataset_id}.json"
        return f"{url}?{query_string}" if query_string else url

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
        return f" {operator} ".join(expression.render() for expression in expressions)

    def _append_expressions(
        self,
        field_name: str,
        expressions: tuple[object, ...],
        converter: Callable[[object], Expression],
    ) -> Self:
        current_expressions = cast("tuple[Expression, ...]", getattr(self, field_name))
        next_expressions = current_expressions + tuple(
            converter(expression) for expression in expressions
        )
        return dataclasses.replace(self, **{field_name: next_expressions})

    def _clauses(self) -> list[_QueryClause]:
        clauses = [
            _QueryClause(
                "SELECT",
                "$select",
                self._render_select_clause(),
                include_param=bool(self.select_expressions),
            )
        ]

        expression_clause_specs = (
            ("WHERE", "$where", self.where_expressions, "AND"),
            ("GROUP BY", "$group", self.group_expressions, None),
            ("HAVING", "$having", self.having_expressions, "AND"),
            ("ORDER BY", "$order", self.order_expressions, None),
        )
        for keyword, param_name, expressions, join_operator in expression_clause_specs:
            if not expressions:
                continue
            value = (
                self._render_list(expressions)
                if join_operator is None
                else self._render_joined(expressions, join_operator)
            )
            clauses.append(_QueryClause(keyword, param_name, value))

        for keyword, param_name, value in (
            ("LIMIT", "$limit", self.limit_value),
            ("OFFSET", "$offset", self.offset_value),
        ):
            if value is not None:
                clauses.append(_QueryClause(keyword, param_name, value))
        return clauses

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
    return _function(_FunctionName.COUNT, expression)


def sum_(expression: object) -> Function:
    """Return a sum aggregate expression."""
    return _function(_FunctionName.SUM, expression)


def avg(expression: object) -> Function:
    """Return an average aggregate expression."""
    return _function(_FunctionName.AVG, expression)


def min_(expression: object) -> Function:
    """Return a minimum aggregate expression."""
    return _function(_FunctionName.MIN, expression)


def max_(expression: object) -> Function:
    """Return a maximum aggregate expression."""
    return _function(_FunctionName.MAX, expression)


def upper(expression: object) -> Function:
    """Return an uppercase string expression."""
    return _function(_FunctionName.UPPER, expression)


def lower(expression: object) -> Function:
    """Return a lowercase string expression."""
    return _function(_FunctionName.LOWER, expression)


def starts_with(expression: object, prefix: object) -> Function:
    """Return a prefix-match string expression."""
    return _function(_FunctionName.STARTS_WITH, expression, prefix)


def date_trunc_y(expression: object) -> Function:
    """Return a year-truncated date expression."""
    return _function(_FunctionName.DATE_TRUNC_Y, expression)


def date_trunc_ym(expression: object) -> Function:
    """Return a year-month-truncated date expression."""
    return _function(_FunctionName.DATE_TRUNC_YM, expression)


def date_trunc_ymd(expression: object) -> Function:
    """Return a year-month-day-truncated date expression."""
    return _function(_FunctionName.DATE_TRUNC_YMD, expression)


def within_circle(
    location: object, latitude: float, longitude: float, radius_meters: float
) -> Function:
    """Return a circular geospatial predicate."""
    return _function(_FunctionName.WITHIN_CIRCLE, location, latitude, longitude, radius_meters)


def within_box(
    location: object,
    northwest_latitude: float,
    northwest_longitude: float,
    southeast_latitude: float,
    southeast_longitude: float,
) -> Function:
    """Return a bounding-box geospatial predicate."""
    return _function(
        _FunctionName.WITHIN_BOX,
        location,
        northwest_latitude,
        northwest_longitude,
        southeast_latitude,
        southeast_longitude,
    )


def distance_in_meters(first_point: object, second_point: object) -> Function:
    """Return a point distance geospatial expression."""
    return _function(_FunctionName.DISTANCE_IN_METERS, first_point, second_point)


def raw(fragment: str, *params: LiteralValue) -> RawExpression:
    """Return a raw expression fragment."""
    return RawExpression(fragment, params)


def _function(name: str | _FunctionName, *args: object) -> Function:
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


def _validate_function_name(name: str) -> None:
    if not name:
        msg = "SoQL function names cannot be empty"
        raise ValueError(msg)
    first = name[0]
    if not (first.isascii() and (first.isalpha() or first == "_")):
        msg = "SoQL function names must start with an ASCII letter or underscore"
        raise ValueError(msg)
    if not all(
        character.isascii() and (character.isalnum() or character == "_") for character in name
    ):
        msg = "SoQL function names can only contain ASCII letters, numbers, and underscores"
        raise ValueError(msg)


def _coerce_token(value: str, enum_type: type[_Token], name: str) -> _Token:
    try:
        return enum_type(value)
    except ValueError as error:
        allowed = ", ".join(sorted(member.value for member in enum_type))
        msg = f"Invalid SoQL {name}: {value!r}; expected one of {allowed}"
        raise ValueError(msg) from error


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
    if isinstance(expression, RawExpression):
        return True

    child_expressions: tuple[Expression, ...] = ()
    if isinstance(expression, BinaryExpression):
        child_expressions = (expression.left, expression.right)
    elif isinstance(
        expression, UnaryExpression | PostfixExpression | AliasedExpression | OrderExpression
    ):
        child_expressions = (expression.expression,)
    elif isinstance(expression, InExpression):
        child_expressions = (expression.expression, *expression.values)
    elif isinstance(expression, BetweenExpression):
        child_expressions = (expression.expression, expression.lower, expression.upper)
    elif isinstance(expression, Function):
        child_expressions = expression.args
    return any(_is_raw_expression(child_expression) for child_expression in child_expressions)


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
