"""Unit tests for chart_mcp.ui_builder."""

from chart_mcp.chart_selector import select_chart
from chart_mcp.data_utils import records_to_dataframe
from chart_mcp.ui_builder import build_chart_html


def _html(records, **kw):
    df = records_to_dataframe(records)
    plan = select_chart(df, **kw)
    return build_chart_html(df, plan, "My Title")


def test_all_tokens_replaced():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert "__" not in html.replace("__doctype", "")  # no leftover __TOKEN__
    for token in ("__OPTION_JSON__", "__ROWS_JSON__", "__TITLE_JSON__", "__XCOL_JSON__"):
        assert token not in html


def test_includes_chart_and_xlsx_libraries():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert "echarts" in html
    assert "xlsx" in html
    assert "📊 Graphique" in html
    assert "Excel" in html and "CSV" in html


def test_title_is_injected():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert "My Title" in html


def test_script_breaking_data_is_escaped():
    # A value containing "</script>" must not terminate the inline script block.
    html = _html([{"name": "a</script>b", "v": 1}, {"name": "c", "v": 2}])
    # The raw closing tag from data must be neutralised via \u003c escaping.
    assert "a</script>b" not in html
    assert "\\u003c/script>b" in html


def test_rows_payload_present():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert "var ROWS" in html
    assert "var COLUMNS" in html


def test_grouped_bar_injects_selection_context():
    rows = [
        {"region": "North", "product": "A", "sales": 10},
        {"region": "North", "product": "B", "sales": 5},
        {"region": "South", "product": "A", "sales": 7},
    ]
    html = _html(rows)  # auto -> grouped_bar by product
    assert '"product"' in html  # GROUP_COL payload
    assert "var GROUP_COL" in html
    assert "var CATEGORIES" in html
    assert "var SERIES_NAMES" in html


def test_ungrouped_chart_has_null_group_col():
    import re
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert re.search(r"var GROUP_COL\s*=\s*null;", html)


def test_default_assets_use_cdn():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert "cdn.jsdelivr.net" in html
    assert "__ECHARTS_TAG__" not in html and "__XLSX_TAG__" not in html


def test_custom_asset_tags_are_injected():
    from chart_mcp.assets import resolve_asset_tags
    from chart_mcp.chart_selector import select_chart
    from chart_mcp.data_utils import records_to_dataframe
    from chart_mcp.ui_builder import build_chart_html

    df = records_to_dataframe([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    plan = select_chart(df)
    html = build_chart_html(df, plan, "T", asset_tags=resolve_asset_tags("http://h:8000/assets"))
    assert "http://h:8000/assets/echarts.min.js" in html
    assert "cdn.jsdelivr.net" not in html


def test_warnings_and_map_selection_injected():
    from chart_mcp.chart_selector import select_chart
    from chart_mcp.data_utils import records_to_dataframe
    from chart_mcp.ui_builder import build_chart_html

    df = records_to_dataframe([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    plan = select_chart(df, requested_type=__import__("chart_mcp.chart_selector", fromlist=["ChartType"]).ChartType.BAR)
    html = build_chart_html(df, plan, "T", map_selection=False, warnings=["Donnée tronquée"])
    assert "Donnée tronquée" in html
    assert "var MAP_SELECTION = false;" in html


def test_table_uses_table_df_not_chart_df():
    # When chart_df is aggregated, the table should reflect table_df rows.
    from chart_mcp.chart_selector import ChartType, select_chart
    from chart_mcp.data_utils import records_to_dataframe
    from chart_mcp.ui_builder import build_chart_html

    chart_df = records_to_dataframe([{"c": "A", "v": 3}])  # 1 aggregated row
    table_df = records_to_dataframe([{"c": "A", "v": 1}, {"c": "A", "v": 2}])  # 2 raw rows
    plan = select_chart(chart_df, requested_type=ChartType.BAR)
    html = build_chart_html(chart_df, plan, "T", table_df=table_df)
    # ROWS payload should carry the 2 raw rows.
    import re, json
    m = re.search(r"var ROWS\s*=\s*(.*?);\n", html, re.S)
    rows = json.loads(m.group(1).replace("\\u003c", "<"))
    assert len(rows) == 2


def test_download_urls_are_injected():
    df = records_to_dataframe([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    plan = select_chart(df)
    html = build_chart_html(
        df, plan, "T",
        download_urls={"csv": "http://h:8013/download/tok/csv",
                       "xlsx": "http://h:8013/download/tok/xlsx"},
    )
    assert "http://h:8013/download/tok/csv" in html
    assert "http://h:8013/download/tok/xlsx" in html
    assert "var CSV_URL" in html


def test_no_download_urls_yields_null():
    import re
    df = records_to_dataframe([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    plan = select_chart(df)
    html = build_chart_html(df, plan, "T")
    assert re.search(r"var CSV_URL\s*=\s*null;", html)


def test_chart_title_not_in_echarts_option():
    # Title lives in the page header, not the ECharts option (avoids toolbox overlap).
    from chart_mcp.chart_options import build_echarts_option
    df = records_to_dataframe([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    plan = select_chart(df)
    opt = build_echarts_option(df, plan, "My Title")
    assert "title" not in opt


# --- robust export (sandbox-safe clipboard fallback) -----------------------

def test_export_has_clipboard_fallback_and_toast():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert 'id="dl-copy"' in html          # explicit copy button
    assert 'id="toast"' in html            # user feedback element
    assert "function copyText" in html     # execCommand-based copy helper
    assert 'execCommand("copy")' in html


def test_export_still_offers_csv_and_excel():
    html = _html([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    assert 'id="dl-csv"' in html and 'id="dl-xlsx"' in html
