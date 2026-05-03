from __future__ import annotations

from typing import Any, Callable

from tradingagents.dataflows.tushare_stock import get_stock_snapshot

from .base import ChatSkill, SkillContext, SkillResult


SnapshotGetter = Callable[[str, str], dict[str, Any]]


class TushareDataSkill(ChatSkill):
    name = "tushare_a_share_data"

    def __init__(self, snapshot_getter: SnapshotGetter = get_stock_snapshot) -> None:
        self.snapshot_getter = snapshot_getter

    def run(self, context: SkillContext) -> SkillResult:
        try:
            snapshot = self.snapshot_getter(context.ts_code, context.trade_date)
        except Exception as exc:
            fallback = _report_fallback(context)
            return SkillResult(
                skill=self.name,
                status="partial",
                conclusion=(
                    f"{context.ts_code} 的 Tushare 结构化数据当前不可用，已降级为报告上下文回答。"
                ),
                evidence=fallback,
                data_sources=["report_context"],
                limitations=[f"Tushare 数据调用失败：{type(exc).__name__}"],
            )

        price = snapshot.get("price") or {}
        daily_basic = snapshot.get("daily_basic") or {}
        evidence = [
            f"交易日：{snapshot.get('trade_date') or context.trade_date}",
            f"收盘价：{_fmt(price.get('close'))}，涨跌幅：{_fmt(price.get('pct_chg'))}%",
            f"成交额：{_fmt(price.get('amount'))}",
            f"PE(TTM)：{_fmt(daily_basic.get('pe_ttm'))}，PB：{_fmt(daily_basic.get('pb'))}",
            f"总市值：{_fmt(daily_basic.get('total_mv'))}",
        ]

        limitations: list[str] = []
        if snapshot.get("is_fallback"):
            limitations.append("指定日期无直接行情，已回退到最近可用交易日。")
        if not price and not daily_basic:
            limitations.append("Tushare 返回内容为空，无法形成新增量化证据。")
        if "资金" in context.message or "moneyflow" in context.message.lower():
            limitations.append("当前 runtime 使用股票快照接口，资金流明细不足时需回到完整分析报告核验。")

        return SkillResult(
            skill=self.name,
            status="ok" if price or daily_basic else "partial",
            conclusion=(
                f"{context.ts_code} 的估值和行情追问已使用 Tushare A股数据补充；"
                "请结合报告中的趋势、基本面和风险结论一起判断。"
            ),
            evidence=evidence,
            data_sources=["tushare", "report_context"],
            limitations=limitations,
        )


def _report_fallback(context: SkillContext) -> list[str]:
    evidence: list[str] = []
    for key in ("market_report", "fundamentals_report", "final_trade_decision"):
        content = context.report_sections.get(key)
        if content:
            evidence.append(f"{key}: {' '.join(content.split())[:180]}")
    return evidence or ["当前报告上下文也缺少可用行情或估值证据。"]


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "暂无"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
