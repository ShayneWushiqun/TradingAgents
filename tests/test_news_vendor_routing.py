from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import DataVendorUnavailable, route_to_vendor


def test_news_vendor_order_falls_back_from_akshare_to_tavily(monkeypatch):
    import tradingagents.dataflows.interface as interface

    calls = []

    def unavailable_akshare(*args, **kwargs):
        calls.append("akshare")
        raise DataVendorUnavailable("akshare rate limited")

    def tavily_news(*args, **kwargs):
        calls.append("tavily")
        return "## Tavily News\nA股新闻搜索结果"

    def tushare_fallback(*args, **kwargs):
        calls.append("tushare")
        return "## Tushare Fallback"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "akshare": unavailable_akshare,
            "tavily": tavily_news,
            "tushare": tushare_fallback,
        },
    )
    set_config({"data_vendors": {"news_data": "akshare,tavily,tushare"}})

    result = route_to_vendor("get_news", "600519.SH", "2026-04-23", "2026-04-30")

    assert result.startswith("## Tavily News")
    assert calls == ["akshare", "tavily"]


def test_news_vendor_order_returns_tushare_fallback_when_paid_sources_unavailable(monkeypatch):
    import tradingagents.dataflows.interface as interface

    calls = []

    def unavailable(vendor):
        def _raise(*args, **kwargs):
            calls.append(vendor)
            raise DataVendorUnavailable(f"{vendor} unavailable")

        return _raise

    def tushare_fallback(*args, **kwargs):
        calls.append("tushare")
        return "## Tushare Fallback\n新闻数据不可用，降级为资金流与基本面说明。"

    monkeypatch.setitem(
        interface.VENDOR_METHODS,
        "get_news",
        {
            "akshare": unavailable("akshare"),
            "tavily": unavailable("tavily"),
            "tushare": tushare_fallback,
        },
    )
    set_config({"data_vendors": {"news_data": "akshare,tavily,tushare"}})

    result = route_to_vendor("get_news", "600519.SH", "2026-04-23", "2026-04-30")

    assert "降级为资金流与基本面说明" in result
    assert calls == ["akshare", "tavily", "tushare"]
