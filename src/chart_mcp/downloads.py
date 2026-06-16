"""Server-side file generation for the table download buttons.

The chart UI runs in an iframe sandboxed with ``allow-scripts`` only, so a
browser ``<a download>`` is blocked. Instead the buttons emit an mcp-ui ``link``
action pointing at one of these endpoints; the host opens the URL outside the
sandbox and the browser downloads the file (proper ``Content-Disposition``).

Files are built once at render time and cached in memory under a short-lived
token (bounded size + TTL) so the GET endpoints stay cheap and stateless-ish.
"""

from __future__ import annotations

import io
import re
import secrets
import time
from collections import OrderedDict
from typing import TypedDict

import pandas as pd

MAX_ENTRIES = 64
TTL_SECONDS = 3600

CSV_MIME = "text/csv; charset=utf-8"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Entry(TypedDict):
    csv: bytes
    xlsx: bytes
    name: str
    ts: float


_CACHE: "OrderedDict[str, _Entry]" = OrderedDict()


def _safe_name(title: str) -> str:
    name = re.sub(r"[^\w.-]+", "_", title or "data").strip("_")[:60]
    return name or "data"


def _evict() -> None:
    now = time.time()
    for key in [k for k, v in _CACHE.items() if now - v["ts"] > TTL_SECONDS]:
        _CACHE.pop(key, None)
    while len(_CACHE) > MAX_ENTRIES:
        _CACHE.popitem(last=False)


def build_csv(df: pd.DataFrame) -> bytes:
    """UTF-8 CSV with a BOM so Excel opens accents correctly."""
    return ("\ufeff" + df.to_csv(index=False)).encode("utf-8")


def build_xlsx(df: pd.DataFrame) -> bytes:
    """Real .xlsx workbook (single 'Données' sheet)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Données")
    return buf.getvalue()


def register(df: pd.DataFrame, title: str) -> str:
    """Build CSV + XLSX for ``df`` and cache them under a fresh token."""
    token = secrets.token_urlsafe(12)
    _CACHE[token] = {
        "csv": build_csv(df),
        "xlsx": build_xlsx(df),
        "name": _safe_name(title),
        "ts": time.time(),
    }
    _evict()
    return token


def get(token: str) -> _Entry | None:
    """Return a cached entry, or None if unknown/expired."""
    entry = _CACHE.get(token)
    if entry is None:
        return None
    if time.time() - entry["ts"] > TTL_SECONDS:
        _CACHE.pop(token, None)
        return None
    return entry
