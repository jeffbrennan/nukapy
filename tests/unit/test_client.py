import pytest

from nukapy import Socrata

ROW_LIMIT = 5


@pytest.mark.vcr
def test_get_replays_nyc_311_rows() -> None:
    rows = Socrata("data.cityofnewyork.us").get("erm2-nwe9", limit=ROW_LIMIT)

    assert len(rows) == ROW_LIMIT
    assert all(isinstance(row, dict) for row in rows)
