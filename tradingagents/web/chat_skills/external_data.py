from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tradingagents.dataflows import akshare_news, tavily_news, tencent_finance
from tradingagents.dataflows.tushare_stock import get_stock_snapshot
from tradingagents.dataflows.vendor_errors import DataVendorUnavailable

from .base import ChatSkill, SkillContext, SkillResult
from .news_search import _date_window


SnapshotGetter = Callable[[str, str], dict[str, Any]]
TencentGetter = Callable[[str], dict[str, Any]]
NewsGetter = Callable[[str, str, str], str]


class ExternalDataSkill(ChatSkill):
    name = "external_data_tools"

    def __init__(
        self,
        tushare_getter: SnapshotGetter = get_stock_snapshot,
        tencent_getter: TencentGetter = tencent_finance.get_quote,
        akshare_getter: NewsGetter = akshare_news.get_news,
        tavily_getter: NewsGetter = tavily_news.get_news,
    ) -> None:
        self.tushare_getter = tushare_getter
        self.tencent_getter = tencent_getter
        self.akshare_getter = akshare_getter
        self.tavily_getter = tavily_getter

    def run(self, context: SkillContext) -> SkillResult:
        evidence: list[str] = []
        data_sources: list[str] = []
        limitations: list[str] = []
        start_date, end_date = _date_window(context.trade_date)

        try:
            snapshot = self.tushare_getter(context.ts_code, context.trade_date)
            price = snapshot.get("price") or {}
            daily_basic = snapshot.get("daily_basic") or {}
            evidence.append(
                "Tushare："
                f"交易日 {snapshot.get('trade_date') or context.trade_date}，"
                f"收盘 {_fmt(price.get('close'))}，"
                f"涨跌幅 {_fmt(price.get('pct_chg'))}%，"
                f"PE(TTM) {_fmt(daily_basic.get('pe_ttm'))}。"
            )
            data_sources.append("tushare")
        except Exception as exc:
            limitations.append(f"Tushare 不可用：{_safe_error(exc)}")

        try:
            quote = self.tencent_getter(context.ts_code)
            evidence.append(
                "腾讯财经："
                f"{quote.get('name') or context.ts_code}，"
                f"最新价 {_fmt(quote.get('price'))}，"
                f"涨跌幅 {_fmt(quote.get('pct_chg'))}%，"
                f"更新时间 {quote.get('time') or '暂无'}。"
            )
            data_sources.append("tencent_finance")
        except Exception as exc:
            limitations.append(f"腾讯财经不可用：{_safe_error(exc)}")

        for label, getter in (
            ("akshare", self.akshare_getter),
            ("tavily", self.tavily_getter),
        ):
            try:
                news = getter(context.ts_code, start_date, end_date)
            except Exception as exc:
                limitations.append(f"{label} 不可用：{_safe_error(exc)}")
                continue
            evidence.append(f"{label.upper()}：{_excerpt(news, 260)}")
            data_sources.append(label)

        if not evidence:
            evidence = _report_fallback(context)
            data_sources = ["report_context"]

        status = "ok" if any(source != "report_context" for source in data_sources) else "partial"
        return SkillResult(
            skill=self.name,
            status=status,
            conclusion=(
                "Agent Chat 可按问题调用外部数据源：Tushare 用于 A 股行情/估值/财务快照，"
                "腾讯财经用于实时行情快照，AKShare 与 Tavily 用于新闻、公告和网页检索。"
                "若某个源失败，会在限制说明里展示并降级到其他源或报告上下文。"
            ),
            evidence=evidence,
            data_sources=data_sources,
            limitations=limitations,
        )


def _report_fallback(context: SkillContext) -> list[str]:
    final = context.report_sections.get("final_trade_decision") or ""
    if final:
        return [f"report_context：{_excerpt(final, 260)}"]
    return ["report_context：当前没有外部数据返回，也没有可用报告片段。"]


def _excerpt(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "暂无"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, DataVendorUnavailable):
        message = str(exc).strip()
    else:
        message = type(exc).__name__
    return message if message and "/" not in message and "\\" not in message else type(exc).__name__
