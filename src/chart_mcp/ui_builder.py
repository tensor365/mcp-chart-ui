"""Assemble the final HTML resource from a chart plan and prepared data."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pandas as pd

from .assets import AssetTags, resolve_asset_tags
from .chart_options import build_echarts_option
from .chart_selector import ChartPlan, ChartType
from .data_utils import dataframe_to_columns_and_rows
from .template import HTML_TEMPLATE


def _json_for_script(value: object) -> str:
    """Serialise a value for safe inlining inside a <script> tag.

    Escaping ``<`` prevents a stray ``</script>`` inside string data from
    terminating the script block early.
    """
    return json.dumps(value, ensure_ascii=False, default=str).replace("<", "\\u003c")


def build_chart_html(
    df: pd.DataFrame,
    plan: ChartPlan,
    title: str,
    *,
    table_df: pd.DataFrame | None = None,
    asset_tags: AssetTags | None = None,
    map_selection: bool | None = None,
    warnings: Sequence[str] = (),
) -> str:
    """Render the complete two-tab HTML document.

    Args:
        df: The data used to *draw the chart* (possibly aggregated/reduced).
        plan: The resolved chart plan (type + x/y/group roles + reasoning).
        title: Heading shown above the chart.
        table_df: The data shown in the *table* tab. Defaults to ``df``. May
            differ from ``df`` when the chart is a top-N aggregation.
        asset_tags: Script tags for ECharts/SheetJS. Defaults to the configured
            mode (``CHART_MCP_ASSETS``).
        map_selection: Whether a chart selection can highlight table rows.
            Defaults to ``False`` for histograms, ``True`` otherwise.
        warnings: Human-readable notes (e.g. truncation) shown in a banner.

    Returns:
        A full standalone HTML document as a string.
    """
    if table_df is None:
        table_df = df
    if asset_tags is None:
        asset_tags = resolve_asset_tags()
    if map_selection is None:
        map_selection = plan.chart_type is not ChartType.HISTOGRAM

    option = build_echarts_option(df, plan, title)
    columns, rows = dataframe_to_columns_and_rows(table_df)

    # Context the front-end needs to map a chart selection back to table rows
    # when bars are pivoted by a grouping column.
    x_axis = option.get("xAxis")
    categories = x_axis.get("data", []) if isinstance(x_axis, dict) else []
    series_names = [s.get("name") for s in option.get("series", [])]

    replacements = {
        "__TITLE_JSON__": _json_for_script(title),
        "__REASONING_JSON__": _json_for_script(plan.reasoning),
        "__CHART_TYPE_JSON__": _json_for_script(plan.chart_type.value),
        "__XCOL_JSON__": _json_for_script(plan.x),
        "__GROUPCOL_JSON__": _json_for_script(plan.group_by),
        "__CATEGORIES_JSON__": _json_for_script(categories),
        "__SERIES_NAMES_JSON__": _json_for_script(series_names),
        "__OPTION_JSON__": _json_for_script(option),
        "__COLUMNS_JSON__": _json_for_script(columns),
        "__ROWS_JSON__": _json_for_script(rows),
        "__MAP_SELECTION_JSON__": _json_for_script(bool(map_selection)),
        "__WARNINGS_JSON__": _json_for_script(list(warnings)),
    }

    html = HTML_TEMPLATE
    for token, payload in replacements.items():
        html = html.replace(token, payload)
    # Asset tags last: their (possibly inlined, large) content is never scanned
    # for other tokens.
    html = html.replace("__ECHARTS_TAG__", asset_tags.echarts)
    html = html.replace("__XLSX_TAG__", asset_tags.xlsx)
    return html
