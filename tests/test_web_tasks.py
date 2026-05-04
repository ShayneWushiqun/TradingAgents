import pytest
from pydantic import ValidationError

from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import TaskRegistry


def test_task_registry_creates_queued_task():
    registry = TaskRegistry()
    request = AnalysisRequest(
        ts_code="600519.SH",
        trade_date="2026-04-30",
        analysts=["market", "fundamentals"],
        research_depth=3,
        llm_provider="deepseek",
        quick_model="deepseek-v4-pro",
        deep_model="deepseek-v4-pro",
    )

    task = registry.create(request)

    assert task.task_id
    assert task.status == "queued"
    assert task.request.ts_code == "600519.SH"
    assert registry.get(task.task_id) == task


def test_analysis_request_rejects_non_a_share_code():
    with pytest.raises(ValidationError):
        AnalysisRequest(ts_code="AAPL", trade_date="2026-04-30")


def test_task_registry_records_ordered_events():
    registry = TaskRegistry()
    request = AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-30")
    task = registry.create(request)

    first = registry.add_event(task.task_id, "task_started", {"status": "running"})
    second = registry.add_event(
        task.task_id,
        "report_section",
        {"section": "market_report", "content": "趋势转强"},
    )

    assert first["id"] == 1
    assert second["id"] == 2
    assert registry.events_since(task.task_id, 0) == [first, second]
    assert registry.events_since(task.task_id, 1) == [second]


def test_task_registry_updates_completed_task_from_final_state():
    registry = TaskRegistry()
    request = AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-30")
    task = registry.create(request)

    registry.complete(
        task.task_id,
        {
            "market_report": "技术面报告",
            "fundamentals_report": "基本面报告",
            "final_trade_decision": "Rating: Buy\n分批增持。",
        },
        decision="Buy",
    )

    assert task.status == "completed"
    assert task.report_sections["market_report"] == "技术面报告"
    assert task.final_decision == "Rating: Buy\n分批增持。"
    assert task.decision == "Buy"
    assert task.events[-1]["event"] == "task_completed"
