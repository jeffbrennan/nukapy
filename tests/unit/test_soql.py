"""Unit tests for the SoQL query builder."""

import datetime as dt
import math

import pytest

from nukapy.soql import (
    Query,
    avg,
    col,
    count,
    date_trunc_ymd,
    distance_in_meters,
    lower,
    max_,
    raw,
    starts_with,
    sum_,
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
