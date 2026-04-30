import os

import pytest

from nukapy import Socrata

ROW_LIMIT = 5


@pytest.mark.integration
def test_get_fetches_live_nyc_311_rows() -> None:
    rows = Socrata(
        "data.cityofnewyork.us",
        app_token=os.environ.get("SOCRATA_APP_TOKEN"),
    ).get("erm2-nwe9", limit=ROW_LIMIT)

    assert len(rows) == ROW_LIMIT
    assert all(isinstance(row, dict) for row in rows)
