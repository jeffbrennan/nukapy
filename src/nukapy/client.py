"""Minimal sync Socrata client."""

from contextlib import suppress
from types import TracebackType
from typing import Any, Self, cast

from nukapy._internal.auth import get_app_token
from nukapy.transport import Request, Transport


class Socrata:
    """Small sync client for the Socrata Open Data API."""

    def __init__(self, domain: str, app_token: str | None = None) -> None:
        """Create a client for a Socrata domain."""
        self.domain = (
            domain.removeprefix("https://").removeprefix("http://").rstrip("/")
        )
        self.app_token = get_app_token() if app_token is None else app_token or None
        self._transport = Transport(app_token=self.app_token)

    def get(self, dataset_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Fetch rows from a Socrata dataset."""
        params: dict[str, int] = {}
        if limit is not None:
            params["$limit"] = limit

        response = self._transport.request(
            Request(
                method="GET",
                url=f"https://{self.domain}/resource/{dataset_id}.json",
                params=params,
            )
        )
        return cast("list[dict[str, Any]]", response.json())

    def close(self) -> None:
        """Close the underlying transport."""
        self._transport.close()

    def __enter__(self) -> Self:
        """Enter the client context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the client context."""
        self.close()

    def __del__(self) -> None:
        """Best-effort cleanup for abandoned clients."""
        with suppress(Exception):
            self.close()
