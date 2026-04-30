import os

import pytest

from nukapy import Socrata
from nukapy.errors import ConnectError
from nukapy.errors import TimeoutError as NukapyTimeoutError

ROW_LIMIT = 5


@pytest.mark.integration
def test_get_fetches_live_nyc_311_rows() -> None:
    app_token = os.environ.get("SOCRATA_APP_TOKEN")
    if not app_token:
        pytest.skip("SOCRATA_APP_TOKEN not set")

    try:
        rows = Socrata(
            "data.cityofnewyork.us", app_token=app_token, api_version="v2.1"
        ).get("erm2-nwe9", limit=ROW_LIMIT)
    except (NukapyTimeoutError, ConnectError) as exc:
        pytest.skip(f"Network unavailable: {exc}")

    assert len(rows) == ROW_LIMIT
    assert all(isinstance(row, dict) for row in rows)
