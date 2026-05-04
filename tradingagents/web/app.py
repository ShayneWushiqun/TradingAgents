import os
import json
from pathlib import Path
from collections.abc import Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from tradingagents.dataflows.tushare_stock import get_stock_snapshot, resolve_stock_name
from tradingagents.web.analysis_cache import AnalysisCache
from tradingagents.web.analysis_service import AnalysisRunner, AnalysisService
from tradingagents.web.analysis_store import AnalysisStore
from tradingagents.web.chat_service import ChatService
from tradingagents.web.hot_radar_scheduler import HotRadarScheduler
from tradingagents.web.hot_radar_service import HotRadarService
from tradingagents.web.report_export import (
    build_full_report_markdown,
    can_export_full_report,
    export_filename,
)
from tradingagents.web.schemas import AnalysisRequest, ChatRequest, HotRadarFetchRequest, HotRadarRunRequest
from tradingagents.web.tasks import TaskRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSTATION_HTML = PROJECT_ROOT / "docs" / "design" / "a-share-workstation.html"
AGENT_CHAT_HTML = PROJECT_ROOT / "docs" / "design" / "agent-chat.html"
REPORTS_HTML = PROJECT_ROOT / "docs" / "design" / "reports.html"
SETTINGS_HTML = PROJECT_ROOT / "docs" / "design" / "settings.html"
HOT_RADAR_HTML = PROJECT_ROOT / "docs" / "design" / "hot-radar.html"
DESIGN_STATIC_DIR = PROJECT_ROOT / "docs" / "design"
DEFAULT_RUNTIME_DIR = PROJECT_ROOT / ".tradingagents-runtime"


