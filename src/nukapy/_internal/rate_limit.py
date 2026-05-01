"""Rate limit tracking helpers."""

import dataclasses
import datetime as dt
from collections.abc import Mapping


@dataclasses.dataclass
class RateLimitState:
    """Tracks rate-limit headers from Socrata responses."""

    limit: int | None = None
    remaining: int | None = None
    reset_at: dt.datetime | None = None

    def update(self, headers: Mapping[str, str]) -> None:
        """Update state from rate-limit response headers."""
        limit = _parse_int(headers.get("x-ratelimit-limit"))
        if limit is not None:
            self.limit = limit

        remaining = _parse_int(headers.get("x-ratelimit-remaining"))
        if remaining is not None:
            self.remaining = remaining

        reset_timestamp = _parse_int(headers.get("x-ratelimit-reset"))
        if reset_timestamp is not None:
            self.reset_at = dt.datetime.fromtimestamp(reset_timestamp, tz=dt.UTC)

    def is_exhausted(self) -> bool:
        """Return whether the known rate-limit bucket is exhausted."""
        return self.remaining is not None and self.remaining <= 0

    def seconds_until_reset(self) -> float:
        """Return seconds until reset, or zero when reset time is unknown/past."""
        if self.reset_at is None:
            return 0.0
        return max((self.reset_at - dt.datetime.now(dt.UTC)).total_seconds(), 0.0)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = ["RateLimitState"]
