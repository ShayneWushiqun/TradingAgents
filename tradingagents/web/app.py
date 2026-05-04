import base64
import hashlib
import hmac
import os
import json
import time
from pathlib import Path
from collections.abc import Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
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
SESSION_COOKIE_NAME = "tradingagents_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign_session(username: str, secret: str, now: int | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + SESSION_MAX_AGE_SECONDS,
    }
    encoded = _urlsafe_b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _verify_session(token: str | None, secret: str, now: int | None = None) -> bool:
    if not token or "." not in token or not secret:
        return False
    encoded, signature = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(_urlsafe_b64decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return False
    expires_at = int(payload.get("exp") or 0)
    return expires_at > int(now if now is not None else time.time())


def _login_html(auth_enabled: bool, username: str) -> str:
    disabled_note = "" if auth_enabled else "<p class=\"note\">当前未配置登录密码，访问保护未开启。</p>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>A-Share Insight 登录</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
      background: #eef4fb;
      color: #111827;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }}
    .panel {{
      width: min(420px, 100%);
      background: #fff;
      border: 1px solid #d8e2f0;
      border-radius: 12px;
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
      padding: 32px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    p {{ margin: 0 0 24px; color: #667085; font-weight: 600; }}
    label {{ display: block; margin: 18px 0 8px; color: #667085; font-weight: 700; }}
    input {{
      width: 100%;
      box-sizing: border-box;
      border: 1px solid #d8e2f0;
      border-radius: 10px;
      padding: 14px 16px;
      font: inherit;
      font-weight: 700;
    }}
    button {{
      width: 100%;
      margin-top: 24px;
      border: 0;
      border-radius: 10px;
      padding: 14px 16px;
      font: inherit;
      font-weight: 800;
      color: #fff;
      background: #2563eb;
      cursor: pointer;
    }}
    .error {{ min-height: 22px; margin-top: 14px; color: #dc2626; font-weight: 700; }}
    .note {{ margin-top: 16px; color: #b45309; }}
  </style>
</head>
<body>
  <main class="panel">
    <h1>A-Share Insight</h1>
    <p>登录后继续使用投研工作台。</p>
    <form id="login-form">
      <label for="username">用户名</label>
      <input id="username" name="username" autocomplete="username" value="{username}" />
      <label for="password">密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password" autofocus />
      <button type="submit">登录</button>
      <div class="error" id="error"></div>
    </form>
    {disabled_note}
  </main>
  <script>
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next") || "/";
    document.querySelector("#login-form").addEventListener("submit", async (event) => {{
      event.preventDefault();
      const error = document.querySelector("#error");
      error.textContent = "";
      const response = await fetch("/api/login", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{
          username: document.querySelector("#username").value,
          password: document.querySelector("#password").value
        }})
      }});
      if (!response.ok) {{
        error.textContent = "用户名或密码错误";
        return;
      }}
      window.location.href = next;
    }});
  </script>
</body>
</html>"""


def create_app(
    analysis_runner: AnalysisRunner | None = None,
    runtime_dir: str | Path | None = None,
    database_url: str | None = None,
    require_database: bool = False,
    load_env_file: bool = False,
    auth_password: str | None = None,
    auth_username: str | None = None,
    require_auth: bool = False,
    hot_snapshot_getter: Callable[[str, int], dict] | None = None,
    trade_dates_getter: Callable[[str | None, int], list[str]] | None = None,
    enable_hot_radar_scheduler: bool | None = None,
) -> FastAPI:
    if load_env_file:
        load_dotenv(PROJECT_ROOT / ".env")
    app = FastAPI(title="TradingAgents A Share Workstation")
    registry = TaskRegistry()
    runtime_root = Path(runtime_dir) if runtime_dir is not None else DEFAULT_RUNTIME_DIR
    cache = AnalysisCache(cache_dir=runtime_root / "cache")
    store = None
    store_error = ""
    database_url_configured = (
        str(database_url).strip()
        if database_url is not None
        else (os.getenv("TRADINGAGENTS_DB_URL", "").strip() if load_env_file else "")
    )
    if require_database and not database_url_configured:
        raise RuntimeError("TRADINGAGENTS_DB_URL is required; runtime DB must be MySQL.")
    if database_url_configured:
        try:
            store = AnalysisStore(database_url_configured)
        except Exception as exc:  # pragma: no cover - depends on local database
            store_error = str(exc)
            if require_database:
                raise RuntimeError(f"Unable to initialize MySQL AnalysisStore: {exc}") from exc
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
    hot_radar_service = None
    hot_radar_store_error = ""
    if database_url_configured:
        try:
            hot_radar_service = HotRadarService.from_runtime(
                analysis_service=analysis_service,
                database_url=database_url_configured,
                runtime_dir=runtime_root,
                hot_snapshot_getter=hot_snapshot_getter,
                trade_dates_getter=trade_dates_getter,
            )
        except Exception as exc:  # pragma: no cover - depends on local database
            hot_radar_store_error = str(exc)
            if require_database:
                raise RuntimeError(f"Unable to initialize MySQL HotRadarStore: {exc}") from exc
    elif require_database:
        raise RuntimeError("TRADINGAGENTS_DB_URL is required for Hot Radar storage.")
    app.state.hot_radar_service = hot_radar_service
    app.state.hot_radar_store_error = hot_radar_store_error
    scheduler_enabled = (
        enable_hot_radar_scheduler
        if enable_hot_radar_scheduler is not None
        else os.getenv("HOT_RADAR_SCHEDULER_ENABLED", "1") != "0"
    )
    hot_radar_scheduler = HotRadarScheduler(hot_radar_service) if hot_radar_service is not None else None
    app.state.hot_radar_scheduler = hot_radar_scheduler
    auth_password_configured = (
        str(auth_password).strip()
        if auth_password is not None
        else (os.getenv("TRADINGAGENTS_WEB_PASSWORD", "").strip() if load_env_file else "")
    )
    auth_username_configured = (
        str(auth_username).strip()
        if auth_username is not None
        else (os.getenv("TRADINGAGENTS_WEB_USERNAME", "admin").strip() if load_env_file else "admin")
    ) or "admin"
    auth_secret = os.getenv("TRADINGAGENTS_WEB_SECRET", "").strip() if load_env_file else ""
    if not auth_secret:
        auth_secret = auth_password_configured
    auth_enabled = bool(auth_password_configured)
    if require_auth and not auth_enabled:
        raise RuntimeError("TRADINGAGENTS_WEB_PASSWORD is required when web authentication is required.")
    cookie_secure = os.getenv("TRADINGAGENTS_COOKIE_SECURE", "0") == "1" if load_env_file else False
    app.state.auth_enabled = auth_enabled

    def is_authenticated(request: Request) -> bool:
        if not auth_enabled:
            return True
        return _verify_session(request.cookies.get(SESSION_COOKIE_NAME), auth_secret)

    def is_public_path(path: str) -> bool:
        return path in {"/login", "/api/login", "/api/logout", "/api/health"} or path.startswith("/favicon")

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        if is_public_path(request.url.path) or is_authenticated(request):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "not authenticated"}, status_code=401)
        next_url = request.url.path
        if request.url.query:
            next_url += f"?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)

    @app.on_event("startup")
    def start_hot_radar_scheduler() -> None:
        if scheduler_enabled and hot_radar_scheduler is not None:
            hot_radar_scheduler.start()

    @app.on_event("shutdown")
    def stop_hot_radar_scheduler() -> None:
        if hot_radar_scheduler is not None:
            hot_radar_scheduler.stop()

    app.mount(
        "/design",
        StaticFiles(directory=str(DESIGN_STATIC_DIR)),
        name="design_static",
    )

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if auth_enabled and is_authenticated(request):
            return RedirectResponse("/", status_code=303)
        return _login_html(auth_enabled, auth_username_configured)

    @app.post("/api/login")
    async def login(request: Request) -> Response:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        username = str(payload.get("username") or auth_username_configured).strip()
        password = str(payload.get("password") or "")
        if not auth_enabled:
            return JSONResponse({"ok": True, "auth_enabled": False})
        if not hmac.compare_digest(username, auth_username_configured) or not hmac.compare_digest(
            password,
            auth_password_configured,
        ):
            raise HTTPException(status_code=401, detail="invalid credentials")
        response = JSONResponse({"ok": True, "auth_enabled": True})
        response.set_cookie(
            SESSION_COOKIE_NAME,
            _sign_session(username, auth_secret),
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=cookie_secure,
        )
        return response

    @app.post("/api/logout")
    def logout() -> Response:
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE_NAME)
        return response

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
            "auth_enabled": auth_enabled,
            "analysis_store_configured": bool(database_url_configured),
            "analysis_store_available": store is not None,
            "analysis_store_error": store_error,
            "hot_radar_store_configured": bool(database_url_configured),
            "hot_radar_store_available": hot_radar_service is not None,
            "hot_radar_store_error": hot_radar_store_error,
            "database_required": require_database,
        }

    def require_hot_radar_service() -> HotRadarService:
        if hot_radar_service is None:
            detail = hot_radar_store_error or "TRADINGAGENTS_DB_URL is required; Hot Radar storage must use MySQL."
            raise HTTPException(status_code=503, detail=detail)
        return hot_radar_service

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
        service = require_hot_radar_service()
        return {"items": service.trade_dates(end_date=end_date, limit=limit)}

    @app.get("/api/hot-radar")
    def hot_radar_dashboard(
        trade_date: str,
        batch_time: str = "daily",
        top_n: int = 20,
        fetch_if_missing: bool = True,
    ) -> dict:
        """``fetch_if_missing`` (default True): walks open days backward until a non-empty snapshot is found or pulled."""

        service = require_hot_radar_service()
        return service.get_dashboard(
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

        service = require_hot_radar_service()
        return service.sync_hot_snapshot_from_source(
            request.trade_date,
            request.batch_time,
            top_n=request.top_n,
            force_refresh=request.force_refresh,
        )

    @app.post("/api/hot-radar/run")
    def run_hot_radar(request: HotRadarRunRequest) -> dict:
        service = require_hot_radar_service()
        return service.run_batch(
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


app = create_app(require_database=True, load_env_file=True)


def main() -> None:
    import uvicorn

    uvicorn.run("tradingagents.web.app:app", host="127.0.0.1", port=8000, reload=True)
