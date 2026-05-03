from __future__ import annotations

from .base import ChatSkill, SkillContext, SkillResult


SECTION_LABELS = {
    "market_report": "技术面报告",
    "fundamentals_report": "基本面报告",
    "news_report": "新闻报告",
    "sentiment_report": "情绪报告",
    "investment_plan": "研究经理计划",
    "trader_investment_plan": "交易计划",
    "final_trade_decision": "最终组合决策",
}


class ReportContextSkill(ChatSkill):
    name = "report_context"

    def run(self, context: SkillContext) -> SkillResult:
        task = context.task
        sections = {
            key: value.strip()
            for key, value in task.report_sections.items()
            if isinstance(value, str) and value.strip()
        }
        final_decision = (task.final_decision or sections.get("final_trade_decision") or "").strip()

        evidence: list[str] = []
        for key in (
            "final_trade_decision",
            "investment_plan",
            "trader_investment_plan",
            "market_report",
            "fundamentals_report",
            "news_report",
            "sentiment_report",
        ):
            content = final_decision if key == "final_trade_decision" else sections.get(key, "")
            if content:
                evidence.append(f"{SECTION_LABELS.get(key, key)}：{_excerpt(content)}")
            if len(evidence) >= 4:
                break

        limitations: list[str] = []
        if task.status != "completed":
            limitations.append(f"当前任务状态为 {task.status}，回答仅基于已生成报告区块。")
        if not evidence:
            limitations.append("当前任务尚未生成可用报告内容。")

        if final_decision:
            conclusion = (
                f"围绕 {context.ts_code} 在 {context.trade_date} 的报告，"
                f"当前最终结论可概括为：{_excerpt(final_decision, 140)}"
            )
        elif evidence:
            conclusion = (
                f"围绕 {context.ts_code} 在 {context.trade_date} 的报告，"
                "当前只能基于阶段性分析区块回答，最终组合决策尚未就绪。"
            )
        else:
            conclusion = (
                f"已找到 {context.ts_code} 的任务，但当前还没有足够报告内容回答该问题。"
            )

        return SkillResult(
            skill=self.name,
            status="ok" if evidence else "partial",
            conclusion=conclusion,
            evidence=evidence,
            data_sources=["report_context"],
            limitations=limitations,
        )


def _excerpt(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "..."
