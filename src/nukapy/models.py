"""Typed Socrata metadata models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ColumnMeta(BaseModel):
    """Metadata for a single column in a Socrata dataset."""

    model_config = ConfigDict(populate_by_name=True)

    field_name: str = Field(alias="fieldName")
    name: str
    data_type_name: str = Field(alias="dataTypeName")
    description: str | None = None
    position: int | None = None


class DatasetMeta(BaseModel):
    """Metadata for a Socrata dataset, as returned by the metadata API."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: int | None = Field(default=None, alias="createdAt")
    updated_at: int | None = Field(default=None, alias="updatedAt")
    columns: list[ColumnMeta] = Field(default_factory=list)


__all__ = ["ColumnMeta", "DatasetMeta"]
