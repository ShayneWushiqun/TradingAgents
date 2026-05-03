"""Build sanitized Markdown exports for TradingAgents analysis tasks."""

from __future__ import annotations

import re
from typing import Any

from tradingagents.web.tasks import AnalysisTask


_SECTION_TITLES: dict[str, str] = {
    "final_trade_decision": "组合经理最终决策（final_trade_decision）",
    "market_report": "市场 / 技术面报告（market_report）",
    "fundamentals_report": "基本面报告（fundamentals_report）",
    "news_report": "新闻报告（news_report）",
    "sentiment_report": "情绪报告（sentiment_report）",
    "investment_plan": "研究辩论 / 投资计划（investment_plan）",
    "trader_investment_plan": "交易计划（trader_investment_plan）",
}


_KNOWN_SECTION_ORDER: tuple[str, ...] = (
    "final_trade_decision",
    "market_report",
    "fundamentals_report",
    "news_report",
    "sentiment_report",
    "investment_plan",
    "trader_investment_plan",
)


def export_filename(task: AnalysisTask) -> str:
    ts = task.request.ts_code.replace("/", "-")
    td = task.request.trade_date.replace("/", "-")
    return f"TradingAgents-{ts}-{td}-full-report.md"


def can_export_full_report(task: AnalysisTask) -> tuple[bool, str]:
    """Return (allowed, reason_code) for HTTP mapping."""
    if task.status in ("queued", "running"):
        return False, "running"
    body = _has_exportable_body(task)
    if task.status == "completed" and not body:
        return False, "empty"
    if task.status == "failed" and not body:
        return False, "failed_empty"
    return True, "ok"


def _has_exportable_body(task: AnalysisTask) -> bool:
    if (task.final_decision or "").strip():
        return True
    for value in task.report_sections.values():
        if isinstance(value, str) and value.strip():
            return True
    return False


def sanitize_markdown(text: str) -> str:
    """Remove or redact common secret patterns and local paths from exported text."""
    out = text
    out = re.sub(r"Bearer\s+[A-Za-z0-9._=-]+", "Bearer [REDACTED]", out, flags=re.I)
    out = re.sub(r"\bsk-[A-Za-z0-9]{20,}\b", "[REDACTED_API_KEY]", out)
    out = re.sub(r"\b[A-Z][A-Z0-9_]*_API_KEY\b", "[REDACTED_ENV_NAME]", out)
    out = re.sub(r"\b[A-Z][A-Z0-9_]*_TOKEN\b", "[REDACTED_ENV_NAME]", out)
    out = re.sub(r"\bTAVILY_API_KEY\b", "[REDACTED_ENV_NAME]", out)
    out = re.sub(r"\bTUSHARE_API_TOKEN\b", "[REDACTED_ENV_NAME]", out)
    out = out.replace(".env", "[environment_config]")
    out = out.replace(".ENV", "[environment_config]")
    out = out.replace("API_KEY", "[REDACTED]")
    out = re.sub(r"\bTOKEN\b", "[REDACTED]", out)
    out = re.sub(r"/Users/[^\s)\]\"']+", "[USER_PATH]", out)
    out = re.sub(r"/home/[^\s)\]\"']+", "[USER_PATH]", out)
    out = re.sub(r"[A-Za-z]:\\Users\\[^\s;)\"']+", "[USER_PATH]", out)
    return out


def _section_heading(key: str) -> str:
    return _SECTION_TITLES.get(key, f"报告区块（{key}）")


def _markdown_table(rows: list[tuple[str, Any]]) -> str:
    lines = ["| 字段 | 值 |", "| --- | --- |"]
    for label, value in rows:
        cell = "" if value is None else str(value).replace("|", "\\|").replace("\n", "<br>")
        lines.append(f"| {label} | {cell} |")
    return "\n".join(lines)


def build_full_report_markdown(task: AnalysisTask) -> str:
    """Assemble full Markdown; content under section headings is raw report text (sanitized)."""
    rows_meta: list[tuple[str, Any]] = [
        ("股票代码（ts_code）", task.request.ts_code),
        ("交易日（trade_date）", task.request.trade_date),
        ("任务 ID（task_id）", task.task_id),
        ("任务状态（status）", task.status),
        ("是否命中缓存（cached）", task.cached),
        ("解析后的决策标签（decision）", task.decision or ""),
    ]
    rows_params: list[tuple[str, Any]] = [
        ("analysts", ", ".join(task.request.analysts)),
        ("research_depth", task.request.research_depth),
        ("llm_provider", task.request.llm_provider),
        ("quick_model", task.request.quick_model),
        ("deep_model", task.request.deep_model),
        ("force_refresh", task.request.force_refresh),
    ]

    parts: list[str] = [
        "# TradingAgents A股完整分析报告",
        "",
        "以下为当前分析任务导出的**原始报告 Markdown**，仅做敏感信息脱敏，不做内容重述或删减。",
        "",
        "## 元数据",
        "",
        _markdown_table(rows_meta),
        "",
        "## 分析参数（request）",
        "",
        _markdown_table(rows_params),
        "",
    ]

    if (task.error or "").strip():
        parts.extend(
            [
                "## 任务错误信息（error，已脱敏）",
                "",
                sanitize_markdown(str(task.error)),
                "",
            ]
        )

    final_block = (task.final_decision or "").strip()
    if final_block:
        parts.extend(
            [
                "## 组合经理最终输出（final_decision）",
                "",
                sanitize_markdown(final_block),
                "",
            ]
        )

    emitted: set[str] = set()
    sections = {k: v for k, v in task.report_sections.items() if isinstance(v, str)}

    for key in _KNOWN_SECTION_ORDER:
        if key not in sections:
            continue
        content = sections[key].strip()
        if not content:
            continue
        parts.extend([f"## {_section_heading(key)}", "", sanitize_markdown(content), ""])
        emitted.add(key)

    remaining = sorted(k for k in sections if k not in emitted)
    for key in remaining:
        content = (sections.get(key) or "").strip()
        if not content:
            continue
        parts.extend([f"## {_section_heading(key)}", "", sanitize_markdown(content), ""])

    doc = "\n".join(parts).strip() + "\n"
    return sanitize_markdown(doc)
