"""Unit tests for Socrata metadata models."""

import pytest
from pydantic import ValidationError

from nukapy import ColumnMeta as ExportedColumnMeta
from nukapy import DatasetMeta as ExportedDatasetMeta
from nukapy.models import ColumnMeta, DatasetMeta

COLUMN_PAYLOAD = {
    "fieldName": "unique_key",
    "name": "Unique Key",
    "dataTypeName": "number",
    "description": "A unique identifier.",
    "position": 1,
}

DATASET_PAYLOAD = {
    "id": "erm2-nwe9",
    "name": "311 Service Requests",
    "description": "NYC 311 calls.",
    "category": "Social Services",
    "tags": ["311", "nyc"],
    "createdAt": 1311196905,
    "updatedAt": 1621436854,
    "columns": [COLUMN_PAYLOAD],
}


def test_column_meta_parses_from_api_payload() -> None:
    col = ColumnMeta.model_validate(COLUMN_PAYLOAD)
    assert col.field_name == "unique_key"
    assert col.name == "Unique Key"
    assert col.data_type_name == "number"
    assert col.description == "A unique identifier."
    assert col.position == 1


def test_column_meta_description_optional() -> None:
    payload = {**COLUMN_PAYLOAD}
    del payload["description"]
    col = ColumnMeta.model_validate(payload)
    assert col.description is None


def test_column_meta_position_optional() -> None:
    payload = {**COLUMN_PAYLOAD}
    del payload["position"]
    col = ColumnMeta.model_validate(payload)
    assert col.position is None


def test_column_meta_snake_case_alias() -> None:
    col = ColumnMeta.model_validate({"field_name": "x", "name": "X", "data_type_name": "text"})
    assert col.field_name == "x"


def test_column_meta_requires_field_name() -> None:
    with pytest.raises(ValidationError):
        ColumnMeta.model_validate({"name": "X", "dataTypeName": "text"})


def test_dataset_meta_parses_from_api_payload() -> None:
    ds = DatasetMeta.model_validate(DATASET_PAYLOAD)
    assert ds.id == "erm2-nwe9"
    assert ds.name == "311 Service Requests"
    assert ds.description == "NYC 311 calls."
    assert ds.category == "Social Services"
    assert ds.tags == ["311", "nyc"]
    assert ds.created_at == 1311196905
    assert ds.updated_at == 1621436854
    assert len(ds.columns) == 1
    assert ds.columns[0].field_name == "unique_key"


def test_dataset_meta_optional_fields_default_to_none() -> None:
    ds = DatasetMeta.model_validate({"id": "abc", "name": "Test"})
    assert ds.description is None
    assert ds.category is None
    assert ds.created_at is None
    assert ds.updated_at is None


def test_dataset_meta_tags_default_to_empty_list() -> None:
    ds = DatasetMeta.model_validate({"id": "abc", "name": "Test"})
    assert ds.tags == []


def test_dataset_meta_columns_default_to_empty_list() -> None:
    ds = DatasetMeta.model_validate({"id": "abc", "name": "Test"})
    assert ds.columns == []


def test_dataset_meta_requires_id() -> None:
    with pytest.raises(ValidationError):
        DatasetMeta.model_validate({"name": "Test"})


def test_dataset_meta_requires_name() -> None:
    with pytest.raises(ValidationError):
        DatasetMeta.model_validate({"id": "abc"})


def test_dataset_meta_snake_case_aliases() -> None:
    ds = DatasetMeta.model_validate(
        {
            "id": "abc",
            "name": "Test",
            "created_at": 1000,
            "updated_at": 2000,
        }
    )
    assert ds.created_at == 1000
    assert ds.updated_at == 2000


def test_column_meta_exported_from_nukapy() -> None:
    assert ExportedColumnMeta is ColumnMeta


def test_dataset_meta_exported_from_nukapy() -> None:
    assert ExportedDatasetMeta is DatasetMeta
