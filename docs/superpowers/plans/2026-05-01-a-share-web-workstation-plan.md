# A Share Web Workstation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Web frontend for TradingAgents that serves the accepted A 股 workstation page, loads Tushare Pro data from `TUSHARE_API_TOKEN`, and exposes a first backend path for single-stock analysis and report-context chat.

**Architecture:** Add a small FastAPI web layer under `tradingagents/web/` and keep it separate from the existing CLI. Add a focused Tushare adapter under `tradingagents/dataflows/tushare_*.py`, route it through the existing vendor abstraction, and use an in-memory analysis task service for the first vertical slice. Serve the existing HTML prototype as the first UI and progressively wire it to JSON/SSE endpoints.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Pydantic, python-dotenv, pandas, tushare, existing TradingAgentsGraph, vanilla HTML/CSS/JS.

---

## File Structure

- Create `tradingagents/web/__init__.py`: package marker.
- Create `tradingagents/web/app.py`: FastAPI app factory, static HTML route, API route registration.
- Create `tradingagents/web/schemas.py`: Pydantic request/response models.
- Create `tradingagents/web/tasks.py`: in-memory task model and task registry.
- Create `tradingagents/web/analysis_service.py`: creates/runs analysis tasks and normalizes graph output.
- Create `tradingagents/web/chat_service.py`: report-context chat service.
- Create `tradingagents/dataflows/tushare_client.py`: thin Tushare client wrapper loading `TUSHARE_API_TOKEN`.
- Create `tradingagents/dataflows/tushare_stock.py`: stock OHLCV, daily basic, financial, and moneyflow fetch helpers.
- Modify `tradingagents/dataflows/interface.py`: register `tushare` vendor for stock, indicator, and fundamental categories.
- Modify `tradingagents/default_config.py`: add `tushare` as documented vendor option without changing current default until the Web path opts in.
- Modify `pyproject.toml`: add `fastapi`, `uvicorn`, `tushare`, and `python-dotenv`; add script `tradingagents-web`.
- Modify `docs/design/a-share-workstation.html`: move from mock-only JS to backend API calls while keeping static fallback copy.
- Create `tests/test_web_app.py`: health and route smoke tests.
- Create `tests/test_tushare_stock.py`: fake-client Tushare adapter tests.
- Create `tests/test_web_tasks.py`: analysis task lifecycle tests.
- Modify `tests/test_design_prototype.py`: assert Web API hooks exist in the page.

## Task 1: Web App Skeleton

**Files:**
- Create: `tradingagents/web/__init__.py`
- Create: `tradingagents/web/app.py`
- Create: `tests/test_web_app.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests for app creation and health**

Create `tests/test_web_app.py`:

```python
from fastapi.testclient import TestClient

from tradingagents.web.app import create_app


def test_health_reports_tushare_configuration(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data_source": "tushare",
        "tushare_configured": True,
    }


def test_index_serves_workstation_html():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "A股单股智能分析工作台" in response.text
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py -v
```

Expected: FAIL because `fastapi` and `tradingagents.web.app` do not exist yet.

- [ ] **Step 3: Add dependencies and script metadata**

Modify `pyproject.toml` dependencies:

```toml
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "tushare>=1.4.0",
    "python-dotenv>=1.0.1",
```

Modify `[project.scripts]`:

```toml
tradingagents = "cli.main:app"
tradingagents-web = "tradingagents.web.app:main"
```

- [ ] **Step 4: Implement app skeleton**

Create `tradingagents/web/__init__.py`:

```python
"""Web UI package for TradingAgents."""
```

Create `tradingagents/web/app.py`:

```python
from pathlib import Path
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSTATION_HTML = PROJECT_ROOT / "docs" / "design" / "a-share-workstation.html"


def create_app() -> FastAPI:
    load_dotenv()
    app = FastAPI(title="TradingAgents A Share Workstation")

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

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("tradingagents.web.app:app", host="127.0.0.1", port=8000, reload=True)
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py -v
```

Expected: PASS.

## Task 2: Tushare Client And Snapshot Adapter

**Files:**
- Create: `tradingagents/dataflows/tushare_client.py`
- Create: `tradingagents/dataflows/tushare_stock.py`
- Create: `tests/test_tushare_stock.py`
- Modify: `tradingagents/web/app.py`

- [ ] **Step 1: Write failing tests with a fake Tushare client**

Create `tests/test_tushare_stock.py`:

```python
import pandas as pd

