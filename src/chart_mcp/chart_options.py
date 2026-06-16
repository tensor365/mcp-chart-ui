"""Translate a :class:`ChartPlan` into an ECharts ``option`` dict.

The option is built server-side (in Python) so that the charting decision and
its configuration are fully testable without a browser. The front-end simply
does ``chart.setOption(option)``.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .chart_selector import _BAR_TYPES, ChartPlan, ChartType
from .data_utils import ColumnKind, coerce_for_kind, infer_column_kinds

# Per-series point count above which ECharts large-mode / LTTB sampling kicks in
# (keeps line/scatter responsive when `max_rows` is raised well above the default).
_LARGE_SERIES_THRESHOLD = 3000

# Number of bins used for histograms (Sturges-like, capped for readability).
_MAX_HIST_BINS = 20


def _num(value: Any) -> float | None:
    """Coerce to a JSON-safe float (NaN/inf -> None)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _axis_labels(series: pd.Series, kind: ColumnKind) -> list[str]:
    coerced = coerce_for_kind(series, kind)
    if kind is ColumnKind.DATETIME:
        return [v.isoformat() if isinstance(v, pd.Timestamp) else str(v) for v in coerced]
    return [str(v) for v in coerced]


def _toolbox(include_brush: bool) -> dict[str, Any]:
    feature: dict[str, Any] = {
        "dataZoom": {"yAxisIndex": "none"},
        "restore": {},
        "saveAsImage": {},
    }
    if include_brush:
        feature["brush"] = {"type": ["rect", "polygon", "clear"]}
    return {"feature": feature, "right": 8, "top": 2}


def _legend(names: list[str]) -> dict[str, Any]:
    # Leave the top-right corner free for the toolbox icons.
    return {"data": names, "type": "scroll", "top": 6, "left": "center", "right": 120}


def _base_option(title: str) -> dict[str, Any]:
    # The title is shown in the page header (HTML), not inside the chart, to
    # avoid overlapping the toolbox icons and duplicating the heading.
    return {
        "tooltip": {"trigger": "item"},
        "animationDuration": 400,
    }


def _cartesian_grid() -> dict[str, Any]:
    return {"left": 56, "right": 24, "bottom": 64, "top": 44, "containLabel": True}


def _datazoom() -> list[dict[str, Any]]:
    return [
        {"type": "inside"},
        {"type": "slider", "bottom": 8},
    ]


def build_echarts_option(df: pd.DataFrame, plan: ChartPlan, title: str) -> dict[str, Any]:
    """Build the full ECharts option dict for the given plan.

    Returns a plain dict that is safe to ``json.dumps`` (no NaN/inf/Timestamp).
    """
    kinds = infer_column_kinds(df)

    if plan.chart_type is ChartType.PIE:
        return _build_pie(df, plan, title, kinds)
    if plan.chart_type is ChartType.SCATTER:
        return _build_scatter(df, plan, title)
    if plan.chart_type is ChartType.HISTOGRAM:
        return _build_histogram(df, plan, title)
    if plan.chart_type in _BAR_TYPES:
        return _build_bar(df, plan, title, kinds)
    # line / area.
    return _build_line_area(df, plan, title, kinds)


def _unique_in_order(values: list[Any]) -> list[str]:
    """Return string labels of values, de-duplicated, preserving first order."""
    return list(dict.fromkeys(str(v) for v in values))


def _cartesian_skeleton(title: str, legend_names: list[str], x_name: str | None) -> dict[str, Any]:
    """Shared option scaffold for bar / line / area charts."""
    option = _base_option(title)
    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "legend": _legend(legend_names),
            "grid": _cartesian_grid(),
            "toolbox": _toolbox(include_brush=True),
            "brush": {"xAxisIndex": "all", "throttleType": "debounce", "throttleDelay": 200},
            "yAxis": {"type": "value"},
            "dataZoom": _datazoom(),
        }
    )
    return option


