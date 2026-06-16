"""``chart_mcp`` — an MCP server that turns tabular data into an interactive,
auto-typed chart rendered through the mcp-ui standard.

The single ``render_chart`` tool accepts a list of records, picks the most
appropriate chart type, and returns a short text summary plus an mcp-ui
``UIResource`` containing a two-tab interface (interactive chart + downloadable
data table).
"""

from __future__ import annotations

import argparse
import os
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, TextContent
from mcp_ui_server import create_ui_resource
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.requests import Request
from starlette.responses import Response

from .assets import ASSET_FILES, read_vendor, resolve_asset_tags
from .chart_selector import ChartType, select_chart
from .data_reduce import DEFAULT_MAX_ROWS, build_summary, prepare_data
from .data_utils import records_to_dataframe
from . import downloads
from .ui_builder import build_chart_html

def _build_transport_security() -> TransportSecuritySettings:
    """Configure DNS-rebinding protection from the environment.

    The MCP streamable-HTTP transport rejects requests whose ``Host`` header is
    not allow-listed (returns 421). FastMCP only auto-allows loopback, so a
    server bound to 0.0.0.0 and reached via a real hostname must declare it.

    ``CHART_MCP_ALLOWED_HOSTS`` (comma-separated ``host[:port]`` entries):
      * unset  -> protection disabled (reachable on any hostname; intended for
                  internal networks / behind a reverse proxy).
      * "*"    -> protection disabled explicitly.
      * a list -> protection enabled, locked to those hosts. A ``:*`` suffix
                  matches any port, e.g. ``app.internal:*``.
    """
    raw = os.getenv("CHART_MCP_ALLOWED_HOSTS", "").strip()
    if raw == "" or raw == "*":
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    origins: list[str] = []
    for h in hosts:
        origins += [f"http://{h}", f"https://{h}"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


mcp = FastMCP("chart_mcp", transport_security=_build_transport_security())

# Base for mcp-ui URIs. A unique suffix is appended per render so multiple
# charts in one conversation do not share a URI (hosts key resources by URI,
# which otherwise makes a new chart overwrite the previous one).
_UI_URI = "ui://chart-mcp/render"

# In-memory cache of vendored asset sources (served over /assets/).
_ASSET_CACHE: dict[str, str] = {}


def _public_base_url() -> str | None:
    """Browser-reachable base URL of this server, for download links.

    Order: ``CHART_MCP_PUBLIC_URL`` -> the origin of ``CHART_MCP_ASSETS`` when it
    is an http(s) URL -> None (downloads then fall back to in-iframe generation,
    which the mcp-ui sandbox may block).
    """
    pub = os.getenv("CHART_MCP_PUBLIC_URL", "").strip().rstrip("/")
    if pub:
        return pub
    assets = os.getenv("CHART_MCP_ASSETS", "").strip().rstrip("/")
    if assets.startswith("http"):
        return assets[: -len("/assets")] if assets.endswith("/assets") else assets
    return None


class RenderChartInput(BaseModel):
    """Validated input for the ``render_chart`` tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    data: list[dict[str, Any]] = Field(
        ...,
        description=(
            "The dataset as a list of row objects, e.g. "
            "[{'month': 'Jan', 'sales': 120}, {'month': 'Feb', 'sales': 150}]. "
            "Each object is one row; keys are column names. Must be non-empty."
        ),
        min_length=1,
    )
    title: str = Field(
        default="Chart",
        description="Heading shown above the chart (e.g. 'Monthly sales 2025').",
        max_length=160,
    )
    chart_type: str = Field(
        default="auto",
        description=(
            "Chart type. Use 'auto' (default) to let the server choose the best "
            "fit, or force one of: bar, grouped_bar, stacked_bar, line, area, "
            "scatter, pie, histogram."
        ),
    )
    x: str | None = Field(
        default=None,
        description=(
            "Optional column to use for the x axis / category / pie label. "
            "If omitted, the server infers it (a date or categorical column)."
        ),
    )
    y: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of numeric columns to plot as series. If omitted, all "
            "numeric columns (other than x) are used."
        ),
    )
    group_by: str | None = Field(
        default=None,
        description=(
            "Optional second categorical column for grouped/stacked bars. Each of "
            "its values becomes a bar series, split across the x categories (the "
            "measure is summed per cell). Inferred automatically when a second "
            "categorical column is present and a single measure is plotted."
        ),
    )
    stacked: bool = Field(
        default=False,
        description="Stack bar/area series instead of placing them side by side.",
    )
    max_rows: int = Field(
        default=DEFAULT_MAX_ROWS,
        ge=10,
        le=200_000,
        description=(
            "Maximum number of rows embedded in the page (chart + table share "
            "these rows). Larger datasets are truncated with a visible notice."
        ),
    )
    top_n: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description=(
            "For categorical charts, keep only the N largest categories and "
            "aggregate the rest into an 'Autres' bucket. Off by default."
        ),
    )

    @field_validator("chart_type")
    @classmethod
    def _validate_chart_type(cls, v: str) -> str:
        allowed = {"auto"} | {t.value for t in ChartType}
        if v not in allowed:
            raise ValueError(f"chart_type must be one of {sorted(allowed)}, got '{v}'.")
        return v


@mcp.tool(
    name="render_chart",
    annotations={
        "title": "Render data as an interactive chart",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def render_chart(params: RenderChartInput) -> list[ContentBlock]:
    """Render a dataset as an interactive, auto-typed chart (mcp-ui resource).

    The server analyses the columns and selects the most suitable chart type
    when ``chart_type='auto'`` (date axis -> line/area, a second categorical
    column -> grouped bars, few categories -> pie, categorical -> bar, two
    numerics -> scatter, otherwise -> histogram). Large datasets are capped to
    ``max_rows`` (with a notice); ``top_n`` optionally keeps only the largest
    categories. The returned UI has two tabs: an interactive ECharts chart
    (legend toggle, zoom, rubber-band selection) and a data table downloadable
    as CSV or Excel.

    Args:
        params (RenderChartInput): Validated input containing:
            - data (list[dict]): rows of the dataset (required, non-empty).
            - title (str): chart heading.
            - chart_type (str): 'auto' or an explicit type.
            - x (str | None): pinned x/category column.
            - y (list[str] | None): pinned numeric series columns.
            - group_by (str | None): second categorical column for grouped/stacked bars.
            - stacked (bool): stack series instead of side-by-side.
            - max_rows (int): row cap for the embedded payload.
            - top_n (int | None): keep only the N largest categories.

    Returns:
        list[ContentBlock]: A text summary followed by a single mcp-ui
        ``rawHtml`` resource (blob-encoded) rendering the two-tab interface.

    Raises:
        ValueError: If the data is malformed, a pinned column is missing, or no
            numeric column is available to plot.
    """
    df = records_to_dataframe(params.data)

    requested = None if params.chart_type == "auto" else ChartType(params.chart_type)
    plan = select_chart(
        df,
        requested_type=requested,
        x=params.x,
        y=params.y,
        group_by=params.group_by,
        stacked=params.stacked,
    )

    prepared = prepare_data(df, plan, max_rows=params.max_rows, top_n=params.top_n)

    # Build download links when a browser-reachable base URL is known; otherwise
    # the UI falls back to (sandbox-limited) in-iframe file generation.
    base = _public_base_url()
    download_urls = None
    if base is not None:
        token = downloads.register(prepared.table_df, params.title)
        download_urls = {
            "csv": f"{base}/download/{token}/csv",
            "xlsx": f"{base}/download/{token}/xlsx",
        }

    html = build_chart_html(
        prepared.chart_df,
        plan,
        params.title,
        table_df=prepared.table_df,
        asset_tags=resolve_asset_tags(),
        map_selection=prepared.map_selection,
        warnings=prepared.warnings,
        download_urls=download_urls,
    )

    resource = create_ui_resource(
        {
            "uri": f"{_UI_URI}/{uuid.uuid4().hex}",
            "content": {"type": "rawHtml", "htmlString": html},
            # blob (base64) is recommended for large HTML payloads.
            "encoding": "blob",
        }
    )
    summary = TextContent(type="text", text=build_summary(plan, prepared))
    return [summary, resource]


@mcp.custom_route("/assets/{filename}", methods=["GET"])
async def serve_asset(request: Request) -> Response:
    """Serve the vendored ECharts/SheetJS files (for ``CHART_MCP_ASSETS=<url>``).

    Lets the server host the JS itself so air-gapped hosts need no CDN: point
    ``CHART_MCP_ASSETS`` at ``http://<this-server>/assets``.
    """
    filename = request.path_params["filename"]
    key = next((k for k, name in ASSET_FILES.items() if name == filename), None)
    if key is None:
        return Response("Not found", status_code=404)
    if key not in _ASSET_CACHE:
        _ASSET_CACHE[key] = read_vendor(key)
    return Response(
        _ASSET_CACHE[key],
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@mcp.custom_route("/download/{token}/{kind}", methods=["GET"])
async def serve_download(request: Request) -> Response:
    """Serve a generated CSV/XLSX file with an attachment disposition.

    Downloads cannot happen inside the ``allow-scripts`` sandbox, so the UI
    routes its download buttons here via an mcp-ui ``link`` action.
    """
    token = request.path_params["token"]
    kind = request.path_params["kind"]
    entry = downloads.get(token)
    if entry is None or kind not in ("csv", "xlsx"):
        return Response("Not found", status_code=404)

    if kind == "csv":
        data, media_type, ext = entry["csv"], downloads.CSV_MIME, "csv"
    else:
        data, media_type, ext = entry["xlsx"], downloads.XLSX_MIME, "xlsx"

    return Response(
        data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{entry["name"]}.{ext}"'},
    )


def main() -> None:
    """CLI entry point. Defaults to stdio; ``--transport http`` for web hosts."""
    parser = argparse.ArgumentParser(description="chart_mcp — interactive chart MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport: 'stdio' for local clients, 'http' (streamable HTTP) for remote.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host for HTTP transport.")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP transport.")
    args = parser.parse_args()

    if args.transport == "http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        # The MCP endpoint path (default "/mcp"). Override to match the client
        # URL, e.g. CHART_MCP_HTTP_PATH=/mcp-builder.
        http_path = os.getenv("CHART_MCP_HTTP_PATH", "").strip()
        if http_path:
            mcp.settings.streamable_http_path = http_path
        ts = mcp.settings.transport_security
        # Printed to stdout so it is visible in `docker logs` and confirms which
        # build is running (helps diagnose stale images / 421 Host errors).
        print(
            f"[chart-mcp] DNS-rebinding protection="
            f"{getattr(ts, 'enable_dns_rebinding_protection', None)} "
            f"allowed_hosts={getattr(ts, 'allowed_hosts', None)} "
            f"path={mcp.settings.streamable_http_path}",
            flush=True,
        )
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
