"""Guardrails for large datasets.

Two independent reductions keep the embedded payload bounded and the chart
readable:

* **Row cap** — the data embedded in the page (used by *both* the chart and the
  table) is capped to ``max_rows``. Chart and table therefore always show the
  same rows, so selecting a point reliably highlights its table row.
* **Top-N** (optional) — for categorical charts, keep the ``top_n`` largest
  categories and aggregate the rest into an "Autres" bucket. This is a *summary*
  view, so row-to-point mapping is disabled while it is active.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .chart_selector import _BAR_TYPES, ChartPlan, ChartType

DEFAULT_MAX_ROWS = 5000
OTHERS_LABEL = "Autres"

# Charts whose x axis is a discrete category and can be top-N reduced.
_CATEGORICAL_CHARTS = _BAR_TYPES | {ChartType.PIE}


@dataclass
class Prepared:
    """Result of :func:`prepare_data`."""

    chart_df: pd.DataFrame
    table_df: pd.DataFrame
    map_selection: bool
    warnings: list[str] = field(default_factory=list)
    total_rows: int = 0
    table_truncated: bool = False
    chart_aggregated: bool = False


def prepare_data(
    df: pd.DataFrame,
    plan: ChartPlan,
    max_rows: int = DEFAULT_MAX_ROWS,
    top_n: int | None = None,
) -> Prepared:
    """Apply row-cap and optional top-N reductions for the given plan."""
    total = len(df)
    warnings: list[str] = []

    # Row cap: chart and table share the same (possibly truncated) rows.
    display_df = df
    table_truncated = False
    if total > max_rows:
        display_df = df.head(max_rows).copy()
        table_truncated = True
        warnings.append(
            f"Données volumineuses : seules les {max_rows} premières lignes "
            f"sur {total} sont affichées et exportables."
        )

    # Row-to-point mapping is meaningful only when chart and table are 1:1.
    map_selection = plan.chart_type is not ChartType.HISTOGRAM
    chart_df = display_df
    chart_aggregated = False

    if (
        top_n is not None
        and top_n > 0
        and plan.chart_type in _CATEGORICAL_CHARTS
        and plan.x is not None
    ):
        chart_df, reduced = _top_n_aggregate(display_df, plan, top_n)
        if reduced:
            chart_aggregated = True
            map_selection = False  # aggregated categories no longer map to rows
            warnings.append(
                f"Graphique : {top_n} principales catégories de '{plan.x}' "
                f"conservées, le reste regroupé dans « {OTHERS_LABEL} »."
            )

    return Prepared(
        chart_df=chart_df,
        table_df=display_df,
        map_selection=map_selection,
        warnings=warnings,
        total_rows=total,
        table_truncated=table_truncated,
        chart_aggregated=chart_aggregated,
    )


def _top_n_aggregate(
    df: pd.DataFrame, plan: ChartPlan, top_n: int
) -> tuple[pd.DataFrame, bool]:
    """Keep the ``top_n`` largest x categories; bucket the rest into "Autres".

    Returns the reduced DataFrame and a flag indicating whether any aggregation
    actually happened (False when there were already <= top_n categories).
    """
    assert plan.x is not None
    x, measure = plan.x, plan.y[0]

    work = df.copy()
    work["__m"] = pd.to_numeric(work[measure], errors="coerce")
    totals = work.groupby(x, dropna=False)["__m"].sum().sort_values(ascending=False)
    if len(totals) <= top_n:
        return df, False

    kept = list(totals.head(top_n).index)
    kept_set = set(kept)
    work["__x"] = work[x].map(lambda v: v if v in kept_set else OTHERS_LABEL)
    order = kept + [OTHERS_LABEL]

    group_cols = ["__x"] + ([plan.group_by] if plan.group_by else [])
    agg = work.groupby(group_cols, dropna=False)["__m"].sum().reset_index()
    agg = agg.rename(columns={"__x": x, "__m": measure})

    # Restore a sensible category order (largest first, "Autres" last).
    agg[x] = pd.Categorical(agg[x], categories=order, ordered=True)
    sort_cols = [x] + ([plan.group_by] if plan.group_by else [])
    agg = agg.sort_values(sort_cols).reset_index(drop=True)
    agg[x] = agg[x].astype(str)

    out_cols = [x] + ([plan.group_by] if plan.group_by else []) + [measure]
    return agg[out_cols], True


def build_summary(plan: ChartPlan, prepared: Prepared) -> str:
    """A short, model-readable text summary returned alongside the UI.

    Useful when the host cannot render mcp-ui, and so the model still has
    something to reason about and chain on.
    """
    type_labels = {
        ChartType.BAR: "barres",
        ChartType.GROUPED_BAR: "barres groupées",
        ChartType.STACKED_BAR: "barres empilées",
        ChartType.LINE: "courbe",
        ChartType.AREA: "aire",
        ChartType.SCATTER: "nuage de points",
        ChartType.PIE: "camembert",
        ChartType.HISTOGRAM: "histogramme",
    }
    label = type_labels.get(plan.chart_type, plan.chart_type.value)

    parts = [f"Graphique généré : {label}"]
    if plan.x:
        parts.append(f"axe « {plan.x} »")
    if plan.y:
        parts.append(f"mesure(s) {', '.join(plan.y)}")
    if plan.group_by:
        parts.append(f"réparti par « {plan.group_by} »")

    shown = len(prepared.table_df)
    rows_info = (
        f"{shown} lignes affichées sur {prepared.total_rows}"
        if prepared.table_truncated
        else f"{prepared.total_rows} lignes"
    )

    summary = ". ".join([", ".join(parts), rows_info])
    if prepared.warnings:
        summary += ". " + " ".join(prepared.warnings)
    return summary + ". Le tableau est exportable en CSV et Excel dans le second onglet."