def _build_line_area(
    df: pd.DataFrame, plan: ChartPlan, title: str, kinds: dict[str, ColumnKind]
) -> dict[str, Any]:
    assert plan.x is not None
    categories = _axis_labels(df[plan.x], kinds[plan.x])
    is_area = plan.chart_type is ChartType.AREA

    series = []
    for col in plan.y:
        spec: dict[str, Any] = {
            "name": col,
            "type": "line",
            "data": [_num(v) for v in df[col]],
            "emphasis": {"focus": "series"},
            "selectedMode": "multiple",
        }
        if is_area:
            spec["areaStyle"] = {"opacity": 0.25}
            spec["smooth"] = True
        if plan.stacked:
            spec["stack"] = "total"
        if len(spec["data"]) > _LARGE_SERIES_THRESHOLD:
            # Downsample visually (Largest-Triangle-Three-Buckets) without
            # dropping data, and hide markers to keep the line readable.
            spec["sampling"] = "lttb"
            spec["showSymbol"] = False
        series.append(spec)

    option = _cartesian_skeleton(title, plan.y, plan.x)
    option["xAxis"] = {
        "type": "category", "data": categories, "name": plan.x, "nameGap": 28,
        "nameLocation": "middle", "axisLabel": {"hideOverlap": True},
    }
    option["series"] = series
    return option


def _build_bar(
    df: pd.DataFrame, plan: ChartPlan, title: str, kinds: dict[str, ColumnKind]
) -> dict[str, Any]:
    """Build a bar option, optionally pivoted by ``group_by`` and/or stacked."""
    assert plan.x is not None

    if plan.group_by:
        categories, series, legend_names = _grouped_bar_series(df, plan)
    else:
        categories = _axis_labels(df[plan.x], kinds[plan.x])
        legend_names = list(plan.y)
        series = []
        for col in plan.y:
            spec: dict[str, Any] = {
                "name": col,
                "type": "bar",
                "data": [_num(v) for v in df[col]],
                "emphasis": {"focus": "series"},
                "selectedMode": "multiple",
            }
            if plan.stacked:
                spec["stack"] = "total"
            series.append(spec)

    option = _cartesian_skeleton(title, legend_names, plan.x)
    option["xAxis"] = {
        "type": "category", "data": categories, "name": plan.x, "nameGap": 28,
        "nameLocation": "middle", "axisLabel": {"hideOverlap": True},
    }
    option["series"] = series
    return option


