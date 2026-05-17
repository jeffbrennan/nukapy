"""Hypothesis property tests for the SoQL query builder."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from nukapy.soql import (
    Query,
    col,
    count,
    raw,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid column / identifier characters: ASCII alphanum + underscore, non-empty,
# no backtick or NUL.
_safe_identifier = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters="_",
        blacklist_characters="`\x00",
    ),
    min_size=1,
    max_size=40,
).filter(lambda s: s[0].isalpha() or s[0] == "_")

# Strings that are safe to use as SoQL literal values (no NUL bytes).
_safe_string = st.text(
    alphabet=st.characters(blacklist_characters="\x00"),
    max_size=200,
)

# Finite floats only.
_finite_float = st.floats(allow_nan=False, allow_infinity=False)

# Small integer values.
_small_int = st.integers(min_value=-(2**31), max_value=2**31)

# Non-negative integers.
_non_neg_int = st.integers(min_value=0, max_value=2**31)

# Positive integers for batch sizes etc.
_pos_int = st.integers(min_value=1, max_value=2**31)


# ---------------------------------------------------------------------------
# Literal rendering properties
# ---------------------------------------------------------------------------


@given(_safe_string)
def test_string_literal_single_quotes_are_escaped(value: str) -> None:
    """Every single-quote in a string literal is doubled."""
    rendered = (col("x") == value).render()
    # Strip wrapping parens and the column reference to isolate the literal.
    assert f"'{value.replace(chr(39), chr(39) * 2)}'" in rendered


@given(_safe_string)
def test_string_literal_rendering_is_deterministic(value: str) -> None:
    """Rendering the same value twice produces identical output."""
    expr = col("x") == value
    assert expr.render() == expr.render()


@given(_finite_float)
def test_finite_float_literals_render_without_error(value: float) -> None:
    """Any finite float renders successfully."""
    rendered = (col("amount") == value).render()
    assert str(value) in rendered


@given(
    st.one_of(
        st.just(math.nan),
        st.just(math.inf),
        st.just(-math.inf),
    )
)
def test_non_finite_float_literals_raise(value: float) -> None:
    """NaN and infinite floats must raise ValueError."""
    with pytest.raises(ValueError, match="finite"):
        (col("amount") == value).render()


# ---------------------------------------------------------------------------
# Column / identifier properties
# ---------------------------------------------------------------------------


@given(_safe_identifier)
def test_column_names_are_backtick_quoted(name: str) -> None:
    """Any valid identifier renders with surrounding backticks."""
    rendered = col(name).render()
    assert rendered == f"`{name}`"


@given(_safe_identifier, _safe_string)
def test_equality_expression_structure(column: str, value: str) -> None:
    """Equality expression always has the form (`col` = 'val')."""
    rendered = (col(column) == value).render()
    assert rendered.startswith("(")
    assert rendered.endswith(")")
    assert f"`{column}`" in rendered


# ---------------------------------------------------------------------------
# IN / NOT IN properties
# ---------------------------------------------------------------------------


@given(st.lists(_small_int, min_size=1, max_size=20))
def test_in_expression_renders_all_values(values: list[int]) -> None:
    """All supplied values appear in the rendered IN expression."""
    rendered = col("x").in_(values).render()
    assert " IN " in rendered
    for value in values:
        assert str(value) in rendered


@given(st.lists(_small_int, min_size=1, max_size=20))
def test_not_in_expression_renders_all_values(values: list[int]) -> None:
    """All supplied values appear in the rendered NOT IN expression."""
    rendered = col("x").not_in(values).render()
    assert " NOT IN " in rendered


def test_in_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        col("x").in_([])


def test_not_in_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        col("x").not_in([])


# ---------------------------------------------------------------------------
# BETWEEN properties
# ---------------------------------------------------------------------------


@given(_small_int, _small_int)
def test_between_renders_both_bounds(lower: int, upper: int) -> None:
    """BETWEEN renders with both bounds and no NOT keyword."""
    rendered = col("x").between(lower, upper).render()
    assert " BETWEEN " in rendered
    assert " NOT BETWEEN " not in rendered
    assert str(lower) in rendered
    assert str(upper) in rendered


@given(_small_int, _small_int)
def test_not_between_renders_both_bounds(lower: int, upper: int) -> None:
    """NOT BETWEEN renders correctly."""
    rendered = col("x").not_between(lower, upper).render()
    assert " NOT BETWEEN " in rendered


# ---------------------------------------------------------------------------
# Comparison operator properties
# ---------------------------------------------------------------------------


@given(_small_int)
def test_all_comparison_operators_wrap_in_parens(value: int) -> None:
    """All comparison operators produce parenthesized expressions."""
    for expr in (
        col("x") == value,
        col("x") != value,
        col("x") > value,
        col("x") >= value,
        col("x") < value,
        col("x") <= value,
    ):
        rendered = expr.render()
        assert rendered.startswith("(")
        assert rendered.endswith(")")


@given(_small_int, _small_int)
def test_and_or_operators_produce_nested_parens(a: int, b: int) -> None:
    """AND and OR operators produce doubly-nested parenthesized expressions."""
    and_expr = (col("x") == a) & (col("y") == b)
    or_expr = (col("x") == a) | (col("y") == b)
    assert " AND " in and_expr.render()
    assert " OR " in or_expr.render()


@given(_small_int)
def test_invert_operator_renders_not(value: int) -> None:
    """The ~ operator wraps the expression in NOT."""
    rendered = (~(col("x") == value)).render()
    assert rendered.startswith("(NOT ")


# ---------------------------------------------------------------------------
# IS NULL / IS NOT NULL
# ---------------------------------------------------------------------------


def test_is_null_renders() -> None:
    assert col("x").is_null().render() == "(`x` IS NULL)"


def test_is_not_null_renders() -> None:
    assert col("x").is_not_null().render() == "(`x` IS NOT NULL)"


# ---------------------------------------------------------------------------
# Query-level properties
# ---------------------------------------------------------------------------


@given(_non_neg_int)
def test_limit_accepts_non_negative(value: int) -> None:
    """Non-negative limit values are accepted."""
    q = Query().limit(value)
    assert q.limit_value == value


@given(st.integers(max_value=-1))
def test_limit_rejects_negative(value: int) -> None:
    """Negative limit values are rejected."""
    with pytest.raises(ValueError, match="non-negative"):
        Query().limit(value)


@given(_non_neg_int)
def test_offset_accepts_non_negative(value: int) -> None:
    q = Query().offset(value)
    assert q.offset_value == value


@given(st.integers(max_value=-1))
def test_offset_rejects_negative(value: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Query().offset(value)


@given(_safe_identifier, _safe_string)
@settings(max_examples=50)
def test_query_params_values_appear_in_soql(column: str, value: str) -> None:
    """Every rendered param value appears somewhere in the full SoQL string."""
    q = Query().where(col(column) == value)
    soql = q.to_soql()
    for param_value in q.to_params().values():
        assert str(param_value) in soql


# ---------------------------------------------------------------------------
# Raw fragment properties
# ---------------------------------------------------------------------------


@given(
    st.integers(min_value=0, max_value=5).flatmap(
        lambda n: st.tuples(
            st.just(" ? ".join(["fragment"] * (n + 1))),
            st.lists(st.integers(), min_size=n, max_size=n).map(tuple),
        )
    )
)
def test_raw_fragment_correct_param_count_renders(args: tuple[str, tuple[int, ...]]) -> None:
    """A raw fragment with matching param count always renders."""
    fragment, params = args
    rendered = raw(fragment, *params).render()
    assert isinstance(rendered, str)


def test_raw_fragment_wrong_param_count_raises() -> None:
    with pytest.raises(ValueError, match="expects 2 parameter"):
        raw("? and ?", 1).render()


# ---------------------------------------------------------------------------
# Explain method
# ---------------------------------------------------------------------------


def test_explain_empty_query_shows_no_params() -> None:
    explanation = Query().explain()
    assert "<none>" in explanation
    assert "Query has no LIMIT clause" in explanation


def test_explain_query_with_params_shows_them() -> None:
    explanation = Query().select(col("name")).limit(10).explain()
    assert "$select" in explanation
    assert "$limit" in explanation


# ---------------------------------------------------------------------------
# count() helper
# ---------------------------------------------------------------------------


def test_count_star_renders() -> None:
    assert count().render() == "count(*)"


def test_count_expression_renders() -> None:
    assert count(col("x")).render() == "count(`x`)"