def create_app(
    analysis_runner: AnalysisRunner | None = None,
    runtime_dir: str | Path | None = None,
    hot_snapshot_getter: Callable[[str, int], dict] | None = None,
    trade_dates_getter: Callable[[str | None, int], list[str]] | None = None,
    enable_hot_radar_scheduler: bool | None = None,
) -> FastAPI:
    load_dotenv()
    app = FastAPI(title="TradingAgents A Share Workstation")
    registry = TaskRegistry()
    runtime_root = Path(runtime_dir) if runtime_dir is not None else DEFAULT_RUNTIME_DIR
    cache = AnalysisCache(cache_dir=runtime_root / "cache")
    store = None
    store_error = ""
    database_url = os.getenv("TRADINGAGENTS_DB_URL", "").strip()
    if database_url:
        try:
            store = AnalysisStore(database_url)
        except Exception as exc:  # pragma: no cover - depends on local database
            store_error = str(exc)
    analysis_service = AnalysisService(
        registry,
        runner=analysis_runner,
        run_inline=analysis_runner is not None,
        cache=cache,
        runtime_dir=runtime_root,
        store=store,
    )
    app.state.analysis_service = analysis_service
    app.state.analysis_store = store
    app.state.analysis_store_error = store_error
    chat_service = ChatService(analysis_service)
    hot_radar_service = HotRadarService.from_runtime(
        analysis_service=analysis_service,
        database_url=database_url or None,
        runtime_dir=runtime_root,
        hot_snapshot_getter=hot_snapshot_getter,
        trade_dates_getter=trade_dates_getter,
    )
    app.state.hot_radar_service = hot_radar_service
    scheduler_enabled = (
        enable_hot_radar_scheduler
        if enable_hot_radar_scheduler is not None
        else os.getenv("HOT_RADAR_SCHEDULER_ENABLED", "1") != "0"
    )
    hot_radar_scheduler = HotRadarScheduler(hot_radar_service)
    app.state.hot_radar_scheduler = hot_radar_scheduler

    @app.on_event("startup")
    def start_hot_radar_scheduler() -> None:
        if scheduler_enabled:
            hot_radar_scheduler.start()

    @app.on_event("shutdown")
    def stop_hot_radar_scheduler() -> None:
        hot_radar_scheduler.stop()

    app.mount(
        "/design",
        StaticFiles(directory=str(DESIGN_STATIC_DIR)),
        name="design_static",
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return WORKSTATION_HTML.read_text(encoding="utf-8")

    @app.get("/agent-chat", response_class=HTMLResponse)
    def agent_chat() -> str:
        return AGENT_CHAT_HTML.read_text(encoding="utf-8")

    @app.get("/reports", response_class=HTMLResponse)
    def reports() -> str:
        return REPORTS_HTML.read_text(encoding="utf-8")

    @app.get("/hot-radar", response_class=HTMLResponse)
    def hot_radar() -> str:
        return HOT_RADAR_HTML.read_text(encoding="utf-8")

    @app.get("/settings", response_class=HTMLResponse)
    def settings() -> str:
        return SETTINGS_HTML.read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "data_source": "tushare",
            "tushare_configured": bool(os.getenv("TUSHARE_API_TOKEN")),
            "analysis_store_configured": bool(database_url),
            "analysis_store_available": store is not None,
            "analysis_store_error": store_error,
        }

    @app.get("/api/tushare/stocks/{ts_code}/snapshot")
    def stock_snapshot(ts_code: str, trade_date: str) -> dict:
        return get_stock_snapshot(ts_code, trade_date)

    @app.get("/api/stocks/{ts_code}/name")
    def stock_display_name(ts_code: str) -> dict:
        """Chinese security name from Tushare ``stock_basic`` (never raises HTTP 500)."""

        try:
            normalized = AnalysisRequest(ts_code=ts_code, trade_date="2026-01-01").ts_code
        except Exception:
            return {"ts_code": (ts_code or "").strip().upper(), "stock_name": ""}
        try:
            name = resolve_stock_name(normalized)
        except Exception:
            name = ""
        return {"ts_code": normalized, "stock_name": (name or "").strip()}

    @app.get("/api/hot-radar/trade-dates")
    def hot_radar_trade_dates(end_date: str | None = None, limit: int = 30) -> dict:
        return {"items": hot_radar_service.trade_dates(end_date=end_date, limit=limit)}

    @app.get("/api/hot-radar")
    def hot_radar_dashboard(
        trade_date: str,
        batch_time: str = "daily",
        top_n: int = 20,
        fetch_if_missing: bool = True,
    ) -> dict:
        """``fetch_if_missing`` (default True): walks open days backward until a non-empty snapshot is found or pulled."""

        return hot_radar_service.get_dashboard(
            trade_date,
            batch_time,
            top_n=top_n,
            fetch_if_missing=fetch_if_missing,
        )

    @app.post("/api/hot-radar/fetch")
    def hot_radar_fetch_snapshot(request: HotRadarFetchRequest) -> dict:
        """Always calls Tushare (unless ``force_refresh`` is false), updates snapshot only (no Agent batch).

        Completed batches only replace leaderboard rows; linked analysis_tasks are kept.

        """

        return hot_radar_service.sync_hot_snapshot_from_source(
            request.trade_date,
            request.batch_time,
            top_n=request.top_n,
            force_refresh=request.force_refresh,
        )

    @app.post("/api/hot-radar/run")
    def run_hot_radar(request: HotRadarRunRequest) -> dict:
        return hot_radar_service.run_batch(
            request.trade_date,
            request.batch_time,
            top_n=request.top_n,
            quick_model=request.quick_model,
            deep_model=request.deep_model,
        )

    def task_payload(task) -> dict:
        req = analysis_service.enrich_request_for_response(task.request)
        return {
            "task_id": task.task_id,
            "status": task.status,
            "request": req.model_dump(),
            "report_sections": task.report_sections,
            "final_decision": task.final_decision,
            "decision": task.decision,
            "error": task.error,
            "cached": task.cached,
        }

    @app.post("/api/analysis")
    def create_analysis(request: AnalysisRequest) -> dict:
        task = analysis_service.create_task(request)
        return {
            "task_id": task.task_id,
            "status": "completed" if task.cached else "queued",
            "cached": task.cached,
        }

    @app.post("/api/analysis/restore")
    def restore_analysis(request: AnalysisRequest) -> dict:
        task = analysis_service.restore_cached_task(request)
        if task is None:
            raise HTTPException(status_code=404, detail="analysis cache not found")
        return {
            "task_id": task.task_id,
            "status": "completed",
            "cached": True,
        }

    @app.get("/api/analysis/latest")
    def latest_analysis() -> dict:
        task = analysis_service.latest_task()
        if task is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        return task_payload(task)

    @app.get("/api/analysis/history")
    def analysis_history(limit: int = 50, status: str | None = None) -> dict:
        """Recent analysis tasks ordered by ``updated_at`` desc (persistent store)."""

        return {"items": analysis_service.history(limit=limit, status=status)}

    @app.delete("/api/analysis/history")
    def analysis_history_clear(status: str | None = "completed") -> dict:
        """One-shot purge of completed reports (registered before ``/api/analysis/{task_id}``)."""

        wanted = str(status or "").strip()
        if wanted and wanted != "completed":
            raise HTTPException(status_code=400, detail="only status=completed bulk-clear is supported")
        return analysis_service.clear_completed_history()

    @app.get("/api/analysis/queue")
    def analysis_queue() -> dict:
        return analysis_service.queue_status()

    @app.post("/api/analysis/{task_id}/priority")
    def analysis_queue_priority(task_id: str, request: dict) -> dict:
        result = analysis_service.move_queue_task(
            task_id,
            direction=str(request.get("direction") or ""),
        )
        if result is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        return result

    @app.post("/api/analysis/{task_id}/stop")
    def analysis_queue_stop(task_id: str) -> dict:
        result = analysis_service.stop_task(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        return result

    @app.delete("/api/analysis/queue/{task_id}")
    def analysis_queue_delete(task_id: str) -> dict:
        result = analysis_service.delete_queue_entry(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        return result

    @app.get("/api/analysis/{task_id}")
    def analysis_status(task_id: str) -> dict:
        task = analysis_service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        return task_payload(task)

    @app.delete("/api/analysis/{task_id}")
    def delete_analysis(task_id: str) -> dict:
        result = analysis_service.delete_task(task_id)
        if result is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        if result.get("blocked"):
            raise HTTPException(status_code=409, detail="running analysis cannot be deleted")
        return result

    @app.get("/api/analysis/{task_id}/export.md")
    def export_analysis_markdown(task_id: str) -> Response:
        task = analysis_service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="analysis task not found")
        allowed, code = can_export_full_report(task)
        if not allowed:
            detail = "当前没有可导出的完整报告。"
            if code == "running":
                detail = "当前没有可导出的完整报告：分析仍在进行中。"
            elif code == "empty":
                detail = "当前没有可导出的完整报告：任务已完成但报告内容为空。"
            elif code == "failed_empty":
                detail = "当前没有可导出的完整报告：任务失败且无已生成的报告内容。"
            raise HTTPException(status_code=409, detail=detail)
        body = build_full_report_markdown(task)
        filename = export_filename(task)
        disposition = (
            f'attachment; filename="{filename}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
        return Response(
            content=body.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )

    @app.get("/api/analysis/{task_id}/events")
    def analysis_events(task_id: str):
        if registry.get(task_id) is None:
            raise HTTPException(status_code=404, detail="analysis task not found")

        def format_event(entry: dict) -> str:
            payload = json.dumps(entry["data"], ensure_ascii=False)
            return f"id: {entry['id']}\nevent: {entry['event']}\ndata: {payload}\n\n"

        def event_stream():
            last_event_id = 0
            while True:
                events = registry.events_since(task_id, last_event_id)
                if not events:
                    events = registry.wait_for_events(task_id, last_event_id, timeout=15)
                if not events:
                    yield ": keepalive\n\n"
                    continue
                for event in events:
                    last_event_id = event["id"]
                    yield format_event(event)
                    if event["event"] in {"task_completed", "task_failed"}:
                        return

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict:
        payload = chat_service.reply_payload(
            request.task_id,
            request.message,
            expert_mode=request.expert_mode,
            smart_search=request.smart_search,
            conversation_history=request.conversation_history,
        )
        return {
            "reply": payload["reply"],
            "sections": payload["sections"],
            "task_id": payload["task_id"],
            "ts_code": payload["ts_code"],
            "trade_date": payload["trade_date"],
            "task_status": payload["task_status"],
        }

    @app.post("/api/chat/stream")
    def chat_stream(request: ChatRequest):
        def format_chat_event(entry: dict) -> str:
            event_name = entry.get("event", "message")
            payload = json.dumps(entry.get("data", {}), ensure_ascii=False)
            return f"event: {event_name}\ndata: {payload}\n\n"

        def event_stream():
            for entry in chat_service.stream_reply_events(
                request.task_id,
                request.message,
                expert_mode=request.expert_mode,
                smart_search=request.smart_search,
                conversation_history=request.conversation_history,
            ):
                yield format_chat_event(entry)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("tradingagents.web.app:app", host="127.0.0.1", port=8000, reload=True)
