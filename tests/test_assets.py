"""Unit tests for chart_mcp.assets."""

from chart_mcp.assets import (
    ASSET_FILES,
    AssetTags,
    read_vendor,
    resolve_asset_tags,
    vendor_path,
)


def test_cdn_mode_uses_jsdelivr_src():
    tags = resolve_asset_tags("cdn")
    assert isinstance(tags, AssetTags)
    assert "cdn.jsdelivr.net" in tags.echarts
    assert "<script src=" in tags.echarts
    assert "xlsx" in tags.xlsx


def test_default_mode_is_cdn():
    # No env override -> defaults to cdn.
    tags = resolve_asset_tags()
    assert "cdn.jsdelivr.net" in tags.echarts


def test_url_mode_builds_src_from_base():
    tags = resolve_asset_tags("http://chart-mcp:8000/assets")
    assert tags.echarts == '<script src="http://chart-mcp:8000/assets/echarts.min.js"></script>'
    assert tags.xlsx == '<script src="http://chart-mcp:8000/assets/xlsx.full.min.js"></script>'


def test_url_mode_strips_trailing_slash():
    tags = resolve_asset_tags("https://host/assets/")
    assert "https://host/assets/echarts.min.js" in tags.echarts


def test_inline_mode_embeds_source():
    tags = resolve_asset_tags("inline")
    assert tags.echarts.startswith("<script>")
    assert tags.echarts.endswith("</script>")
    assert "<script src=" not in tags.echarts  # not an external load
    # The vendored library source should actually be present.
    assert len(tags.echarts) > 100_000


def test_inline_mode_neutralises_closing_script():
    # Any literal "</script" in the library must be escaped so it can't break out.
    tags = resolve_asset_tags("inline")
    assert "</script>" == tags.echarts[-9:]  # only the real terminator
    assert "</script" not in tags.echarts[:-9].replace("<\\/script", "")


def test_vendored_files_exist():
    for key in ASSET_FILES:
        assert vendor_path(key).exists()
        assert read_vendor(key)  # non-empty