def _grouped_bar_series(
    df: pd.DataFrame, plan: ChartPlan
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Pivot a long-form measure into one bar series per ``group_by`` value.

    Multiple rows sharing the same (x, group) pair are summed. Returns the
    ordered category labels, the ECharts series list and the legend names.
    """
    assert plan.group_by is not None
    measure = plan.y[0]
    xs = df[plan.x].astype(str)
    gs = df[plan.group_by].astype(str)
    values = pd.to_numeric(df[measure], errors="coerce")

    categories = _unique_in_order(df[plan.x].tolist())
    groups = _unique_in_order(df[plan.group_by].tolist())

    series: list[dict[str, Any]] = []
    for g in groups:
        data: list[float | None] = []
        for c in categories:
            mask = (xs == c) & (gs == g)
            cell = values[mask].dropna()
            data.append(float(cell.sum()) if len(cell) else None)
        spec: dict[str, Any] = {
            "name": g,
            "type": "bar",
            "data": data,
            "emphasis": {"focus": "series"},
            "selectedMode": "multiple",
        }
        if plan.stacked:
            spec["stack"] = "total"
        series.append(spec)
    return categories, series, groups


def _build_scatter(df: pd.DataFrame, plan: ChartPlan, title: str) -> dict[str, Any]:
    assert plan.x is not None
    x_vals = [_num(v) for v in df[plan.x]]
    series = []
    for col in plan.y:
        points = [[x_vals[i], _num(df[col].iloc[i])] for i in range(len(df))]
        series.append(
            {
                "name": col,
                "type": "scatter",
                "data": points,
                "emphasis": {"focus": "series"},
                "selectedMode": "multiple",
                **(
                    {"large": True, "largeThreshold": _LARGE_SERIES_THRESHOLD}
                    if len(points) > _LARGE_SERIES_THRESHOLD
                    else {}
                ),
            }
        )
    option = _base_option(title)
    option.update(
        {
            "tooltip": {"trigger": "item"},
            "legend": _legend(plan.y),
            "grid": _cartesian_grid(),
            "toolbox": _toolbox(include_brush=True),
            "brush": {"xAxisIndex": "all", "yAxisIndex": "all"},
            "xAxis": {"type": "value", "name": plan.x, "nameGap": 26, "nameLocation": "middle", "scale": True},
            "yAxis": {"type": "value", "name": ", ".join(plan.y), "scale": True},
            "dataZoom": [{"type": "inside", "xAxisIndex": 0}, {"type": "inside", "yAxisIndex": 0}],
            "series": series,
        }
    )
    return option


def _build_pie(
    df: pd.DataFrame, plan: ChartPlan, title: str, kinds: dict[str, ColumnKind]
) -> dict[str, Any]:
    assert plan.x is not None
    labels = _axis_labels(df[plan.x], kinds[plan.x])
    value_col = plan.y[0]
    data = [
        {"name": labels[i], "value": _num(df[value_col].iloc[i])}
        for i in range(len(df))
        if _num(df[value_col].iloc[i]) is not None
    ]
    option = _base_option(title)
    option.update(
        {
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {"type": "scroll", "orient": "vertical", "left": 8, "top": "middle"},
            "toolbox": _toolbox(include_brush=False),
            "series": [
                {
                    "name": value_col,
                    "type": "pie",
                    "radius": ["35%", "68%"],
                    "center": ["58%", "55%"],
                    "selectedMode": "single",
                    "data": data,
                    "emphasis": {"itemStyle": {"shadowBlur": 10, "shadowColor": "rgba(0,0,0,0.3)"}},
                    "label": {"formatter": "{b}\n{d}%"},
                }
            ],
        }
    )
    return option


def _build_histogram(df: pd.DataFrame, plan: ChartPlan, title: str) -> dict[str, Any]:
    col = plan.y[0]
    values = pd.to_numeric(df[col], errors="coerce").dropna()
    option = _base_option(title)
    if values.empty:
        option.update({"xAxis": {"type": "category", "data": []}, "yAxis": {"type": "value"}, "series": []})
        return option

    n_bins = max(1, min(_MAX_HIST_BINS, int(math.ceil(math.log2(len(values) + 1)) + 1)))
    counts, edges = _histogram_counts(values.tolist(), n_bins)
    labels = [f"{edges[i]:.3g}–{edges[i + 1]:.3g}" for i in range(len(counts))]

    option.update(
        {
            "tooltip": {"trigger": "axis"},
            "grid": _cartesian_grid(),
            "toolbox": _toolbox(include_brush=True),
            "brush": {"xAxisIndex": "all"},
            "xAxis": {"type": "category", "data": labels, "name": col, "nameLocation": "middle",
                       "nameGap": 28, "axisLabel": {"rotate": 30, "hideOverlap": True}},
            "yAxis": {"type": "value", "name": "count"},
            "series": [
                {
                    "name": "count",
                    "type": "bar",
                    "data": counts,
                    "barWidth": "99%",
                    "selectedMode": "multiple",
                    "emphasis": {"focus": "series"},
                }
            ],
        }
    )
    return option


def _histogram_counts(values: list[float], n_bins: int) -> tuple[list[int], list[float]]:
    """Compute integer bin counts and bin edges without numpy."""
    lo, hi = min(values), max(values)
    if lo == hi:
        return [len(values)], [lo, hi if hi != lo else lo + 1.0]
    width = (hi - lo) / n_bins
    edges = [lo + i * width for i in range(n_bins)] + [hi]
    counts = [0] * n_bins
    for v in values:
        idx = int((v - lo) / width)
        if idx == n_bins:  # the maximum value lands in the last bin
            idx = n_bins - 1
        counts[idx] += 1
    return counts, edges
