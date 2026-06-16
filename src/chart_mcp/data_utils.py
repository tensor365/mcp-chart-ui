"""Data normalisation helpers.

This module turns the loosely-typed list-of-records that an LLM produces into a
clean :class:`pandas.DataFrame`, and classifies every column into one of four
*kinds* (numeric / datetime / boolean / categorical). The chart-selection logic
relies entirely on these kinds, so keeping the detection here makes it trivial
to unit-test in isolation.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

import pandas as pd

# A column is treated as a date column only if at least this share of its
# non-null values parse as dates. Keeps "12", "34" from being read as years.
_DATETIME_PARSE_THRESHOLD = 0.8


class ColumnKind(str, Enum):
    """Semantic kind of a column, used to pick a chart type."""

    NUMERIC = "numeric"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"


def records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert a list of record dicts into a DataFrame, preserving column order.

    Args:
        records: Non-empty list of ``{column: value}`` mappings. Missing keys in
            some rows are allowed and become NaN.

    Returns:
        A DataFrame whose columns follow first-seen order across all records.

    Raises:
        ValueError: If ``records`` is empty or not a list of dicts.
    """
    if not isinstance(records, list) or not records:
        raise ValueError("`data` must be a non-empty list of record objects.")
    if not all(isinstance(row, dict) for row in records):
        raise ValueError("Every item in `data` must be an object (mapping).")

    # Preserve first-seen column order rather than letting pandas sort/union it.
    ordered_cols: list[str] = []
    for row in records:
        for key in row:
            if key not in ordered_cols:
                ordered_cols.append(key)

    df = pd.DataFrame(records, columns=ordered_cols)
    return df


def _looks_like_datetime(series: pd.Series) -> bool:
    """Return True if an object/string series is predominantly parseable dates."""
    non_null = series.dropna()
    if non_null.empty:
        return False
    # Pure integers/floats masquerading as objects should stay numeric.
    parsed = pd.to_datetime(non_null, errors="coerce", format="mixed")
    success_ratio = parsed.notna().mean()
    return bool(success_ratio >= _DATETIME_PARSE_THRESHOLD)


def infer_column_kind(series: pd.Series) -> ColumnKind:
    """Classify a single column into a :class:`ColumnKind`."""
    if pd.api.types.is_bool_dtype(series):
        return ColumnKind.BOOLEAN
    if pd.api.types.is_numeric_dtype(series):
        return ColumnKind.NUMERIC
    if pd.api.types.is_datetime64_any_dtype(series):
        return ColumnKind.DATETIME
    # Object/string column: try to coerce to numeric, then to datetime.
    coerced = pd.to_numeric(series, errors="coerce")
    if coerced.notna().mean() >= _DATETIME_PARSE_THRESHOLD and series.dropna().size:
        return ColumnKind.NUMERIC
    if _looks_like_datetime(series):
        return ColumnKind.DATETIME
    return ColumnKind.CATEGORICAL


def infer_column_kinds(df: pd.DataFrame) -> dict[str, ColumnKind]:
    """Classify every column of a DataFrame.

    Returns:
        Mapping of column name to :class:`ColumnKind`, in column order.
    """
    return {col: infer_column_kind(df[col]) for col in df.columns}


def coerce_for_kind(series: pd.Series, kind: ColumnKind) -> pd.Series:
    """Return the column cast to the dtype implied by its inferred kind."""
    if kind is ColumnKind.NUMERIC:
        return pd.to_numeric(series, errors="coerce")
    if kind is ColumnKind.DATETIME:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    return series


def _json_safe_scalar(value: Any) -> Any:
    """Convert a single cell into a JSON-serialisable value (NaN -> None)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    # numpy scalar types expose .item()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except (ValueError, TypeError):
            return value
    return value


def dataframe_to_columns_and_rows(
    df: pd.DataFrame,
) -> tuple[list[str], list[list[Any]]]:
    """Split a DataFrame into a JSON-safe ``(columns, rows)`` pair for the table.

    Rows are returned as a list of positional lists (not dicts) so the front-end
    table stays compact and column order is guaranteed. Row capping is handled
    upstream by :func:`chart_mcp.data_reduce.prepare_data`.
    """
    columns = [str(c) for c in df.columns]
    rows = [
        [_json_safe_scalar(v) for v in record]
        for record in df.itertuples(index=False, name=None)
    ]
    return columns, rows
