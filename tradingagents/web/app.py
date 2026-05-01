import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from tradingagents.dataflows.tushare_stock import get_stock_snapshot
from tradingagents.web.analysis_service import AnalysisService
from tradingagents.web.chat_service import ChatService
from tradingagents.web.schemas import AnalysisRequest, ChatRequest
from tradingagents.web.tasks import TaskRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSTATION_HTML = PROJECT_ROOT / "docs" / "design" / "a-share-workstation.html"


def create_app() -> FastAPI:
    load_dotenv()
    app = FastAPI(title="TradingAgents A Share Workstation")
    registry = TaskRegistry()
    analysis_service = AnalysisService(registry)
    chat_service = ChatService(registry)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return WORKSTATION_HTML.read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "data_source": "tushare",
            "tushare_configured": bool(os.getenv("TUSHARE_API_TOKEN")),
        }

    @app.get("/api/tushare/stocks/{ts_code}/snapshot")
    def stock_snapshot(ts_code: str, trade_date: str) -> dict:
        return get_stock_snapshot(ts_code, trade_date)

    @app.post("/api/analysis")
    def create_analysis(request: AnalysisRequest) -> dict:
        task = analysis_service.create_task(request)
        return {"task_id": task.task_id, "status": task.status}

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict:
        return {"reply": chat_service.reply(request.task_id, request.message)}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("tradingagents.web.app:app", host="127.0.0.1", port=8000, reload=True)
