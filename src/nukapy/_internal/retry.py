"""Retry policy helpers."""

import dataclasses
import datetime as dt
import email.utils
import random
from collections.abc import Mapping

RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 502, 503, 504})


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry backoff."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    backoff_factor: float = 2.0
    readonly_only: bool = True

    def delay(self, attempt: int) -> float:
        """Return a full-jitter delay for an attempt number."""
        upper_bound = min(
            self.base_delay * (self.backoff_factor**attempt), self.max_delay
        )
        return random.uniform(0, upper_bound)  # noqa: S311


def retry_after_delay(
    headers: Mapping[str, str], attempt: int, policy: RetryPolicy
) -> float:
    """Return a delay from Retry-After headers, falling back to policy jitter."""
    retry_after = headers.get("retry-after")
    if retry_after is None:
        return policy.delay(attempt)

    try:
        return min(max(float(int(retry_after)), 0.0), policy.max_delay)
    except ValueError:
        pass

    try:
        retry_at = email.utils.parsedate_to_datetime(retry_after)
    except (TypeError, ValueError):
        return policy.delay(attempt)

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=dt.UTC)

    seconds = (retry_at.astimezone(dt.UTC) - dt.datetime.now(dt.UTC)).total_seconds()
    return min(max(seconds, 0.0), policy.max_delay)


__all__ = ["RETRYABLE_STATUS_CODES", "RetryPolicy", "retry_after_delay"]
