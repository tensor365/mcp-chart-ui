"""Automatic chart-type selection.

Given a DataFrame and (optionally) user-pinned x / y columns, decide which chart
type best represents the data and resolve which columns play which role. The
rules are deterministic and explained via a human-readable ``reasoning`` string
so the choice is transparent (and easy to unit-test).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from .data_utils import ColumnKind, infer_column_kinds

# Above this many slices a pie chart becomes unreadable -> fall back to bar.
_MAX_PIE_SLICES = 6


class ChartType(str, Enum):
    """Supported chart types."""

    BAR = "bar"
    GROUPED_BAR = "grouped_bar"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    AREA = "area"
    SCATTER = "scatter"
    PIE = "pie"
    HISTOGRAM = "histogram"


# Bar-family types share the same builder; only grouping/stacking differs.
_BAR_TYPES = frozenset({ChartType.BAR, ChartType.GROUPED_BAR, ChartType.STACKED_BAR})


@dataclass(frozen=True)
class ChartPlan:
    """Resolved plan describing how to render the data.

    ``group_by`` is the optional second categorical dimension used to split a
    single measure into multiple bar series (long-form pivot). ``stacked`` marks
    a bar/area plan as stacked rather than side-by-side.
    """

    chart_type: ChartType
    x: str | None
    y: list[str]
    reasoning: str
    group_by: str | None = None
    stacked: bool = False


def _columns_by_kind(kinds: dict[str, ColumnKind]) -> dict[ColumnKind, list[str]]:
    grouped: dict[ColumnKind, list[str]] = {k: [] for k in ColumnKind}
    for col, kind in kinds.items():
        grouped[kind].append(col)
    return grouped


def select_chart(
    df: pd.DataFrame,
    requested_type: ChartType | None = None,
    x: str | None = None,
    y: list[str] | None = None,
    group_by: str | None = None,
    stacked: bool = False,
) -> ChartPlan:
    """Pick a chart type and resolve x / y / group roles.

    Args:
        df: The dataset.
        requested_type: If provided, this type is honoured and only role
            resolution is performed (the caller explicitly overrode auto mode).
        x: Optional pinned column for the x axis / category / pie label.
        y: Optional pinned list of numeric value columns (series).
        group_by: Optional second categorical column used to split a single
            measure into multiple bar series (long-form pivot). If omitted in a
            grouped/stacked bar context, it is inferred from the data.
        stacked: Force stacked bars/areas instead of side-by-side.

    Returns:
        A :class:`ChartPlan`.

    Raises:
        ValueError: If pinned columns do not exist, or no numeric column is
            available to plot.
    """
    kinds = infer_column_kinds(df)
    pinned_cols = [c for c in ([x] if x else []) + (y or []) + ([group_by] if group_by else []) if c]
    for pinned in pinned_cols:
        if pinned not in kinds:
            raise ValueError(f"Column '{pinned}' is not present in the data.")

    grouped = _columns_by_kind(kinds)
    numeric = grouped[ColumnKind.NUMERIC]
    datetime_cols = grouped[ColumnKind.DATETIME]
    categorical = grouped[ColumnKind.CATEGORICAL] + grouped[ColumnKind.BOOLEAN]

    if not numeric:
        raise ValueError("At least one numeric column is required to draw a chart.")

    # Resolve y: pinned > all numeric columns not used as x.
    resolved_y = list(y) if y else [c for c in numeric if c != x]
    if not resolved_y:
        resolved_y = [c for c in numeric if c != x] or numeric

    # Resolve a default x candidate when not pinned.
    resolved_x = x
    if resolved_x is None:
        if datetime_cols:
            resolved_x = datetime_cols[0]
        elif categorical:
            resolved_x = categorical[0]
        elif len(numeric) >= 2:
            # No category/time: use the first numeric as the x axis (scatter).
            resolved_x = numeric[0]
            resolved_y = [c for c in numeric if c != resolved_x] or [numeric[0]]

    # Categorical columns still free to act as a grouping dimension.
    other_categoricals = [c for c in categorical if c not in (resolved_x, group_by)]

    def _resolve_bar(chart_type: ChartType) -> ChartPlan:
        """Resolve grouping/stacking for any bar-family chart type."""
        is_stacked = stacked or chart_type is ChartType.STACKED_BAR
        g = group_by
        # Infer the grouping column for grouped/stacked bars on a single measure.
        if g is None and chart_type in (ChartType.GROUPED_BAR, ChartType.STACKED_BAR):
            if len(resolved_y) <= 1 and other_categoricals:
                g = other_categoricals[0]
        bits = [f"a {'stacked' if is_stacked else 'grouped'} bar chart"]
        if g:
            bits.append(f"split by '{g}'")
        reason = (
            f"'{resolved_x}' on the x axis with {', '.join(resolved_y)} as "
            f"{' '.join(bits)}."
        )
        return ChartPlan(chart_type, resolved_x, resolved_y, reason, group_by=g, stacked=is_stacked)

    # If the caller forced a type, honour it (roles already resolved above).
    if requested_type is not None:
        if requested_type in _BAR_TYPES:
            return _resolve_bar(requested_type)
        return ChartPlan(
            chart_type=requested_type,
            x=resolved_x,
            y=resolved_y,
            reasoning=f"Chart type '{requested_type.value}' was explicitly requested.",
            group_by=group_by,
            stacked=stacked,
        )

    x_kind = kinds.get(resolved_x) if resolved_x else None

    # Rule 1: a time axis -> trend chart.
    if x_kind is ColumnKind.DATETIME:
        kind = ChartType.AREA if len(resolved_y) == 1 else ChartType.LINE
        return ChartPlan(
            kind,
            resolved_x,
            resolved_y,
            f"'{resolved_x}' is a date/time column, so a {kind.value} chart shows the "
            f"trend of {', '.join(resolved_y)} over time.",
            stacked=stacked,
        )

    # Rule 2: categorical x.
    if x_kind in (ColumnKind.CATEGORICAL, ColumnKind.BOOLEAN):
        # Rule 2a: a second categorical dimension + a single measure -> grouped
        # (or stacked) bars, so the second dimension is not silently dropped.
        if len(resolved_y) == 1 and other_categoricals:
            group_col = other_categoricals[0]
            kind = ChartType.STACKED_BAR if stacked else ChartType.GROUPED_BAR
            verb = "stacked" if stacked else "grouped"
            return ChartPlan(
                kind,
                resolved_x,
                resolved_y,
                f"'{resolved_x}' and '{group_col}' are both categorical, so a {verb} bar "
                f"chart compares {resolved_y[0]} across '{resolved_x}', split by '{group_col}'.",
                group_by=group_col,
                stacked=stacked,
            )

        # Rule 2b: a single measure over few non-negative categories -> pie.
        n_categories = int(df[resolved_x].nunique(dropna=True))
        if not stacked and len(resolved_y) == 1 and 2 <= n_categories <= _MAX_PIE_SLICES:
            non_negative = bool((df[resolved_y[0]].dropna() >= 0).all())
            if non_negative:
                return ChartPlan(
                    ChartType.PIE,
                    resolved_x,
                    resolved_y,
                    f"'{resolved_x}' has {n_categories} non-negative categories, well "
                    f"suited to a pie chart showing each share of {resolved_y[0]}.",
                )

        # Rule 2c: otherwise a bar chart (multiple measures render side-by-side;
        # stacked when requested).
        kind = ChartType.STACKED_BAR if stacked and len(resolved_y) > 1 else ChartType.BAR
        return ChartPlan(
            kind,
            resolved_x,
            resolved_y,
            f"'{resolved_x}' is categorical, so a bar chart compares "
            f"{', '.join(resolved_y)} across categories.",
            stacked=stacked,
        )

    # Rule 3: numeric x with numeric y -> scatter (relationship between measures).
    if x_kind is ColumnKind.NUMERIC:
        return ChartPlan(
            ChartType.SCATTER,
            resolved_x,
            resolved_y,
            f"Both '{resolved_x}' and {', '.join(resolved_y)} are numeric, so a scatter "
            f"plot reveals their relationship.",
        )

    # Rule 4: nothing to put on x -> distribution of the first numeric column.
    return ChartPlan(
        ChartType.HISTOGRAM,
        None,
        resolved_y[:1],
        f"No categorical or time axis is available, so a histogram shows the "
        f"distribution of {resolved_y[0]}.",
    )
