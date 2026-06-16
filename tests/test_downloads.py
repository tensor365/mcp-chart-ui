"""Unit tests for chart_mcp.downloads and the download wiring."""

import asyncio

import pandas as pd
from starlette.requests import Request

from chart_mcp import downloads
from chart_mcp.server import _public_base_url, serve_download

DF = pd.DataFrame([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])


def test_build_csv_has_bom_and_rows():
    data = downloads.build_csv(DF)
    text = data.decode("utf-8")
    assert text.startswith("\ufeff")  # BOM for Excel
    assert "a,b" in text
    assert "1,x" in text


def test_build_xlsx_is_valid_workbook():
    import openpyxl
    import io

    data = downloads.build_xlsx(DF)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws.title == "Données"
    assert [c.value for c in ws[1]] == ["a", "b"]


def test_register_and_get_roundtrip():
    token = downloads.register(DF, "My Title")
    entry = downloads.get(token)
    assert entry is not None
    assert entry["name"] == "My_Title"
    assert entry["csv"] and entry["xlsx"]


def test_get_unknown_token_returns_none():
    assert downloads.get("does-not-exist") is None


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(downloads, "MAX_ENTRIES", 5)
    tokens = [downloads.register(DF, f"t{i}") for i in range(8)]
    # Oldest entries evicted; only the last few survive.
    alive = [t for t in tokens if downloads.get(t) is not None]
    assert len(alive) <= 5
    assert tokens[-1] in alive


def test_public_base_from_explicit_env(monkeypatch):
    monkeypatch.setenv("CHART_MCP_PUBLIC_URL", "http://host:8013/")
    assert _public_base_url() == "http://host:8013"


def test_public_base_derived_from_assets_url(monkeypatch):
    monkeypatch.delenv("CHART_MCP_PUBLIC_URL", raising=False)
    monkeypatch.setenv("CHART_MCP_ASSETS", "http://host:8013/assets")
    assert _public_base_url() == "http://host:8013"


def test_public_base_none_when_inline(monkeypatch):
    monkeypatch.delenv("CHART_MCP_PUBLIC_URL", raising=False)
    monkeypatch.setenv("CHART_MCP_ASSETS", "inline")
    assert _public_base_url() is None


def _fake_request(token: str, kind: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/download/{token}/{kind}",
            "headers": [],
            "path_params": {"token": token, "kind": kind},
        }
    )


def test_serve_download_csv_has_attachment_header():
    token = downloads.register(DF, "Sales Report")
    resp = asyncio.run(serve_download(_fake_request(token, "csv")))
    assert resp.status_code == 200
    assert resp.media_type.startswith("text/csv")
    assert 'filename="Sales_Report.csv"' in resp.headers["content-disposition"]


def test_serve_download_xlsx_ok():
    token = downloads.register(DF, "Sales")
    resp = asyncio.run(serve_download(_fake_request(token, "xlsx")))
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.media_type


def test_serve_download_unknown_is_404():
    resp = asyncio.run(serve_download(_fake_request("nope", "csv")))
    assert resp.status_code == 404


def test_serve_download_bad_kind_is_404():
    token = downloads.register(DF, "Sales")
    resp = asyncio.run(serve_download(_fake_request(token, "pdf")))
    assert resp.status_code == 404