from tradingagents.dataflows.tushare_stock import get_stock_snapshot


class FakeTushareClient:
    def daily(self, **kwargs):
        assert kwargs["ts_code"] == "600519.SH"
        return pd.DataFrame([
            {
                "ts_code": "600519.SH",
                "trade_date": "20260430",
                "open": 1660.0,
                "high": 1698.0,
                "low": 1650.0,
                "close": 1684.2,
                "pre_close": 1654.1,
                "pct_chg": 1.82,
                "amount": 4260000.0,
            }
        ])

    def daily_basic(self, **kwargs):
        assert kwargs["ts_code"] == "600519.SH"
        return pd.DataFrame([
            {
                "ts_code": "600519.SH",
                "trade_date": "20260430",
                "pe_ttm": 28.4,
                "pb": 8.2,
                "total_mv": 2110000.0,
            }
        ])


def test_get_stock_snapshot_normalizes_tushare_rows():
    snapshot = get_stock_snapshot(
        "600519.SH",
        "2026-04-30",
        client=FakeTushareClient(),
    )

    assert snapshot["ts_code"] == "600519.SH"
    assert snapshot["trade_date"] == "2026-04-30"
    assert snapshot["price"]["close"] == 1684.2
    assert snapshot["price"]["pct_chg"] == 1.82
    assert snapshot["daily_basic"]["pe_ttm"] == 28.4
    assert snapshot["daily_basic"]["pb"] == 8.2
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_tushare_stock.py -v
```

Expected: FAIL because `tradingagents.dataflows.tushare_stock` does not exist.

- [ ] **Step 3: Implement Tushare client wrapper**

Create `tradingagents/dataflows/tushare_client.py`:

```python
import os

from dotenv import load_dotenv


class TushareTokenError(RuntimeError):
    """Raised when Tushare token is missing."""


def create_tushare_client():
    load_dotenv()
    token = os.getenv("TUSHARE_API_TOKEN")
    if not token:
        raise TushareTokenError("TUSHARE_API_TOKEN is not configured")

    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()
```

- [ ] **Step 4: Implement snapshot adapter**

Create `tradingagents/dataflows/tushare_stock.py`:

```python
from datetime import datetime
from typing import Any

import pandas as pd

from .tushare_client import create_tushare_client


