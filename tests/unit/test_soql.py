"""Unit tests for the SoQL query builder."""

import datetime as dt
import math

import pytest

from nukapy.soql import (
    BinaryExpression,
    Expression,
    Function,
    OrderExpression,
    PostfixExpression,
    Query,
    UnaryExpression,
    avg,
    col,
    count,
    date_trunc_y,
    date_trunc_ym,
    date_trunc_ymd,
    distance_in_meters,
    lower,
    max_,
    min_,
    raw,
    starts_with,
    sum_,
    upper,
    within_box,
    within_circle,
)

HAVING_COUNT_THRESHOLD = 10
MIN_RATING = 3
BOOLEAN_TEST_THRESHOLD = 5


def test_query_renders_individual_params() -> None:
    query = (
        Query()
        .select(col("complaint_type"), count().as_("count"))
        .where((col("created_date") >= "2024-01-01T00:00:00") & (col("status") != "Closed"))
        .group_by(col("complaint_type"))
        .having(count() > HAVING_COUNT_THRESHOLD)
        .order_by(count().desc())
        .limit(100)
        .offset(20)
    )

    assert query.to_params() == {
        "$select": "`complaint_type`, count(*) AS `count`",
        "$where": "((`created_date` >= '2024-01-01T00:00:00') AND (`status` != 'Closed'))",
        "$group": "`complaint_type`",
        "$having": "(count(*) > 10)",
        "$order": "count(*) DESC",
        "$limit": 100,
        "$offset": 20,
    }


def test_query_renders_full_soql() -> None:
    query = Query().select(col("name")).where(col("rating") > MIN_RATING).order_by(col("name"))

    assert query.to_soql() == "SELECT `name` WHERE (`rating` > 3) ORDER BY `name` ASC"


def test_query_omits_default_select_param() -> None:
    query = Query().where(col("name") == "Library")

    assert query.to_soql() == "SELECT * WHERE (`name` = 'Library')"
    assert query.to_params() == {"$where": "(`name` = 'Library')"}


def test_literals_are_escaped() -> None:
    query = Query().where(
        col("name") == "Bob's Burgers",
        col("created_date") == dt.date(2024, 1, 2),
        col("active") == True,  # noqa: E712
    )

    assert query.to_params()["$where"] == (
        "(`name` = 'Bob''s Burgers') AND (`created_date` = '2024-01-02') AND (`active` = true)"
    )


def test_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        Query().select(col("bad`name")).to_params()


def test_direct_expression_constructors_accept_valid_tokens() -> None:
    assert Function("custom_function", (col("name"),)).render() == "custom_function(`name`)"
    assert BinaryExpression(col("name"), "=", col("other_name")).render() == (
        "(`name` = `other_name`)"
    )
    assert UnaryExpression("NOT", col("name").is_null()).render() == "(NOT (`name` IS NULL))"
    assert PostfixExpression(col("name"), "IS NOT NULL").render() == "(`name` IS NOT NULL)"
    assert OrderExpression(col("name"), "DESC").render() == "`name` DESC"


def test_rejects_unsafe_structural_tokens() -> None:
    with pytest.raises(ValueError, match="function names"):
        Function("count); SELECT *", ())

    with pytest.raises(ValueError, match="binary operator"):
        BinaryExpression(col("name"), "= 'Library' OR", col("name"))

    with pytest.raises(ValueError, match="unary operator"):
        UnaryExpression("NOT EXISTS", col("name"))

    with pytest.raises(ValueError, match="postfix operator"):
        PostfixExpression(col("name"), "IS NOT NULL OR")

    with pytest.raises(ValueError, match="order direction"):
        OrderExpression(col("name"), "DESC NULLS FIRST")


def test_rejects_invalid_literals() -> None:
    with pytest.raises(ValueError, match="finite"):
        Query().where(col("amount") == math.inf).to_params()

    with pytest.raises(TypeError, match="None"):
        Query().where(col("amount").__eq__(None)).to_params()


def test_raw_where_substitutes_params_safely() -> None:
    query = Query().raw_where("`name` = ? AND `amount` > ?", "Bob's", 10)

    assert query.to_params() == {"$where": "`name` = 'Bob''s' AND `amount` > 10"}


def test_raw_fragment_param_count_must_match() -> None:
    with pytest.raises(ValueError, match="expects 1"):
        Query().where(raw("`name` = ?", "first", "second")).to_params()


def test_boolean_python_operators_raise() -> None:
    with pytest.raises(TypeError, match="cannot be used as booleans"):
        bool(col("amount") > BOOLEAN_TEST_THRESHOLD)


def test_functions_render() -> None:
    query = Query().select(
        sum_(col("amount")).as_("total"),
        avg(col("amount")).as_("average"),
        max_(date_trunc_ymd(col("created_date"))).as_("latest_day"),
    )

    assert query.to_params()["$select"] == (
        "sum(`amount`) AS `total`, "
        "avg(`amount`) AS `average`, "
        "max(date_trunc_ymd(`created_date`)) AS `latest_day`"
    )


def test_string_functions_render() -> None:
    query = Query().where(starts_with(lower(col("city")), "new"))

    assert query.to_params() == {"$where": "starts_with(lower(`city`), 'new')"}


