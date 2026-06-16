"""Unit tests for chart_mcp.server (tool wiring + input validation)."""

import base64

import pytest
from mcp.types import EmbeddedResource, TextContent
from pydantic import ValidationError

from chart_mcp.server import RenderChartInput, render_chart

SAMPLE = [
    {"month": "Jan", "sales": 120, "returns": 12},
    {"month": "Feb", "sales": 150, "returns": 9},
    {"month": "Mar", "sales": 90, "returns": 20},
]


def _resource(out):
    """Extract the embedded UI resource from the tool output list."""
    res = [b for b in out if isinstance(b, EmbeddedResource)]
    assert len(res) == 1
    return res[0].model_dump(by_alias=True)["resource"]


def _html(out):
    res = _resource(out)
    if res.get("blob"):
        return base64.b64decode(res["blob"]).decode("utf-8")
    return res["text"]


def test_input_rejects_unknown_chart_type():
    with pytest.raises(ValidationError):
        RenderChartInput(data=SAMPLE, chart_type="bubble")


def test_input_rejects_empty_data():
    with pytest.raises(ValidationError):
        RenderChartInput(data=[])


def test_input_accepts_auto_default():
    params = RenderChartInput(data=SAMPLE)
    assert params.chart_type == "auto"
    assert params.title == "Chart"
    assert params.max_rows == 5000
    assert params.top_n is None


def test_output_has_text_summary_and_resource():
    out = render_chart(RenderChartInput(data=SAMPLE, title="Sales"))
    assert isinstance(out, list) and len(out) == 2
    assert isinstance(out[0], TextContent)
    assert isinstance(out[1], EmbeddedResource)
    # Summary should mention row count and export availability.
    assert "3 lignes" in out[0].text
    assert "CSV" in out[0].text and "Excel" in out[0].text


def test_resource_uri_and_mimetype():
    out = render_chart(RenderChartInput(data=SAMPLE, title="Sales"))
    res = _resource(out)
    assert str(res["uri"]).startswith("ui://chart-mcp/render")
    assert res["mimeType"] == "text/html"


def test_resource_html_contains_ui():
    html = _html(render_chart(RenderChartInput(data=SAMPLE, title="Sales")))
    assert "📊 Graphique" in html
    assert "▦ Données" in html
    assert "Sales" in html


def test_render_chart_with_explicit_type_and_pins():
    params = RenderChartInput(
        data=SAMPLE, title="Sales", chart_type="bar", x="month", y=["sales"]
    )
    out = render_chart(params)
    assert len(out) == 2


def test_render_chart_raises_without_numeric_column():
    params = RenderChartInput(data=[{"a": "x"}, {"a": "y"}])
    with pytest.raises(ValueError):
        render_chart(params)


def test_max_rows_truncates_and_warns():
    data = [{"cat": f"C{i}", "v": i} for i in range(50)]
    out = render_chart(RenderChartInput(data=data, max_rows=10, chart_type="bar"))
    assert "10 premières lignes sur 50" in out[0].text
    html = _html(out)
    assert "Données volumineuses" in html  # warning banner content present


def test_top_n_aggregation_mentions_others():
    data = [{"cat": f"C{i}", "v": 100 - i} for i in range(20)]
    out = render_chart(RenderChartInput(data=data, chart_type="bar", top_n=5))
    assert "Autres" in out[0].text


GROUPED_DATA = [
    {"region": "North", "product": "A", "sales": 10},
    {"region": "North", "product": "B", "sales": 5},
    {"region": "South", "product": "A", "sales": 7},
    {"region": "South", "product": "B", "sales": 3},
]


def test_input_accepts_grouped_and_stacked_types():
    RenderChartInput(data=GROUPED_DATA, chart_type="grouped_bar")
    RenderChartInput(data=GROUPED_DATA, chart_type="stacked_bar")


def test_render_grouped_bar_end_to_end():
    out = render_chart(RenderChartInput(data=GROUPED_DATA, chart_type="grouped_bar", title="By region"))
    assert len(out) == 2


def test_render_with_group_by_and_stacked_params():
    params = RenderChartInput(
        data=GROUPED_DATA, title="Stacked", stacked=True, group_by="product", x="region"
    )
    out = render_chart(params)
    assert len(out) == 2


def test_invalid_group_by_raises():
    params = RenderChartInput(data=GROUPED_DATA, group_by="missing")
    with pytest.raises(ValueError):
        render_chart(params)


def test_invalid_max_rows_rejected():
    with pytest.raises(ValidationError):
        RenderChartInput(data=SAMPLE, max_rows=1)


# --- transport security (DNS-rebinding / Host header) ----------------------

import os as _os

from mcp.server.transport_security import TransportSecurityMiddleware
from chart_mcp.server import _build_transport_security


def _reload_ts(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CHART_MCP_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("CHART_MCP_ALLOWED_HOSTS", value)
    return _build_transport_security()


def test_security_disabled_when_unset(monkeypatch):
    ts = _reload_ts(monkeypatch, None)
    assert ts.enable_dns_rebinding_protection is False


def test_security_disabled_with_star(monkeypatch):
    ts = _reload_ts(monkeypatch, "*")
    assert ts.enable_dns_rebinding_protection is False


def test_security_allows_listed_host(monkeypatch):
    ts = _reload_ts(monkeypatch, "app.internal:*, 10.0.4.10:8013")
    assert ts.enable_dns_rebinding_protection is True
    mw = TransportSecurityMiddleware(ts)
    assert mw._validate_host("app.internal:8013") is True
    assert mw._validate_host("10.0.4.10:8013") is True


def test_security_rejects_unlisted_host(monkeypatch):
    ts = _reload_ts(monkeypatch, "app.internal:*")
    mw = TransportSecurityMiddleware(ts)
    assert mw._validate_host("evil.com:8013") is False
    assert mw._validate_host(None) is False


# --- unique resource URI (multiple charts in one conversation) -------------

def test_each_render_has_unique_uri():
    uri1 = str(_resource(render_chart(RenderChartInput(data=SAMPLE, title="A")))["uri"])
    uri2 = str(_resource(render_chart(RenderChartInput(data=SAMPLE, title="B")))["uri"])
    assert uri1.startswith("ui://chart-mcp/render/")
    assert uri2.startswith("ui://chart-mcp/render/")
    assert uri1 != uri2  # would collide (overwrite) if shared


def test_downloads_activate_with_public_url(monkeypatch):
    monkeypatch.setenv("CHART_MCP_PUBLIC_URL", "http://app.internal:8013")
    page = _html(render_chart(RenderChartInput(data=SAMPLE, title="DL")))
    assert "http://app.internal:8013/download/" in page


def test_no_public_url_no_download_link(monkeypatch):
    monkeypatch.delenv("CHART_MCP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("CHART_MCP_ASSETS", raising=False)
    page = _html(render_chart(RenderChartInput(data=SAMPLE, title="DL")))
    # Falls back to clipboard copy (no server download URL injected).
    assert "/download/" not in page