def _api_date(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%Y%m%d")


def _display_date(date: str) -> str:
    return datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")


def _first_record(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    return frame.iloc[0].where(pd.notnull(frame.iloc[0]), None).to_dict()


def get_stock_snapshot(ts_code: str, trade_date: str, client=None) -> dict[str, Any]:
    client = client or create_tushare_client()
    api_date = _api_date(trade_date)

    daily = _first_record(client.daily(ts_code=ts_code, trade_date=api_date))
    daily_basic = _first_record(client.daily_basic(ts_code=ts_code, trade_date=api_date))

    return {
        "ts_code": ts_code,
        "name": "",
        "trade_date": _display_date(daily.get("trade_date", api_date)),
        "price": {
            "open": daily.get("open"),
            "high": daily.get("high"),
            "low": daily.get("low"),
            "close": daily.get("close"),
            "pre_close": daily.get("pre_close"),
            "pct_chg": daily.get("pct_chg"),
            "amount": daily.get("amount"),
        },
        "daily_basic": {
            "pe_ttm": daily_basic.get("pe_ttm"),
            "pb": daily_basic.get("pb"),
            "total_mv": daily_basic.get("total_mv"),
        },
        "ohlcv": [],
    }
```

- [ ] **Step 5: Expose snapshot endpoint**

Modify `tradingagents/web/app.py` inside `create_app()`:

```python
    from tradingagents.dataflows.tushare_stock import get_stock_snapshot

    @app.get("/api/tushare/stocks/{ts_code}/snapshot")
    def stock_snapshot(ts_code: str, trade_date: str) -> dict:
        return get_stock_snapshot(ts_code, trade_date)
```

- [ ] **Step 6: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_tushare_stock.py tests/test_web_app.py -v
```

Expected: PASS.

## Task 3: Web Schemas And Task Registry

**Files:**
- Create: `tradingagents/web/schemas.py`
- Create: `tradingagents/web/tasks.py`
- Create: `tests/test_web_tasks.py`

- [ ] **Step 1: Write failing task registry tests**

Create `tests/test_web_tasks.py`:

```python
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
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_tasks.py -v
```

Expected: FAIL because schemas/tasks do not exist.

- [ ] **Step 3: Implement schemas**

Create `tradingagents/web/schemas.py`:

```python
from pydantic import BaseModel, Field, field_validator


class AnalysisRequest(BaseModel):
    ts_code: str
    trade_date: str
    analysts: list[str] = Field(default_factory=lambda: ["market", "fundamentals"])
    research_depth: int = 1
    llm_provider: str = "deepseek"
    quick_model: str = "deepseek-chat"
    deep_model: str = "deepseek-chat"

    @field_validator("ts_code")
    @classmethod
    def validate_a_share_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized.endswith((".SH", ".SZ", ".BJ")):
            raise ValueError("ts_code must end with .SH, .SZ, or .BJ")
        return normalized


class ChatRequest(BaseModel):
    task_id: str
    message: str
```

- [ ] **Step 4: Implement task registry**

Create `tradingagents/web/tasks.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from .schemas import AnalysisRequest


@dataclass
class AnalysisTask:
    task_id: str
    request: AnalysisRequest
    status: str = "queued"
    events: list[dict] = field(default_factory=list)
    report_sections: dict[str, str] = field(default_factory=dict)
    final_decision: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, AnalysisTask] = {}

    def create(self, request: AnalysisRequest) -> AnalysisTask:
        task = AnalysisTask(task_id=uuid4().hex, request=request)
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> AnalysisTask | None:
        return self._tasks.get(task_id)
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_tasks.py -v
```

Expected: PASS.

## Task 4: Analysis API Vertical Slice

**Files:**
- Create: `tradingagents/web/analysis_service.py`
- Modify: `tradingagents/web/app.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/test_web_app.py`:

```python
def test_create_analysis_task_returns_task_id(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())

    response = client.post("/api/analysis", json={
        "ts_code": "600519.SH",
        "trade_date": "2026-04-30",
        "analysts": ["market", "fundamentals"],
        "research_depth": 1,
        "llm_provider": "deepseek",
        "quick_model": "deepseek-chat",
        "deep_model": "deepseek-chat",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"]
    assert body["status"] == "queued"
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py::test_create_analysis_task_returns_task_id -v
```

Expected: FAIL because `/api/analysis` is missing.

- [ ] **Step 3: Implement analysis service**

Create `tradingagents/web/analysis_service.py`:

```python
from tradingagents.default_config import DEFAULT_CONFIG

from .schemas import AnalysisRequest
from .tasks import AnalysisTask, TaskRegistry


class AnalysisService:
    def __init__(self, registry: TaskRegistry) -> None:
        self.registry = registry

    def create_task(self, request: AnalysisRequest) -> AnalysisTask:
        return self.registry.create(request)

    def build_config(self, request: AnalysisRequest) -> dict:
        config = DEFAULT_CONFIG.copy()
        config["data_vendors"] = {
            "core_stock_apis": "tushare",
            "technical_indicators": "tushare",
            "fundamental_data": "tushare",
            "news_data": "tushare",
        }
        config["llm_provider"] = request.llm_provider
        config["quick_think_llm"] = request.quick_model
        config["deep_think_llm"] = request.deep_model
        config["max_debate_rounds"] = request.research_depth
        config["max_risk_discuss_rounds"] = request.research_depth
        config["output_language"] = "Chinese"
        return config
```

- [ ] **Step 4: Wire endpoint**

Modify `tradingagents/web/app.py` in `create_app()`:

```python
    from tradingagents.web.analysis_service import AnalysisService
    from tradingagents.web.schemas import AnalysisRequest
    from tradingagents.web.tasks import TaskRegistry

    registry = TaskRegistry()
    analysis_service = AnalysisService(registry)

    @app.post("/api/analysis")
    def create_analysis(request: AnalysisRequest) -> dict:
        task = analysis_service.create_task(request)
        return {"task_id": task.task_id, "status": task.status}
```

- [ ] **Step 5: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py tests/test_web_tasks.py -v
```

Expected: PASS.

## Task 5: Static Page API Hooks

**Files:**
- Modify: `docs/design/a-share-workstation.html`
- Modify: `tests/test_design_prototype.py`

- [ ] **Step 1: Add failing smoke expectations**

Modify `tests/test_design_prototype.py` required labels:

```python
        "/api/health",
        "/api/tushare/stocks/",
        "/api/analysis",
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
.venv/bin/python -c "from pathlib import Path; html=Path('docs/design/a-share-workstation.html').read_text(encoding='utf-8'); assert '/api/health' in html and '/api/tushare/stocks/' in html and '/api/analysis' in html"
```

Expected: FAIL until the page script calls those endpoints.

- [ ] **Step 3: Add frontend API helpers**

Modify the page script in `docs/design/a-share-workstation.html`:

```javascript
    async function loadHealth() {
      const response = await fetch("/api/health");
      return response.json();
    }

    async function loadSnapshot(tsCode, tradeDate) {
      const response = await fetch(`/api/tushare/stocks/${tsCode}/snapshot?trade_date=${tradeDate}`);
      return response.json();
    }

    async function createAnalysis(payload) {
      const response = await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      return response.json();
    }
```

- [ ] **Step 4: Use API in run button**

Modify the `runButton.addEventListener("click", ...)` handler so the first lines are:

```javascript
      const payload = {
        ts_code: "600519.SH",
        trade_date: "2026-04-30",
        analysts: ["market", "fundamentals"],
        research_depth: 1,
        llm_provider: "deepseek",
        quick_model: "deepseek-chat",
        deep_model: "deepseek-chat",
      };
      const task = await createAnalysis(payload);
      runHint.textContent = `任务已创建：${task.task_id}`;
```

- [ ] **Step 5: Run smoke verification**

Run:

```bash
.venv/bin/python -c "from pathlib import Path; html=Path('docs/design/a-share-workstation.html').read_text(encoding='utf-8'); assert '/api/health' in html and '/api/tushare/stocks/' in html and '/api/analysis' in html"
```

Expected: PASS.

## Task 6: Tushare Vendor Registration For Existing Tools

**Files:**
- Modify: `tradingagents/dataflows/interface.py`
- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/dataflows/tushare_stock.py`
- Create: `tests/test_tushare_vendor_routing.py`

- [ ] **Step 1: Write failing routing test**

Create `tests/test_tushare_vendor_routing.py`:

```python
from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS


def test_tushare_vendor_registered_for_core_analysis_methods():
    assert "tushare" in VENDOR_LIST
    assert "tushare" in VENDOR_METHODS["get_stock_data"]
    assert "tushare" in VENDOR_METHODS["get_indicators"]
    assert "tushare" in VENDOR_METHODS["get_fundamentals"]
    assert "tushare" in VENDOR_METHODS["get_balance_sheet"]
    assert "tushare" in VENDOR_METHODS["get_cashflow"]
    assert "tushare" in VENDOR_METHODS["get_income_statement"]
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_tushare_vendor_routing.py -v
```

Expected: FAIL because `tushare` is not registered.

- [ ] **Step 3: Add adapter functions**

Append to `tradingagents/dataflows/tushare_stock.py`:

```python
def get_stock_data(ts_code: str, start_date: str, end_date: str) -> str:
    client = create_tushare_client()
    frame = client.daily(
        ts_code=ts_code,
        start_date=_api_date(start_date),
        end_date=_api_date(end_date),
    )
    return frame.to_csv(index=False)


def get_indicators(ts_code: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    return (
        f"Tushare indicator adapter received {indicator} for {ts_code}. "
        "MVP computes technical indicators from pro_bar in the web layer."
    )


def get_fundamentals(ts_code: str, curr_date: str = "") -> str:
    snapshot = get_stock_snapshot(ts_code, curr_date or "2026-04-30")
    return str(snapshot["daily_basic"])


def get_balance_sheet(ts_code: str, freq: str = "annual", curr_date: str = "") -> str:
    client = create_tushare_client()
    return client.balancesheet(ts_code=ts_code).head(8).to_csv(index=False)


def get_cashflow(ts_code: str, freq: str = "annual", curr_date: str = "") -> str:
    client = create_tushare_client()
    return client.cashflow(ts_code=ts_code).head(8).to_csv(index=False)


def get_income_statement(ts_code: str, freq: str = "annual", curr_date: str = "") -> str:
    client = create_tushare_client()
    return client.income(ts_code=ts_code).head(8).to_csv(index=False)
```

- [ ] **Step 4: Register vendor**

Modify `tradingagents/dataflows/interface.py` imports:

```python
from .tushare_stock import (
    get_stock_data as get_tushare_stock_data,
    get_indicators as get_tushare_indicators,
    get_fundamentals as get_tushare_fundamentals,
    get_balance_sheet as get_tushare_balance_sheet,
    get_cashflow as get_tushare_cashflow,
    get_income_statement as get_tushare_income_statement,
)
```

Modify `VENDOR_LIST`:

```python
VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "tushare",
]
```

Modify `VENDOR_METHODS` by adding `"tushare": ...` entries for the methods listed in Step 1.

- [ ] **Step 5: Document config option**

Modify comments in `tradingagents/default_config.py`:

```python
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance, tushare
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance, tushare
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance, tushare
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
```

- [ ] **Step 6: Run routing test**

Run:

```bash
.venv/bin/python -m pytest tests/test_tushare_vendor_routing.py -v
```

Expected: PASS.

## Task 7: Report Context Chat MVP

**Files:**
- Create: `tradingagents/web/chat_service.py`
- Modify: `tradingagents/web/app.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Add failing chat endpoint test**

Append to `tests/test_web_app.py`:

```python
def test_chat_endpoint_returns_contextual_reply(monkeypatch):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app())
    created = client.post("/api/analysis", json={
        "ts_code": "600519.SH",
        "trade_date": "2026-04-30",
        "analysts": ["market", "fundamentals"],
        "research_depth": 1,
        "llm_provider": "deepseek",
        "quick_model": "deepseek-chat",
        "deep_model": "deepseek-chat",
    }).json()

    response = client.post("/api/chat", json={
        "task_id": created["task_id"],
        "message": "成交额下降怎么办？",
    })

    assert response.status_code == 200
    assert "reply" in response.json()
    assert "600519.SH" in response.json()["reply"]
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py::test_chat_endpoint_returns_contextual_reply -v
```

Expected: FAIL because `/api/chat` is missing.

- [ ] **Step 3: Implement deterministic MVP chat service**

Create `tradingagents/web/chat_service.py`:

```python
from .tasks import TaskRegistry


class ChatService:
    def __init__(self, registry: TaskRegistry) -> None:
        self.registry = registry

    def reply(self, task_id: str, message: str) -> str:
        task = self.registry.get(task_id)
        if task is None:
            return "未找到对应分析任务，请先运行一次单股分析。"

        return (
            f"基于 {task.request.ts_code} 在 {task.request.trade_date} 的 TradingAgents 报告，"
            "我会先检查趋势、估值、财务质量和 moneyflow。"
            f"你的问题是：{message}"
        )
```

- [ ] **Step 4: Wire endpoint**

Modify `tradingagents/web/app.py`:

```python
    from tradingagents.web.chat_service import ChatService
    from tradingagents.web.schemas import ChatRequest

    chat_service = ChatService(registry)

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> dict:
        return {"reply": chat_service.reply(request.task_id, request.message)}
```

- [ ] **Step 5: Run chat test**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py::test_chat_endpoint_returns_contextual_reply -v
```

Expected: PASS.

## Task 8: Launch And Browser Verification

**Files:**
- Modify only if verification finds a defect.

- [ ] **Step 1: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py tests/test_web_tasks.py tests/test_tushare_stock.py tests/test_tushare_vendor_routing.py tests/test_design_prototype.py -v
```

Expected: PASS.

- [ ] **Step 2: Start web server**

Run:

```bash
.venv/bin/python -m uvicorn tradingagents.web.app:app --host 127.0.0.1 --port 8000
```

Expected: server starts and logs Uvicorn running on `http://127.0.0.1:8000`.

- [ ] **Step 3: Open page in browser**

Open:

```text
http://127.0.0.1:8000/
```

Expected: A 股单股智能分析工作台 loads.

- [ ] **Step 4: Verify health call**

Open:

```text
http://127.0.0.1:8000/api/health
```

Expected:

```json
{"ok": true, "data_source": "tushare", "tushare_configured": true}
```

- [ ] **Step 5: Verify UI interaction**

In the browser:

1. Click `开始分析`.
2. Confirm task id appears in the hint text.
3. Confirm agent progress simulation completes.
4. Click `开启 Agent 对话`.
5. Send a chat message.
6. Confirm a reply appears.

Expected: no browser console errors and no blank page.

## Self-Review

- Spec coverage: Web page serving, Tushare token loading, snapshot API, analysis task creation, report-context chat, and browser verification are covered by Tasks 1-8.
- Scope control: Real SSE streaming and full TradingAgentsGraph execution are intentionally deferred until the Web skeleton, Tushare adapter, and task model are working. The plan creates the endpoint shapes needed for streaming later.
- Placeholder scan: The plan uses concrete paths, commands, and code snippets. No task uses “TBD” or “implement later”.
- Risk: `pyproject.toml` dependency installation may require network access. If dependency install is blocked, request permission to run the project dependency sync command with network access.
