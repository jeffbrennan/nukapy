import os
import sys
import time

import pytest

from nukapy import Socrata
from nukapy.errors import ConnectError
from nukapy.errors import TimeoutError as NukapyTimeoutError

ROW_LIMIT = 5
DEFAULT_TIMEOUT = 5.0
TIMING_ENV_VAR = "NUKAPY_DEBUG_INTEGRATION_TIMING"
TIMEOUT_ENV_VAR = "NUKAPY_INTEGRATION_TIMEOUT"


@pytest.mark.integration
def test_get_fetches_live_nyc_311_rows() -> None:
    app_token = os.environ.get("SOCRATA_APP_TOKEN")
    if not app_token:
        pytest.skip("SOCRATA_APP_TOKEN not set")

    timings: dict[str, float] = {}
    total_start = time.perf_counter()
    client: Socrata | None = None
    try:
        init_start = time.perf_counter()
        client = Socrata(
            "data.cityofnewyork.us",
            app_token=app_token,
            api_version="v2.1",
            timeout=float(os.environ.get(TIMEOUT_ENV_VAR, DEFAULT_TIMEOUT)),
        )
        timings["client_init"] = time.perf_counter() - init_start

        get_start = time.perf_counter()
        rows = client.get(
            "erm2-nwe9", limit=ROW_LIMIT, select="unique_key,complaint_type"
        )
        timings["get"] = time.perf_counter() - get_start
    except (NukapyTimeoutError, ConnectError) as exc:
        pytest.skip(f"Network unavailable: {exc}")
    finally:
        if client is not None:
            close_start = time.perf_counter()
            client.close()
            timings["close"] = time.perf_counter() - close_start
        timings["total"] = time.perf_counter() - total_start
        _emit_timing(timings)

    assert len(rows) == ROW_LIMIT
    assert all(isinstance(row, dict) for row in rows)


def _emit_timing(timings: dict[str, float]) -> None:
    if not os.environ.get(TIMING_ENV_VAR):
        return

    parts = " ".join(f"{name}={duration:.3f}s" for name, duration in timings.items())
    sys.stderr.write(f"nukapy NYC 311 integration timing: {parts}\n")
