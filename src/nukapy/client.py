"""Minimal sync Socrata client."""

from typing import Any, cast

import httpx

from nukapy._internal.auth import get_app_token


class Socrata:
    """Small sync client for the Socrata Open Data API."""

    def __init__(self, domain: str, app_token: str | None = None) -> None:
        """Create a client for a Socrata domain."""
        self.domain = (
            domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        )
        self.app_token = app_token or get_app_token()

    def get(self, dataset_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Fetch rows from a Socrata dataset."""
        params: dict[str, int] = {}
        if limit is not None:
            params["$limit"] = limit

        headers: dict[str, str] = {}
        if self.app_token is not None:
            headers["X-App-Token"] = self.app_token

        response = httpx.get(
            f"https://{self.domain}/resource/{dataset_id}.json",
            headers=headers,
            params=params,
            timeout=30.0,
        )
        response.raise_for_status()
        return cast("list[dict[str, Any]]", response.json())
