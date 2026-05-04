"""In-memory registry history when no AnalysisStore is configured."""

import time

from tradingagents.web.analysis_cache import AnalysisCache
from tradingagents.web.analysis_service import AnalysisService
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import TaskRegistry


def test_history_without_store_lists_completed_and_queued_tasks(tmp_path):
    registry = TaskRegistry()
    service = AnalysisService(
        registry,
        runner=lambda request, config, emit: (
            {"final_trade_decision": "Rating: Hold\n", "market_report": "ok"},
            "Hold",
        ),
        run_inline=True,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=None,
    )

    req_done = AnalysisRequest(
        ts_code="601991.SH",
        trade_date="2026-04-30",
        analysts=["market", "fundamentals"],
        research_depth=3,
        force_refresh=True,
    )
    t_done = service.create_task(req_done)
    assert t_done.status == "completed"

    req_run = AnalysisRequest(
        ts_code="002594.SZ",
        trade_date="2026-04-30",
        analysts=["market", "fundamentals", "news"],
        research_depth=3,
        force_refresh=True,
    )
    # Do not use create_task here — run_inline would complete it; we need a queued row in history.
    t_run = registry.create(req_run)
    assert t_run.status == "queued"

    rows = service.history(limit=10)
    assert len(rows) == 2
    by_id = {r["task_id"]: r for r in rows}
    assert by_id[t_done.task_id]["status"] == "completed"
    assert by_id[t_run.task_id]["status"] in {"queued", "running"}
    codes = {r["request"]["ts_code"] for r in rows}
    assert codes == {"601991.SH", "002594.SZ"}
    for row in rows:
        assert "cache_key" in row
        assert "created_at" in row
        assert "updated_at" in row
        assert "report_sections" in row


def test_task_registry_list_recent_orders_by_updated_at():
    reg = TaskRegistry()
    r1 = AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-28", force_refresh=True)
    r2 = AnalysisRequest(ts_code="600519.SH", trade_date="2026-04-29", force_refresh=True)
    a = reg.create(r1)
    time.sleep(0.002)
    b = reg.create(r2)
    recent = reg.list_recent(10)
    assert [t.task_id for t in recent] == [b.task_id, a.task_id]


def test_history_completed_falls_back_to_disk_cache_when_no_store_or_registry(tmp_path):
    """Cache-only completion: rerunning the server (registry empty, no store) must still surface reports."""

    cache = AnalysisCache(cache_dir=tmp_path / "cache")
    request = AnalysisRequest(
        ts_code="600186.SH",
        trade_date="2026-05-03",
        analysts=["market", "fundamentals"],
        research_depth=3,
        force_refresh=True,
    )
    cache.set(
        request,
        final_state={"final_trade_decision": "Rating: Hold\n"},
        decision="Hold",
        report_sections={"final_trade_decision": "Rating: Hold"},
    )

    fresh_registry = TaskRegistry()
    service = AnalysisService(
        fresh_registry,
        runner=lambda request, config, emit: ({}, ""),
        run_inline=False,
        cache=cache,
        runtime_dir=tmp_path,
        store=None,
    )

    rows = service.history(limit=20, status="completed")
    assert any(row["request"]["ts_code"] == "600186.SH" for row in rows)
    cache_row = next(row for row in rows if row["request"]["ts_code"] == "600186.SH")
    assert cache_row["status"] == "completed"
    assert cache_row["task_id"].startswith("cache:")
    assert cache_row["cache_key"]

    """``GET /api/analysis/{task_id}`` must restore a real task from the cache id."""
    restored = service.get_task(cache_row["task_id"])
    assert restored is not None
    assert restored.status == "completed"
    assert restored.request.ts_code == "600186.SH"
    assert restored.report_sections.get("final_trade_decision") == "Rating: Hold"


def test_history_with_store_does_not_mix_disk_cache_rows(tmp_path):
    """When the DB store is configured, history is DB-authoritative and ignores loose cache files."""

    from tradingagents.web.analysis_store import AnalysisStore

    cache = AnalysisCache(cache_dir=tmp_path / "cache")
    cache_only_request = AnalysisRequest(
        ts_code="600186.SH",
        trade_date="2026-05-03",
        force_refresh=True,
    )
    cache.set(
        cache_only_request,
        final_state={"final_trade_decision": "Rating: Hold\n"},
        decision="Hold",
        report_sections={"final_trade_decision": "Rating: Hold"},
    )

    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({}, ""),
        run_inline=False,
        cache=cache,
        runtime_dir=tmp_path,
        store=store,
    )

    assert service.history(limit=20, status="completed") == []
    assert service.get_task(f"cache:{cache.key_for(cache_only_request)}") is None


def test_history_completed_includes_repaired_failed_rows_with_final_decision(tmp_path):
    """A row stored as ``failed`` but with a usable ``final_decision`` must surface as completed."""
    from tradingagents.web.analysis_store import AnalysisStore
    from tradingagents.web.tasks import AnalysisTask

    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    request = AnalysisRequest(ts_code="600186.SH", trade_date="2026-05-03")
    task = AnalysisTask(task_id="task-failed-but-done", request=request)
    from tradingagents.web.analysis_service import RAW_LOG_TICKER_ERROR

    task.status = "failed"
    task.error = RAW_LOG_TICKER_ERROR
    task.report_sections["final_trade_decision"] = "Rating: Hold\nReasoning: ..."
    task.final_decision = "Rating: Hold"
    task.decision = "Hold"
    store.upsert_task(task, cache_key="cache-x")

    service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({}, ""),
        run_inline=False,
        cache=AnalysisCache(cache_dir=tmp_path / "cache"),
        runtime_dir=tmp_path,
        store=store,
    )

    completed = service.history(limit=10, status="completed")
    assert any(row["task_id"] == "task-failed-but-done" for row in completed)
    row = next(row for row in completed if row["task_id"] == "task-failed-but-done")
    assert row["status"] == "completed"
    assert row["request"]["ts_code"] == "600186.SH"
