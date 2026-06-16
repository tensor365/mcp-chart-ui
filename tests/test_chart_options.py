"""Unit tests for chart_mcp.chart_options."""

import json

from chart_mcp.chart_options import _LARGE_SERIES_THRESHOLD, build_echarts_option
from chart_mcp.chart_selector import ChartPlan, ChartType, select_chart
from chart_mcp.data_utils import records_to_dataframe


def _df(records):
    return records_to_dataframe(records)


def _option(records, **kw):
    df = _df(records)
    plan = select_chart(df, **kw)
    return df, plan, build_echarts_option(df, plan, "T")


def test_bar_option_structure():
    _, _, opt = _option(
        [{"c": "A", "v": 1}, {"c": "B", "v": 2}], requested_type=ChartType.BAR
    )
    assert opt["xAxis"]["type"] == "category"
    assert opt["xAxis"]["data"] == ["A", "B"]
    assert opt["series"][0]["type"] == "bar"
    assert opt["series"][0]["data"] == [1, 2]


def test_area_option_has_areastyle():
    df = _df([{"d": "2024-01-01", "v": 1}, {"d": "2024-02-01", "v": 2}])
    plan = select_chart(df)  # -> area
    opt = build_echarts_option(df, plan, "T")
    assert plan.chart_type is ChartType.AREA
    assert "areaStyle" in opt["series"][0]


def test_scatter_option_points():
    df, _, opt = _option(
        [{"x": 1, "y": 2}, {"x": 3, "y": 4}], requested_type=ChartType.SCATTER
    )
    assert opt["series"][0]["type"] == "scatter"
    assert opt["series"][0]["data"] == [[1, 2], [3, 4]]


def test_pie_option_data():
    _, _, opt = _option(
        [{"c": "A", "v": 10}, {"c": "B", "v": 20}], requested_type=ChartType.PIE
    )
    series = opt["series"][0]
    assert series["type"] == "pie"
    assert series["data"] == [{"name": "A", "value": 10}, {"name": "B", "value": 20}]


def test_histogram_counts_sum_to_n():
    records = [{"v": i} for i in range(50)]
    df, _, opt = _option(records, requested_type=ChartType.HISTOGRAM)
    counts = opt["series"][0]["data"]
    assert sum(counts) == 50
    assert len(opt["xAxis"]["data"]) == len(counts)


def test_nan_is_sanitised_to_none():
    df = _df([{"c": "A", "v": float("nan")}, {"c": "B", "v": 5}])
    plan = select_chart(df, requested_type=ChartType.BAR)
    opt = build_echarts_option(df, plan, "T")
    assert opt["series"][0]["data"][0] is None


def test_option_is_json_serialisable():
    _, _, opt = _option([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    # Must not raise (no NaN, Timestamp or numpy types left).
    json.dumps(opt)


# --- grouped / stacked bars ------------------------------------------------

GROUPED = [
    {"region": "North", "product": "A", "sales": 10},
    {"region": "North", "product": "B", "sales": 5},
    {"region": "South", "product": "A", "sales": 7},
    {"region": "South", "product": "B", "sales": 3},
]


def test_grouped_bar_pivots_into_one_series_per_group():
    df = _df(GROUPED)
    plan = select_chart(df)  # -> grouped_bar by product
    opt = build_echarts_option(df, plan, "T")
    assert opt["xAxis"]["data"] == ["North", "South"]
    names = [s["name"] for s in opt["series"]]
    assert names == ["A", "B"]
    # Series A: North=10, South=7 ; Series B: North=5, South=3
    assert opt["series"][0]["data"] == [10, 7]
    assert opt["series"][1]["data"] == [5, 3]


def test_grouped_bar_sums_duplicate_cells():
    rows = GROUPED + [{"region": "North", "product": "A", "sales": 4}]
    df = _df(rows)
    plan = select_chart(df, requested_type=ChartType.GROUPED_BAR)
    opt = build_echarts_option(df, plan, "T")
    # North/A now 10 + 4 = 14
    assert opt["series"][0]["data"][0] == 14


def test_stacked_bar_sets_stack_property():
    df = _df(GROUPED)
    plan = select_chart(df, requested_type=ChartType.STACKED_BAR)
    opt = build_echarts_option(df, plan, "T")
    assert all(s.get("stack") == "total" for s in opt["series"])


def test_grouped_bar_missing_cell_is_none():
    rows = [
        {"region": "North", "product": "A", "sales": 10},
        {"region": "South", "product": "B", "sales": 3},
    ]
    df = _df(rows)
    plan = select_chart(df, requested_type=ChartType.GROUPED_BAR)
    opt = build_echarts_option(df, plan, "T")
    # North has no product B -> that cell must be None, not 0.
    series_b = next(s for s in opt["series"] if s["name"] == "B")
    assert series_b["data"][0] is None


def test_grouped_bar_option_is_json_serialisable():
    df = _df(GROUPED)
    plan = select_chart(df)
    json.dumps(build_echarts_option(df, plan, "T"))


# --- large-data rendering --------------------------------------------------

def test_large_line_series_uses_lttb_sampling():
    import pandas as pd
    n = _LARGE_SERIES_THRESHOLD + 5
    dates = pd.date_range("2020-01-01", periods=n, freq="D").astype(str)
    df = _df([{"d": d, "v": i} for i, d in enumerate(dates)])
    plan = select_chart(df)  # datetime axis -> area
    opt = build_echarts_option(df, plan, "T")
    assert opt["series"][0].get("sampling") == "lttb"
    assert opt["series"][0].get("showSymbol") is False


def test_large_scatter_series_enables_large_mode():
    n = _LARGE_SERIES_THRESHOLD + 5
    df = _df([{"x": float(i), "y": float(2 * i)} for i in range(n)])
    plan = select_chart(df)  # two numeric -> scatter
    opt = build_echarts_option(df, plan, "T")
    assert opt["series"][0].get("large") is True


def test_small_series_has_no_sampling():
    df = _df([{"d": "2020-01-01", "v": 1}, {"d": "2020-01-02", "v": 2}])
    plan = select_chart(df)
    opt = build_echarts_option(df, plan, "T")
    assert "sampling" not in opt["series"][0]
