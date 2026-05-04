from threading import Event
import time

import pytest

from tradingagents.web.analysis_cache import AnalysisCache
from tradingagents.web.analysis_store import AnalysisStore
from tradingagents.web.analysis_service import AnalysisService
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import AnalysisTask, TaskRegistry


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Avoid leaking the developer's real ``~/.tradingagents/cache`` into history merges."""
    monkeypatch.setenv("TRADINGAGENTS_CACHE_DIR", str(tmp_path / "cache_root"))


def _request(code, model="deepseek-v4-pro", origin="hot_radar"):
    return AnalysisRequest(
        ts_code=code,
        stock_name=f"测试股票{code[:6]}",
        trade_date="2026-04-30",
        analysts=["market"],
        research_depth=3,
        quick_model=model,
        deep_model=model,
        origin=origin,
        force_refresh=True,
    )


def _wait_for(predicate, timeout=1.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_pro_lane_runs_only_one_task_at_a_time():
    blocker = Event()

    def runner(request, config, emit):
        blocker.wait(0.5)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    first = service.create_task(_request("600001.SH", "deepseek-v4-pro"))
    second = service.create_task(_request("600002.SH", "deepseek-v4-pro"))

    assert _wait_for(lambda: len(service.queue_status()["lanes"]["pro"]["running"]) == 1)
    lane = service.queue_status()["lanes"]["pro"]
    assert first.status == "running"
    assert second.status == "queued"
    assert lane["capacity"] == 1
    assert len(lane["running"]) == 1
    assert len(lane["queued"]) == 1
    blocker.set()


def test_flash_lane_runs_three_tasks_at_a_time():
    blocker = Event()

    def runner(request, config, emit):
        blocker.wait(0.5)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    for suffix in range(4):
        service.create_task(_request(f"60000{suffix}.SH", "deepseek-v4-flash"))

    assert _wait_for(lambda: len(service.queue_status()["lanes"]["flash"]["running"]) == 3)
    lane = service.queue_status()["lanes"]["flash"]
    assert lane["capacity"] == 3
    assert len(lane["running"]) == 3
    assert len(lane["queued"]) == 1
    blocker.set()


def test_analyze_origin_outranks_hot_radar_in_same_lane():
    blocker = Event()

    def runner(request, config, emit):
        blocker.wait(0.5)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    service.create_task(_request("600001.SH", "deepseek-v4-pro", origin="hot_radar"))
    hot = service.create_task(_request("600002.SH", "deepseek-v4-pro", origin="hot_radar"))
    manual = service.create_task(_request("600003.SH", "deepseek-v4-pro", origin="analyze"))

    assert _wait_for(lambda: len(service.queue_status()["lanes"]["pro"]["queued"]) == 2)
    queued_codes = [row["request"]["ts_code"] for row in service.queue_status()["lanes"]["pro"]["queued"]]
    assert queued_codes.index(manual.request.ts_code) < queued_codes.index(hot.request.ts_code)
    blocker.set()


def test_queue_delete_removes_queued_and_stopped_without_deleting_history():
    service = AnalysisService(TaskRegistry(), runner=lambda request, config, emit: ({}, ""), run_inline=False)
    queued = service.registry.create(_request("600001.SH", "deepseek-v4-pro"))
    stopped = service.registry.create(_request("600002.SH", "deepseek-v4-pro"))
    stopped.status = "stopped"

    assert service.delete_queue_entry(queued.task_id)["deleted"] is True
    assert service.delete_queue_entry(stopped.task_id)["deleted"] is True


def test_running_task_requested_to_stop_finishes_as_stopped_not_completed():
    blocker = Event()

    def runner(request, config, emit):
        blocker.wait(0.5)
        return ({"final_trade_decision": "Rating: Buy"}, "Buy")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    task = service.create_task(_request("600001.SH", "deepseek-v4-pro"))

    assert _wait_for(lambda: service.get_task(task.task_id).status == "running")
    assert service.stop_task(task.task_id)["status"] == "stopping"
    blocker.set()

    assert _wait_for(lambda: service.get_task(task.task_id).status == "stopped")
    assert service.get_task(task.task_id).final_decision == ""


def test_queue_status_includes_active_store_tasks_after_registry_restart(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    stored = AnalysisTask(task_id="task-store-running", request=_request("601991.SH", "deepseek-v4-pro"))
    stored.status = "running"
    store.upsert_task(stored, cache_key="cache-store-running")

    service = AnalysisService(TaskRegistry(), runner=lambda request, config, emit: ({}, ""), store=store)

    lane = service.queue_status()["lanes"]["pro"]

    assert [row["task_id"] for row in lane["running"]] == ["task-store-running"]


def test_stop_stale_store_running_task_marks_stopped_immediately(tmp_path):
    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    stored = AnalysisTask(task_id="task-store-stale", request=_request("601991.SH", "deepseek-v4-pro"))
    stored.status = "running"
    store.upsert_task(stored, cache_key="cache-store-stale")

    service = AnalysisService(TaskRegistry(), runner=lambda request, config, emit: ({}, ""), store=store)

    result = service.stop_task("task-store-stale")

    assert result == {"task_id": "task-store-stale", "status": "stopped", "stop_requested": True}
    assert store.get_task("task-store-stale")["status"] == "stopped"


def test_history_can_filter_completed_reports_without_queue_items():
    service = AnalysisService(TaskRegistry(), runner=lambda request, config, emit: ({}, ""), run_inline=False)
    running = service.registry.create(_request("600001.SH", "deepseek-v4-pro"))
    service.registry.start(running.task_id)
    completed = service.registry.create(_request("600002.SH", "deepseek-v4-pro"))
    service.registry.complete(completed.task_id, {"final_trade_decision": "Rating: Hold"}, "Hold")

    rows = service.history(limit=20, status="completed")

    assert [row["task_id"] for row in rows] == [completed.task_id]


def test_queue_status_excludes_completed_reports_from_current_queue():
    service = AnalysisService(TaskRegistry(), runner=lambda request, config, emit: ({}, ""), run_inline=False)
    completed = service.registry.create(_request("600002.SH", "deepseek-v4-pro"))
    service.registry.complete(completed.task_id, {"final_trade_decision": "Rating: Hold"}, "Hold")

    queue = service.queue_status()

    assert completed.task_id not in {
        row["task_id"]
        for lane in queue["lanes"].values()
        for group in ("running", "queued", "finished")
        for row in lane[group]
    }


def test_clear_completed_history_purges_store_registry_and_cache(tmp_path):
    from tradingagents.web.analysis_cache import AnalysisCache

    store = AnalysisStore(f"sqlite:///{tmp_path / 'analysis.db'}")
    cache = AnalysisCache(cache_dir=tmp_path / "cache")
    service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({}, ""),
        run_inline=False,
        cache=cache,
        runtime_dir=tmp_path,
        store=store,
    )

    completed = service.registry.create(_request("600002.SH", "deepseek-v4-pro"))
    service.registry.complete(
        completed.task_id,
        {"final_trade_decision": "Rating: Hold"},
        "Hold",
    )
    service._sync_store(service.registry.get(completed.task_id))
    cache.set(
        completed.request,
        final_state={"final_trade_decision": "Rating: Hold"},
        decision="Hold",
        report_sections={"final_trade_decision": "Rating: Hold"},
    )

    """Running tasks must survive a clear-history call."""
    running = service.registry.create(_request("600003.SH", "deepseek-v4-pro"))
    service.registry.start(running.task_id)
    service._sync_store(service.registry.get(running.task_id))

    result = service.clear_completed_history()

    assert result["deleted_tasks"] >= 1
    assert result["deleted_cache_files"] >= 1
    assert service.history(limit=20, status="completed") == []
    assert service.get_task(running.task_id) is not None
    assert service.get_task(running.task_id).status == "running"


def test_second_stop_click_force_clears_runner_stuck_stopping_state():
    """Re-clicking 「停止」 on a task already in ``stopping`` should force-stop it."""

    service = AnalysisService(TaskRegistry(), runner=lambda request, config, emit: ({}, ""), run_inline=False)
    task = service.registry.create(_request("600001.SH", "deepseek-v4-pro"))
    """Simulate a runner-stuck stopping state (e.g. server reload while a task was running)."""
    service.registry.start(task.task_id)
    task.status = "stopping"
    task.stop_requested = True

    result = service.stop_task(task.task_id)

    assert result == {"task_id": task.task_id, "status": "stopped", "stop_requested": True}
    assert service.get_task(task.task_id).status == "stopped"
