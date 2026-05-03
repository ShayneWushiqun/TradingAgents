import pytest

from tradingagents.dataflows.vendor_errors import DataVendorUnavailable
from tradingagents.web.chat_skills import (
    ChatSkillRouter,
    ExternalDataSkill,
    NewsSearchSkill,
    ReportContextSkill,
    SkillContext,
    TushareDataSkill,
)
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import TaskRegistry


def _context(message: str = "怎么看？") -> SkillContext:
    registry = TaskRegistry()
    task = registry.create(
        AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-30")
    )
    task.status = "completed"
    task.report_sections.update(
        {
            "market_report": "技术面维持强势，成交额温和放大。",
            "fundamentals_report": "基本面稳定，估值需要结合 PE 分位观察。",
            "news_report": "近期新闻无重大利空。",
            "final_trade_decision": "Rating: Hold\n等待更清晰的买点。",
        }
    )
    task.final_decision = task.report_sections["final_trade_decision"]
    return SkillContext(task=task, message=message)


@pytest.mark.unit
def test_router_selects_tushare_for_valuation_and_moneyflow_questions():
    router = ChatSkillRouter()

    assert router.select("资金流怎么看？").name == "tushare_a_share_data"
    assert router.select("PE 和估值压力如何？").name == "tushare_a_share_data"


@pytest.mark.unit
def test_router_selects_news_for_news_announcement_questions():
    router = ChatSkillRouter()

    assert router.select("最近有什么新闻？").name == "a_share_news_search"
    assert router.select("公告有没有利空？").name == "a_share_news_search"


@pytest.mark.unit
def test_router_selects_external_data_for_tool_and_vendor_questions():
    router = ChatSkillRouter()

    assert router.select("你能获取外部数据吗？你的 tool 有哪些？").name == "external_data_tools"
    assert router.select("腾讯财经实时行情能接入吗？").name == "external_data_tools"
    assert router.select("Tushare AKShare Tavily 都能查吗？").name == "external_data_tools"


@pytest.mark.unit
def test_router_defaults_to_report_context_for_normal_follow_up():
    router = ChatSkillRouter()

    assert router.select("这个交易计划是否保守？").name == "report_context"


@pytest.mark.unit
def test_tushare_skill_returns_snapshot_evidence_without_exposing_credentials():
    skill = TushareDataSkill(
        snapshot_getter=lambda ts_code, trade_date: {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "is_fallback": False,
            "price": {"close": 1888.0, "pct_chg": 1.2, "amount": 123456.0},
            "daily_basic": {"pe_ttm": 24.5, "pb": 8.1, "total_mv": 2300000.0},
        }
    )

    result = skill.run(_context("PE 和估值怎么看？"))
    rendered = result.render()

    assert result.status == "ok"
    assert "PE(TTM)：24.50" in rendered
    assert "tushare" in result.data_sources
    assert "token" not in rendered.lower()


@pytest.mark.unit
def test_tushare_skill_degrades_to_report_context_when_data_unavailable():
    def unavailable(ts_code, trade_date):
        raise RuntimeError("network down")

    result = TushareDataSkill(snapshot_getter=unavailable).run(_context("资金流？"))

    assert result.status == "partial"
    assert "Tushare 结构化数据当前不可用" in result.conclusion
    assert result.data_sources == ["report_context"]
    assert result.limitations


@pytest.mark.unit
def test_external_data_skill_reports_successful_vendor_checks():
    skill = ExternalDataSkill(
        tushare_getter=lambda ts_code, trade_date: {
            "price": {"close": 119.5, "pct_chg": 0.4},
            "daily_basic": {"pe_ttm": 70.7},
        },
        tencent_getter=lambda ts_code: {
            "name": "华工科技",
            "price": 119.6,
            "pct_chg": 0.5,
            "time": "2026-05-03 10:30:00",
        },
        akshare_getter=lambda ts_code, start_date, end_date: "AKShare 新闻：暂无重大利空。",
        tavily_getter=lambda ts_code, start_date, end_date: "Tavily 搜索：行业需求仍在。",
    )

    result = skill.run(_context("你能获取外部数据吗？"))

    rendered = result.render()
    assert result.status == "ok"
    assert result.data_sources == ["tushare", "tencent_finance", "akshare", "tavily"]
    assert "Tushare" in rendered
    assert "腾讯财经" in rendered
    assert "AKShare" in rendered
    assert "Tavily" in rendered


@pytest.mark.unit
def test_external_data_skill_degrades_per_vendor_without_exposing_paths():
    def unavailable(*args):
        raise DataVendorUnavailable("disabled")

    result = ExternalDataSkill(
        tushare_getter=unavailable,
        tencent_getter=unavailable,
        akshare_getter=unavailable,
        tavily_getter=unavailable,
    ).run(_context("有哪些外部工具？"))

    assert result.status == "partial"
    assert result.data_sources == ["report_context"]
    assert "Tushare 不可用" in result.limitations[0]
    assert "/Users/" not in result.render()
    assert ".env" not in result.render()


@pytest.mark.unit
def test_news_skill_uses_akshare_before_tavily():
    calls = []

    def akshare(ts_code, start_date, end_date):
        calls.append("akshare")
        return "AKShare 新闻：公司公告偏中性。"

    def tavily(ts_code, start_date, end_date):
        calls.append("tavily")
        return "Tavily should not be called"

    result = NewsSearchSkill(akshare_getter=akshare, tavily_getter=tavily).run(
        _context("有什么公告？")
    )

    assert calls == ["akshare"]
    assert result.data_sources == ["akshare"]
    assert "AKShare 新闻" in result.evidence[0]


@pytest.mark.unit
def test_news_skill_degrades_when_external_sources_unavailable():
    def unavailable(*args):
        raise DataVendorUnavailable("disabled")

    result = NewsSearchSkill(
        akshare_getter=unavailable,
        tavily_getter=unavailable,
        tushare_fallback_getter=lambda *args: "Tushare fallback news context",
    ).run(_context("有没有利空新闻？"))

    rendered = result.render()
    assert result.status == "partial"
    assert result.data_sources == ["tushare_fallback", "report_context"]
    assert "已降级" in rendered
    assert "Tushare fallback news context" in rendered


@pytest.mark.unit
def test_report_context_skill_uses_existing_report_sections():
    result = ReportContextSkill().run(_context("交易计划是否保守？"))

    rendered = result.render()
    assert result.status == "ok"
    assert "Rating: Hold" in rendered
    assert result.data_sources == ["report_context"]
