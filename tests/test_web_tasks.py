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
        research_depth=1,
        llm_provider="deepseek",
        quick_model="deepseek-chat",
        deep_model="deepseek-chat",
    )

    task = registry.create(request)

    assert task.task_id
    assert task.status == "queued"
    assert task.request.ts_code == "600519.SH"
    assert registry.get(task.task_id) == task


def test_analysis_request_rejects_non_a_share_code():
    with pytest.raises(ValidationError):
        AnalysisRequest(ts_code="AAPL", trade_date="2026-04-30")
