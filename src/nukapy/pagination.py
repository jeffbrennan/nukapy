"""Pagination interfaces."""

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Literal

from nukapy.soql import Query, SoQLParamValue

DEFAULT_BATCH_SIZE = 10_000

PaginationStrategy = Literal["id", "offset", "updated_at"]
Params = dict[str, SoQLParamValue]


@dataclasses.dataclass(frozen=True)
class PageRequest:
    """One Socrata page request and its checkpoint basis."""

    params: Params
    state: dict[str, object]


@dataclasses.dataclass(frozen=True)
class PaginationConfig:
    """Configuration for dataset iteration."""

    batch_size: int = DEFAULT_BATCH_SIZE
    strategy: PaginationStrategy = "id"
    query: Query | None = None
    state: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Validate pagination settings."""
        if self.batch_size <= 0:
            msg = "batch_size must be greater than zero"
            raise ValueError(msg)
        if self.query is not None:
            params = self.query.to_params()
            if "$limit" in params or "$offset" in params or "$order" in params:
                msg = "streaming queries cannot include limit, offset, or order"
                raise ValueError(msg)


class Paginator:
    """Generate SoQL params for paged dataset reads."""

    def __init__(self, config: PaginationConfig) -> None:
        """Create a paginator."""
        self._config = config
        self._state: dict[str, object] = dict(config.state or {})

    @property
    def checkpoint(self) -> dict[str, object]:
        """Return the latest pagination checkpoint."""
        return dict(self._state)

    def next_request(self) -> PageRequest:
        """Return request params for the next page."""
        params = self._base_params()
        params["$limit"] = self._config.batch_size

        if self._config.strategy == "offset":
            offset = _int_state(self._state, "offset", 0)
            params["$offset"] = offset
            state = {**self._state, "offset": offset}
        elif self._config.strategy == "updated_at":
            updated_at = _str_state(self._state, "updated_at", "")
            last_id = _int_state(self._state, "id", 0)
            params["$select"] = _with_system_select(params.get("$select"), (":updated_at", ":id"))
            params["$where"] = _and_where(
                params.get("$where"),
                _updated_at_where(updated_at, last_id),
            )
            params["$order"] = ":updated_at, :id"
            state = {**self._state, "updated_at": updated_at, "id": last_id}
        else:
            last_id = _int_state(self._state, "id", 0)
            params["$select"] = _with_system_select(params.get("$select"), (":id",))
            params["$where"] = _and_where(params.get("$where"), f":id > {last_id}")
            params["$order"] = ":id"
            state = {**self._state, "id": last_id}

        return PageRequest(params=params, state=state)

    def advance(self, rows: Sequence[Mapping[str, object]]) -> None:
        """Advance the checkpoint after a non-empty page."""
        if self._config.strategy == "offset":
            self._state["offset"] = _int_state(self._state, "offset", 0) + len(rows)
            return

        last_row = rows[-1]
        if self._config.strategy == "updated_at":
            updated_at = last_row.get(":updated_at")
            if isinstance(updated_at, str):
                self._state["updated_at"] = updated_at
            else:
                msg = "updated_at pagination requires returned rows to include :updated_at"
                raise ValueError(msg)

        row_id = last_row.get(":id")
        if isinstance(row_id, int):
            self._state["id"] = row_id
        elif isinstance(row_id, str) and row_id.isdecimal():
            self._state["id"] = int(row_id)
        else:
            msg = f"{self._config.strategy} pagination requires returned rows to include :id"
            raise ValueError(msg)

    def _base_params(self) -> Params:
        if self._config.query is None:
            return {}
        return dict(self._config.query.to_params())


def _and_where(existing: SoQLParamValue | None, cursor_where: str) -> str:
    if existing is None:
        return cursor_where
    return f"({existing}) AND ({cursor_where})"


def _with_system_select(existing: SoQLParamValue | None, columns: tuple[str, ...]) -> str:
    prefix = ", ".join(columns)
    if existing is None:
        return f"{prefix}, *"
    return f"{prefix}, {existing}"


def _updated_at_where(updated_at: str, last_id: int) -> str:
    if not updated_at:
        return ":updated_at IS NOT NULL"
    escaped = updated_at.replace("'", "''")
    return f"(:updated_at > '{escaped}') OR (:updated_at = '{escaped}' AND :id > {last_id})"


def _int_state(state: Mapping[str, object], key: str, default: int) -> int:
    value = state.get(key, default)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return default


def _str_state(state: Mapping[str, object], key: str, default: str) -> str:
    value = state.get(key, default)
    return value if isinstance(value, str) else default


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "PageRequest",
    "PaginationConfig",
    "PaginationStrategy",
    "Paginator",
]
