"""Unit tests for chart_mcp.data_utils."""

import math

import pandas as pd
import pytest

from chart_mcp.data_utils import (
    ColumnKind,
    dataframe_to_columns_and_rows,
    infer_column_kind,
    infer_column_kinds,
    records_to_dataframe,
)


def test_records_to_dataframe_preserves_column_order():
    records = [{"b": 1, "a": 2}, {"a": 3, "c": 4}]
    df = records_to_dataframe(records)
    assert list(df.columns) == ["b", "a", "c"]
    assert df.shape == (2, 3)


def test_records_to_dataframe_allows_missing_keys():
    df = records_to_dataframe([{"a": 1}, {"a": 2, "b": 9}])
    assert math.isnan(df["b"].iloc[0])


@pytest.mark.parametrize("bad", [[], "not a list", [1, 2, 3], [{"a": 1}, "x"]])
def test_records_to_dataframe_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        records_to_dataframe(bad)


def test_infer_kind_numeric():
    assert infer_column_kind(pd.Series([1, 2, 3])) is ColumnKind.NUMERIC
    assert infer_column_kind(pd.Series([1.5, 2.0, None])) is ColumnKind.NUMERIC


def test_infer_kind_numeric_strings():
    assert infer_column_kind(pd.Series(["1", "2", "3"])) is ColumnKind.NUMERIC


def test_infer_kind_boolean():
    assert infer_column_kind(pd.Series([True, False, True])) is ColumnKind.BOOLEAN


def test_infer_kind_datetime_strings():
    s = pd.Series(["2024-01-01", "2024-02-01", "2024-03-01"])
    assert infer_column_kind(s) is ColumnKind.DATETIME


def test_infer_kind_categorical():
    assert infer_column_kind(pd.Series(["red", "green", "blue"])) is ColumnKind.CATEGORICAL


def test_infer_column_kinds_mapping():
    df = records_to_dataframe(
        [{"day": "2024-01-01", "city": "Lille", "sales": 10, "ok": True}]
    )
    kinds = infer_column_kinds(df)
    assert kinds["day"] is ColumnKind.DATETIME
    assert kinds["city"] is ColumnKind.CATEGORICAL
    assert kinds["sales"] is ColumnKind.NUMERIC
    assert kinds["ok"] is ColumnKind.BOOLEAN


def test_dataframe_to_columns_and_rows_is_json_safe():
    df = records_to_dataframe([{"a": 1, "b": float("nan")}, {"a": 2, "b": 5}])
    columns, rows = dataframe_to_columns_and_rows(df)
    assert columns == ["a", "b"]
    assert rows[0][1] is None  # NaN -> None
    assert rows[1][1] == 5


def test_dataframe_to_columns_and_rows_serialises_timestamps():
    df = records_to_dataframe([{"d": "2024-01-01"}])
    df["d"] = pd.to_datetime(df["d"])
    _, rows = dataframe_to_columns_and_rows(df)
    assert rows[0][0].startswith("2024-01-01")
