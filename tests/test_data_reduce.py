"""Unit tests for chart_mcp.data_reduce."""

import pandas as pd

from chart_mcp.chart_selector import ChartType, select_chart
from chart_mcp.data_reduce import OTHERS_LABEL, build_summary, prepare_data
from chart_mcp.data_utils import records_to_dataframe


def _df(records):
    return records_to_dataframe(records)


def test_no_reduction_for_small_data():
    df = _df([{"c": "A", "v": 1}, {"c": "B", "v": 2}])
    plan = select_chart(df, requested_type=ChartType.BAR)
    prep = prepare_data(df, plan, max_rows=5000)
    assert prep.total_rows == 2
    assert prep.table_truncated is False
    assert not prep.warnings
    assert len(prep.table_df) == 2
    assert prep.map_selection is True


def test_row_cap_truncates_table_and_chart_together():
    df = _df([{"c": f"C{i}", "v": i} for i in range(100)])
    plan = select_chart(df, requested_type=ChartType.BAR)
    prep = prepare_data(df, plan, max_rows=20)
    assert prep.table_truncated is True
    assert len(prep.table_df) == 20
    assert len(prep.chart_df) == 20  # same rows -> selection still maps
    assert prep.map_selection is True
    assert any("20 premières lignes sur 100" in w for w in prep.warnings)


def test_histogram_disables_selection_mapping():
    df = _df([{"v": i} for i in range(10)])
    plan = select_chart(df)  # histogram
    prep = prepare_data(df, plan)
    assert plan.chart_type is ChartType.HISTOGRAM
    assert prep.map_selection is False


def test_top_n_keeps_largest_and_buckets_rest():
    # values 100..81 ; categories C0 (100) ... C19 (81)
    df = _df([{"cat": f"C{i}", "v": 100 - i} for i in range(20)])
    plan = select_chart(df, requested_type=ChartType.BAR)
    prep = prepare_data(df, plan, top_n=5)
    cats = list(prep.chart_df["cat"])
    assert OTHERS_LABEL in cats
    # 5 kept + 1 "Autres"
    assert len(prep.chart_df) == 6
    assert prep.chart_aggregated is True
    assert prep.map_selection is False  # aggregated -> no row mapping
    # "Autres" must equal the sum of the dropped categories (C5..C19).
    dropped_sum = sum(100 - i for i in range(5, 20))
    others_val = float(prep.chart_df.loc[prep.chart_df["cat"] == OTHERS_LABEL, "v"].iloc[0])
    assert others_val == dropped_sum


def test_top_n_noop_when_few_categories():
    df = _df([{"cat": "A", "v": 1}, {"cat": "B", "v": 2}])
    plan = select_chart(df, requested_type=ChartType.BAR)
    prep = prepare_data(df, plan, top_n=5)
    assert prep.chart_aggregated is False
    assert prep.map_selection is True


def test_top_n_with_grouped_bar_preserves_groups():
    rows = []
    for i in range(10):
        rows.append({"region": f"R{i}", "product": "A", "sales": 100 - i})
        rows.append({"region": f"R{i}", "product": "B", "sales": 50 - i})
    df = _df(rows)
    plan = select_chart(df)  # grouped_bar by product
    assert plan.chart_type is ChartType.GROUPED_BAR
    prep = prepare_data(df, plan, top_n=3)
    # Both product groups must survive in the aggregated frame.
    assert set(prep.chart_df["product"]) == {"A", "B"}
    assert OTHERS_LABEL in set(prep.chart_df["region"])


def test_summary_mentions_type_and_rows():
    df = _df([{"region": "N", "product": "A", "sales": 5}])
    plan = select_chart(df, requested_type=ChartType.GROUPED_BAR)
    prep = prepare_data(df, plan)
    summary = build_summary(plan, prep)
    assert "barres groupées" in summary
    assert "product" in summary
    assert "1 lignes" in summary


def test_summary_includes_warnings_when_truncated():
    df = _df([{"c": f"C{i}", "v": i} for i in range(30)])
    plan = select_chart(df, requested_type=ChartType.BAR)
    prep = prepare_data(df, plan, max_rows=10)
    summary = build_summary(plan, prep)
    assert "10 lignes affichées sur 30" in summary