def test_geospatial_functions_render() -> None:
    query = (
        Query()
        .where(within_circle(col("location"), 41.88, -87.63, 500))
        .where(within_box(col("location"), 42.0, -88.0, 41.0, -87.0))
        .order_by(distance_in_meters(col("location"), "POINT (-87.637714 41.887275)"))
    )

    assert query.to_params() == {
        "$where": "within_circle(`location`, 41.88, -87.63, 500) AND "
        "within_box(`location`, 42.0, -88.0, 41.0, -87.0)",
        "$order": "distance_in_meters(`location`, 'POINT (-87.637714 41.887275)') ASC",
    }


def test_to_url_renders_debug_url() -> None:
    query = Query().select(col("name")).limit(1)

    assert query.to_url("https://data.example.gov/", "abcd-1234") == (
        "https://data.example.gov/resource/abcd-1234.json?%24select=%60name%60&%24limit=1"
    )


def test_explain_includes_warnings() -> None:
    explanation = Query().raw_where("`name` IS NOT NULL").explain()

    assert "Query has no LIMIT clause" in explanation
    assert "Query contains raw SoQL fragments" in explanation


def test_in_and_not_in_render() -> None:
    assert col("status").in_(["Open", "Closed"]).render() == "(`status` IN ('Open', 'Closed'))"
    assert col("status").not_in(["Open"]).render() == "(`status` NOT IN ('Open'))"


def test_between_and_not_between_render() -> None:
    assert col("amount").between(0, 100).render() == "(`amount` BETWEEN 0 AND 100)"
    assert col("amount").not_between(0, 100).render() == "(`amount` NOT BETWEEN 0 AND 100)"


def test_is_not_null_renders() -> None:
    assert col("value").is_not_null().render() == "(`value` IS NOT NULL)"


def test_lt_le_or_invert_operators() -> None:
    assert (col("x") < 5).render() == "(`x` < 5)"
    assert (col("x") <= 5).render() == "(`x` <= 5)"
    assert ((col("x") == 1) | (col("y") == 2)).render() == "((`x` = 1) OR (`y` = 2))"
    assert (~col("x").is_null()).render() == "(NOT (`x` IS NULL))"


def test_base_expression_render_raises() -> None:
    class _Bare(Expression):
        pass

    with pytest.raises(NotImplementedError, match="_Bare must implement _render"):
        _Bare().render()


def test_min_upper_date_trunc_functions_render() -> None:
    assert min_(col("price")).render() == "min(`price`)"
    assert upper(col("city")).render() == "upper(`city`)"
    assert date_trunc_y(col("created_date")).render() == "date_trunc_y(`created_date`)"
    assert date_trunc_ym(col("created_date")).render() == "date_trunc_ym(`created_date`)"


def test_as_expression_rejects_none() -> None:
    with pytest.raises(TypeError, match="None"):
        col("x").__eq__(None).render()


def test_quote_identifier_rejects_empty() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        col("").render()


def test_validate_function_name_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        Function("", ())

    with pytest.raises(ValueError, match="must start with"):
        Function("1bad", ())

    with pytest.raises(ValueError, match="only contain"):
        Function("bad name", ())


def test_quote_string_rejects_nul_bytes() -> None:
    with pytest.raises(ValueError, match="NUL"):
        (col("x") == "hello\x00world").render()


def test_is_raw_expression_detects_nested_raw() -> None:
    raw_expr = raw("? > 0", 1)
    assert (col("x") == raw_expr).render()  # BinaryExpression with raw child triggers warning
    assert Query().where(col("x") == raw_expr).explain().__contains__("raw SoQL")


def test_is_raw_expression_in_between_and_in() -> None:
    raw_expr = raw("? > 0", 1)
    assert col("x").between(raw_expr, 10).render()
    assert col("x").in_([raw_expr]).render()


def test_is_raw_expression_in_postfix_alias_order() -> None:
    raw_expr = raw("? > 0", 1)
    assert raw_expr.is_null().render()
    assert raw_expr.as_("alias").render()
    assert raw_expr.asc().render()


def test_explain_no_params_shows_none_label() -> None:
    explanation = Query().explain()
    assert "<none>" in explanation


def test_as_expression_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError, match="Unsupported SoQL expression value"):
        col("x").__eq__([1, 2, 3]).render()


def test_datetime_literal_renders() -> None:
    expr = col("created_at") == dt.datetime(2024, 6, 15, 12, 0, 0, tzinfo=dt.UTC)
    assert "2024-06-15T12:00:00" in expr.render()


def test_is_raw_expression_warns_for_in_between_function_unary() -> None:
    r = raw("? > 0", 1)

    # InExpression with raw value
    assert "raw SoQL" in Query().where(col("x").in_([r])).explain()
    # BetweenExpression with raw bound
    assert "raw SoQL" in Query().where(col("x").between(r, 10)).explain()
    # Function with raw arg
    assert "raw SoQL" in Query().where(count(r) > 0).explain()
    # UnaryExpression (NOT) wrapping raw
    assert "raw SoQL" in Query().where(~r).explain()
    # OrderExpression in having (raw not in where/having by default, but we can put raw in having)
    assert "raw SoQL" in Query().having(r.asc()).explain()
