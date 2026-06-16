"""Resolve how the front-end loads its JS dependencies (ECharts, SheetJS).

The chart UI runs inside the host's sandboxed iframe, so the ``<script>`` tags
must reference an absolute URL the iframe can reach — a relative path would
resolve against the host page, not this server. Three modes are supported via
the ``CHART_MCP_ASSETS`` environment variable:

* ``cdn`` (default)  — jsDelivr URLs. Zero-config, but needs internet egress.
* ``inline``         — the vendored files are embedded directly in the HTML.
                       Fully self-contained / air-gap friendly (larger payload).
* any URL/base path  — e.g. ``http://chart-mcp:8000/assets``. The two vendored
                       files are referenced from there. The server can host them
                       itself via its ``/assets/{filename}`` route (HTTP transport).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

VENDOR_DIR = Path(__file__).parent / "vendor"
ENV_VAR = "CHART_MCP_ASSETS"

# Logical name -> vendored filename (also the path served under /assets/).
ASSET_FILES = {
    "echarts": "echarts.min.js",
    "xlsx": "xlsx.full.min.js",
}

_CDN = {
    "echarts": "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
    "xlsx": "https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js",
}

_CLOSING_SCRIPT = re.compile(r"</script", re.IGNORECASE)


@dataclass(frozen=True)
class AssetTags:
    """The two ``<script>`` tags to inject into the page."""

    echarts: str
    xlsx: str


def vendor_path(key: str) -> Path:
    """Absolute path to a vendored asset file."""
    return VENDOR_DIR / ASSET_FILES[key]


def read_vendor(key: str) -> str:
    """Read a vendored asset's source."""
    return vendor_path(key).read_text(encoding="utf-8")


def _src_tag(url: str) -> str:
    return f'<script src="{url}"></script>'


def _inline_tag(code: str) -> str:
    # Neutralise any literal "</script" inside the library source so it cannot
    # terminate the inline block early. "<\/script" is identical inside JS.
    safe = _CLOSING_SCRIPT.sub(r"<\\/script", code)
    return f"<script>{safe}</script>"


def resolve_asset_tags(mode: str | None = None) -> AssetTags:
    """Build the script tags for the configured asset mode.

    Args:
        mode: Override for the ``CHART_MCP_ASSETS`` env var. ``None`` reads the
            environment (defaulting to ``cdn``).

    Returns:
        :class:`AssetTags` with the echarts and xlsx ``<script>`` tags.
    """
    mode = (mode if mode is not None else os.environ.get(ENV_VAR, "cdn")).strip() or "cdn"

    if mode == "cdn":
        return AssetTags(_src_tag(_CDN["echarts"]), _src_tag(_CDN["xlsx"]))
    if mode == "inline":
        return AssetTags(_inline_tag(read_vendor("echarts")), _inline_tag(read_vendor("xlsx")))

    base = mode.rstrip("/")
    return AssetTags(
        _src_tag(f"{base}/{ASSET_FILES['echarts']}"),
        _src_tag(f"{base}/{ASSET_FILES['xlsx']}"),
    )
