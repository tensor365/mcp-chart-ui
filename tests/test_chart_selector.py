"""Unit tests for chart_mcp.chart_selector."""

import pytest

from chart_mcp.chart_selector import ChartType, select_chart
from chart_mcp.data_utils import records_to_dataframe


def _df(records):
    return records_to_dataframe(records)


def test_datetime_axis_single_series_is_area():
    df = _df([{"d": "2024-01-01", "v": 10}, {"d": "2024-02-01", "v": 20}])
    plan = select_chart(df)
    assert plan.chart_type is ChartType.AREA
    assert plan.x == "d"
    assert plan.y == ["v"]


def test_datetime_axis_multi_series_is_line():
    df = _df(
        [
            {"d": "2024-01-01", "a": 1, "b": 2},
            {"d": "2024-02-01", "a": 3, "b": 4},
        ]
    )
    plan = select_chart(df)
    assert plan.chart_type is ChartType.LINE
    assert set(plan.y) == {"a", "b"}


def test_few_categories_single_nonneg_is_pie():
    df = _df([{"cat": "A", "v": 10}, {"cat": "B", "v": 20}, {"cat": "C", "v": 5}])
    plan = select_chart(df)
    assert plan.chart_type is ChartType.PIE
    assert plan.x == "cat"


def test_many_categories_is_bar():
    df = _df([{"cat": f"C{i}", "v": i} for i in range(12)])
    plan = select_chart(df)
    assert plan.chart_type is ChartType.BAR


def test_negative_values_disable_pie():
    df = _df([{"cat": "A", "v": -10}, {"cat": "B", "v": 20}])
    plan = select_chart(df)
    assert plan.chart_type is ChartType.BAR


def test_two_numeric_is_scatter():
    df = _df([{"x": 1.0, "y": 2.0}, {"x": 2.0, "y": 4.5}, {"x": 3.0, "y": 1.2}])
    plan = select_chart(df)
    assert plan.chart_type is ChartType.SCATTER
    assert plan.x == "x"
    assert plan.y == ["y"]


def test_single_numeric_is_histogram():
    df = _df([{"v": 1}, {"v": 2}, {"v": 3}, {"v": 4}])
    plan = select_chart(df)
    assert plan.chart_type is ChartType.HISTOGRAM
    assert plan.x is None
    assert plan.y == ["v"]


# --- grouped / stacked bars ------------------------------------------------

GROUPED = [
    {"region": "North", "product": "A", "sales": 10},
    {"region": "North", "product": "B", "sales": 5},
    {"region": "South", "product": "A", "sales": 7},
    {"region": "South", "product": "B", "sales": 3},
]


def test_second_categorical_auto_selects_grouped_bar():
    plan = select_chart(_df(GROUPED))
    assert plan.chart_type is ChartType.GROUPED_BAR
    assert plan.x == "region"
    assert plan.group_by == "product"
    assert plan.y == ["sales"]
    assert plan.stacked is False


def test_second_categorical_with_stacked_flag_is_stacked_bar():
    plan = select_chart(_df(GROUPED), stacked=True)
    assert plan.chart_type is ChartType.STACKED_BAR
    assert plan.group_by == "product"
    assert plan.stacked is True


def test_requested_grouped_bar_resolves_group_by():
    plan = select_chart(_df(GROUPED), requested_type=ChartType.GROUPED_BAR)
    assert plan.chart_type is ChartType.GROUPED_BAR
    assert plan.group_by == "product"
    assert plan.stacked is False


def test_requested_stacked_bar_sets_stacked_and_group():
    plan = select_chart(_df(GROUPED), requested_type=ChartType.STACKED_BAR)
    assert plan.chart_type is ChartType.STACKED_BAR
    assert plan.group_by == "product"
    assert plan.stacked is True


def test_explicit_group_by_is_respected():
    plan = select_chart(_df(GROUPED), requested_type=ChartType.GROUPED_BAR,
                        x="product", group_by="region")
    assert plan.x == "product"
    assert plan.group_by == "region"


def test_missing_group_by_column_raises():
    with pytest.raises(ValueError):
        select_chart(_df(GROUPED), group_by="nope")


def test_stacked_flag_on_wide_form_stacks_y_columns():
    df = _df([{"cat": "A", "x": 1, "y": 2}, {"cat": "B", "x": 3, "y": 4}])
    plan = select_chart(df, stacked=True)
    assert plan.chart_type is ChartType.STACKED_BAR
    assert plan.stacked is True
    assert set(plan.y) == {"x", "y"}


def test_two_categoricals_do_not_become_pie():
    # Even with few categories, the second categorical must not be dropped.
    plan = select_chart(_df(GROUPED))
    assert plan.chart_type is not ChartType.PIE


def test_requested_type_is_honoured():
    df = _df([{"cat": "A", "v": 10}, {"cat": "B", "v": 20}])
    plan = select_chart(df, requested_type=ChartType.LINE)
    assert plan.chart_type is ChartType.LINE


def test_pinned_columns_are_respected():
    df = _df([{"m": "Jan", "rev": 100, "cost": 60}])
    plan = select_chart(df, x="m", y=["cost"])
    assert plan.x == "m"
    assert plan.y == ["cost"]


def test_missing_pinned_column_raises():
    df = _df([{"a": 1, "b": 2}])
    with pytest.raises(ValueError):
        select_chart(df, x="nope")


def test_no_numeric_column_raises():
    df = _df([{"a": "x", "b": "y"}])
    with pytest.raises(ValueError):
        select_chart(df)
