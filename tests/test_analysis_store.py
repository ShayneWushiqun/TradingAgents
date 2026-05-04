from datetime import datetime, timedelta

from tradingagents.web.analysis_store import AnalysisStore
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import AnalysisTask


def test_analysis_store_tracks_latest_and_history(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    request = AnalysisRequest(ts_code="600118.SH", trade_date="2026-04-30")
    task = AnalysisTask(task_id="task-1", request=request)

    store.upsert_task(task, cache_key="cache-1")
    task.status = "running"
    store.upsert_task(task, cache_key="cache-1")

    latest = store.latest_task()
    history = store.history()

    assert latest is not None
    assert latest["task_id"] == "task-1"
    assert latest["status"] == "running"
    assert latest["request"]["ts_code"] == "600118.SH"
    assert latest["cache_key"] == "cache-1"
    assert history[0]["task_id"] == "task-1"


def test_analysis_store_restores_latest_completed_request(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    request = AnalysisRequest(ts_code="000066.SZ", trade_date="2026-04-30")
    task = AnalysisTask(task_id="task-2", request=request)
    task.status = "completed"
    task.cached = True
    task.report_sections["final_trade_decision"] = "Rating: Hold"
    task.final_decision = "Rating: Hold"
    task.decision = "Hold"

    store.upsert_task(task, cache_key="cache-2")

    latest_completed = store.latest_completed()

    assert latest_completed is not None
    assert latest_completed["request"]["ts_code"] == "000066.SZ"
    assert latest_completed["status"] == "completed"
    assert latest_completed["final_decision"] == "Rating: Hold"


def test_analysis_store_persists_partial_report_sections_for_failed_task(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    request = AnalysisRequest(ts_code="603629.SH", trade_date="2026-04-30")
    task = AnalysisTask(task_id="task-3", request=request)
    task.status = "failed"
    task.report_sections["market_report"] = "已生成技术面"
    task.report_sections["fundamentals_report"] = "已生成基本面"
    task.error = "provider interrupted"

    store.upsert_task(task, cache_key="cache-3")

    latest = store.latest_task()
    restored = store.get_task("task-3")

    assert latest is not None
    assert latest["status"] == "failed"
    assert latest["report_sections"]["market_report"] == "已生成技术面"
    assert latest["report_sections"]["fundamentals_report"] == "已生成基本面"
    assert latest["error"] == "provider interrupted"
    assert restored is not None
    assert restored["report_sections"]["market_report"] == "已生成技术面"


def test_analysis_store_history_completed_not_masked_by_many_recent_queued(tmp_path):
    """``status=completed`` must not be implemented as “recent N rows then filter”."""
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    base = datetime(2024, 1, 1)
    done_req = AnalysisRequest(ts_code="600186.SH", trade_date="2026-05-03")
    done_task = AnalysisTask(task_id="done-old", request=done_req)
    done_task.status = "completed"
    done_task.created_at = base
    done_task.updated_at = base
    store.upsert_task(done_task, cache_key="k-done")

    for i in range(201):
        request = AnalysisRequest(ts_code="600000.SH", trade_date="2026-05-01")
        task = AnalysisTask(task_id=f"q-{i}", request=request)
        task.status = "queued"
        task.created_at = base + timedelta(seconds=i + 1)
        task.updated_at = base + timedelta(seconds=i + 1)
        store.upsert_task(task, cache_key=f"k-{i}")

    completed_only = store.history(limit=10, status="completed")
    assert len(completed_only) == 1
    assert completed_only[0]["task_id"] == "done-old"
    assert completed_only[0]["request"]["ts_code"] == "600186.SH"


def test_analysis_store_soft_deletes_completed_rows_without_removing_db_record(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    request = AnalysisRequest(ts_code="600186.SH", trade_date="2026-05-03")
    task = AnalysisTask(task_id="done-soft-delete", request=request)
    task.status = "completed"

    store.upsert_task(task, cache_key="k-soft")

    assert store.soft_delete_completed() == 1
    assert store.history(limit=10, status="completed") == []
    stored = store.get_task("done-soft-delete", include_deleted=True)
    assert stored is not None
    assert stored["task_id"] == "done-soft-delete"
    assert stored["status"] == "completed"
    assert stored["deleted_at"]


def test_analysis_store_deletes_task_by_id(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    request = AnalysisRequest(ts_code="603629.SH", trade_date="2026-04-30")
    task = AnalysisTask(task_id="task-delete", request=request)

    store.upsert_task(task, cache_key="cache-delete")

    assert store.delete_task("task-delete") is True
    assert store.get_task("task-delete") is None
    assert store.history() == []
    assert store.delete_task("task-delete") is False
