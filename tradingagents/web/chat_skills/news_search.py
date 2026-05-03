from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from tradingagents.dataflows import akshare_news, tavily_news, tushare_news_fallback
from tradingagents.dataflows.vendor_errors import DataVendorUnavailable

from .base import ChatSkill, SkillContext, SkillResult


NewsGetter = Callable[[str, str, str], str]


class NewsSearchSkill(ChatSkill):
    name = "a_share_news_search"

    def __init__(
        self,
        akshare_getter: NewsGetter = akshare_news.get_news,
        tavily_getter: NewsGetter = tavily_news.get_news,
        tushare_fallback_getter: NewsGetter = tushare_news_fallback.get_news,
    ) -> None:
        self.akshare_getter = akshare_getter
        self.tavily_getter = tavily_getter
        self.tushare_fallback_getter = tushare_fallback_getter

    def run(self, context: SkillContext) -> SkillResult:
        start_date, end_date = _date_window(context.trade_date)
        limitations: list[str] = []

        for source, getter in (
            ("akshare", self.akshare_getter),
            ("tavily", self.tavily_getter),
        ):
            try:
                news = getter(context.ts_code, start_date, end_date)
            except DataVendorUnavailable as exc:
                limitations.append(f"{source} 不可用：{_safe_error(exc)}")
                continue
            except Exception as exc:
                limitations.append(f"{source} 调用失败：{_safe_error(exc)}")
                continue

            return SkillResult(
                skill=self.name,
                conclusion=(
                    f"已使用 {source.upper()} 检索 {context.ts_code} 的新闻/公告线索，"
                    "请优先关注这些事件是否改变报告中的风险假设。"
                ),
                evidence=[_excerpt(news, 700)],
                data_sources=[source],
                limitations=limitations,
            )

        try:
            fallback_news = self.tushare_fallback_getter(
                context.ts_code, start_date, end_date
            )
        except Exception as exc:
            limitations.append(f"tushare fallback 调用失败：{_safe_error(exc)}")
            fallback_news = "Tushare fallback 不可用，继续使用报告上下文回答。"
        report_evidence = _report_context_evidence(context)
        limitations.append("AKShare 与 Tavily 均未返回可用外部新闻，已降级到 Tushare fallback 和报告上下文。")

        return SkillResult(
            skill=self.name,
            status="partial",
            conclusion=(
                f"未能获取 {context.ts_code} 的外部新闻/公告数据，"
                "当前只能基于降级数据和已有报告判断利好利空。"
            ),
            evidence=[_excerpt(fallback_news, 500), *report_evidence],
            data_sources=["tushare_fallback", "report_context"],
            limitations=limitations,
        )


def _date_window(trade_date: str, days: int = 30) -> tuple[str, str]:
    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = end - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _report_context_evidence(context: SkillContext) -> list[str]:
    evidence: list[str] = []
    for key in ("news_report", "sentiment_report", "final_trade_decision"):
        content = context.report_sections.get(key)
        if content:
            evidence.append(f"{key}: {_excerpt(content, 260)}")
    return evidence or ["报告上下文中没有可用新闻区块。"]


def _excerpt(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message if message and "/" not in message and "\\" not in message else type(exc).__name__
