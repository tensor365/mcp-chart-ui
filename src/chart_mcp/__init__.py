"""chart_mcp — MCP server that renders tabular data as interactive charts."""

from .assets import AssetTags, resolve_asset_tags
from .chart_selector import ChartPlan, ChartType, select_chart
from .data_reduce import Prepared, build_summary, prepare_data
from .data_utils import ColumnKind, infer_column_kinds, records_to_dataframe
from .ui_builder import build_chart_html

__all__ = [
    "AssetTags",
    "ChartPlan",
    "ChartType",
    "ColumnKind",
    "Prepared",
    "build_chart_html",
    "build_summary",
    "infer_column_kinds",
    "prepare_data",
    "records_to_dataframe",
    "resolve_asset_tags",
    "select_chart",
]

__version__ = "0.2.0"
