# Analysis Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real model-aware analysis queue with Hot Radar parameter modal, Analyze-page model selection, priority controls, stop/delete semantics, and queue-list removal separate from historical report deletion.

**Architecture:** Add queue metadata to `AnalysisTask`, move dispatch responsibility from immediate ad-hoc threads into `AnalysisService` lane scheduling, and expose queue-specific APIs from `tradingagents/web/app.py`. Frontend changes stay in the existing design prototypes: `a-share-workstation.html` owns Analyze parameters and `hot-radar.html` owns modal + queue panel.

**Tech Stack:** Python/FastAPI, existing in-memory `TaskRegistry`, optional MySQL-backed `AnalysisStore`, static HTML/CSS/JS prototypes, pytest.

---

### Task 1: Queue Metadata And Lane Scheduling

**Files:**
- Modify: `tradingagents/web/tasks.py`
- Modify: `tradingagents/web/analysis_service.py`
- Test: `tests/test_analysis_queue.py`

- [ ] **Step 1: Write failing backend queue tests**

Create `tests/test_analysis_queue.py` with tests for Pro lane 1 concurrency, Flash lane 3 concurrency, Analyze-origin priority, and queued/stopped deletion semantics:

```python
from threading import Event

from tradingagents.web.analysis_service import AnalysisService
from tradingagents.web.schemas import AnalysisRequest
from tradingagents.web.tasks import TaskRegistry


def _request(code, model="deepseek-v4-pro", origin="hot_radar"):
    return AnalysisRequest(
        ts_code=code,
        stock_name=code,
        trade_date="2026-04-30",
        analysts=["market"],
        research_depth=3,
        quick_model=model,
        deep_model=model,
        origin=origin,
    )


def test_pro_lane_runs_only_one_task_at_a_time():
    started = []
    blocker = Event()

    def runner(request, config, emit):
        started.append(request.ts_code)
        blocker.wait(0.3)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    first = service.create_task(_request("600001.SH", "deepseek-v4-pro"))
    second = service.create_task(_request("600002.SH", "deepseek-v4-pro"))

    assert first.status in {"queued", "running"}
    assert second.status == "queued"
    assert service.queue_status()["lanes"]["pro"]["capacity"] == 1
    assert len(service.queue_status()["lanes"]["pro"]["running"]) == 1
    assert len(service.queue_status()["lanes"]["pro"]["queued"]) == 1
    blocker.set()


def test_flash_lane_runs_three_tasks_at_a_time():
    blocker = Event()

    def runner(request, config, emit):
        blocker.wait(0.3)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    for suffix in range(4):
        service.create_task(_request(f"60000{suffix}.SH", "deepseek-v4-flash"))

    lane = service.queue_status()["lanes"]["flash"]
    assert lane["capacity"] == 3
    assert len(lane["running"]) == 3
    assert len(lane["queued"]) == 1
    blocker.set()


def test_analyze_origin_outranks_hot_radar_in_same_lane():
    blocker = Event()

    def runner(request, config, emit):
        blocker.wait(0.3)
        return ({"final_trade_decision": "Rating: Hold"}, "Hold")

    service = AnalysisService(TaskRegistry(), runner=runner, run_inline=False)
    service.create_task(_request("600001.SH", "deepseek-v4-pro", origin="hot_radar"))
    hot = service.create_task(_request("600002.SH", "deepseek-v4-pro", origin="hot_radar"))
    manual = service.create_task(_request("600003.SH", "deepseek-v4-pro", origin="analyze"))

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
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_analysis_queue.py -q
```

Expected: fail because `AnalysisRequest.origin`, queue lane scheduling, `queue_status()`, and `delete_queue_entry()` do not exist.

- [ ] **Step 3: Implement queue metadata and scheduler**

Update `AnalysisRequest` with:

```python
origin: str = "analyze"
```

Add validators to keep origin in `{"analyze", "hot_radar"}`.

Update `AnalysisTask` with:

```python
origin: str = "analyze"
lane: str = "pro"
priority: int = 50
queue_position: int = 0
stop_requested: bool = False
removed_from_queue: bool = False
```

Add registry helpers:

```python
def queued_for_lane(self, lane: str) -> list[AnalysisTask]: ...
def running_for_lane(self, lane: str) -> list[AnalysisTask]: ...
def mark_removed_from_queue(self, task_id: str) -> AnalysisTask | None: ...
```

In `AnalysisService.create_task()`, create tasks as queued and call `_dispatch_queue()` rather than starting a thread directly. `_dispatch_queue()` should start up to 1 Pro task and 3 Flash tasks using existing `_run_task()`.

- [ ] **Step 4: Run tests to verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_analysis_queue.py -q
```

Expected: pass.

### Task 2: Queue API Endpoints

**Files:**
- Modify: `tradingagents/web/app.py`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write failing API tests**

Add tests covering `GET /api/analysis/queue`, priority move, stop, and queue delete:

```python
def test_analysis_queue_endpoint_reports_lanes(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app(analysis_runner=lambda request, config, emit: ({}, ""), runtime_dir=tmp_path))
    created = client.post("/api/analysis", json={"ts_code": "600519.SH", "trade_date": "2026-04-30"}).json()

    response = client.get("/api/analysis/queue")

    assert response.status_code == 200
    body = response.json()
    assert body["lanes"]["pro"]["capacity"] == 1
    assert body["lanes"]["flash"]["capacity"] == 3
    assert created["task_id"] in {row["task_id"] for row in body["lanes"]["pro"]["running"] + body["lanes"]["pro"]["queued"]}


def test_queue_delete_does_not_delete_completed_history(monkeypatch, tmp_path):
    monkeypatch.setenv("TUSHARE_API_TOKEN", "test-token")
    client = TestClient(create_app(analysis_runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"), runtime_dir=tmp_path))
    created = client.post("/api/analysis", json={"ts_code": "600519.SH", "trade_date": "2026-04-30"}).json()

    response = client.delete(f"/api/analysis/queue/{created['task_id']}")
    history = client.get("/api/analysis/history").json()

    assert response.status_code == 200
    assert any(row["task_id"] == created["task_id"] for row in history["items"])
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py::test_analysis_queue_endpoint_reports_lanes tests/test_web_app.py::test_queue_delete_does_not_delete_completed_history -q
```

Expected: fail because endpoints do not exist.

- [ ] **Step 3: Add endpoints**

Add in `tradingagents/web/app.py` before `/api/analysis/{task_id}`:

```python
@app.get("/api/analysis/queue")
def analysis_queue() -> dict:
    return analysis_service.queue_status()

@app.post("/api/analysis/{task_id}/priority")
def analysis_queue_priority(task_id: str, request: dict) -> dict:
    return analysis_service.move_queue_task(task_id, direction=str(request.get("direction", "")))

@app.post("/api/analysis/{task_id}/stop")
def analysis_queue_stop(task_id: str) -> dict:
    return analysis_service.stop_task(task_id)

@app.delete("/api/analysis/queue/{task_id}")
def analysis_queue_delete(task_id: str) -> dict:
    result = analysis_service.delete_queue_entry(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="analysis task not found")
    return result
```

- [ ] **Step 4: Run tests to verify green**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_app.py::test_analysis_queue_endpoint_reports_lanes tests/test_web_app.py::test_queue_delete_does_not_delete_completed_history -q
```

Expected: pass.

### Task 3: Analyze Page Model Selector

**Files:**
- Modify: `docs/design/a-share-workstation.html`
- Test: `tests/test_design_prototype.py`

- [ ] **Step 1: Write failing design test**

Add assertions that Analyze page contains a model segmented control before action buttons and that it updates `TRADINGAGENTS_REPORT_MODEL`.

- [ ] **Step 2: Run test to verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_design_prototype.py::test_workstation_uses_pro_model_for_standard_and_deep_analysis -q
```

Expected: fail until markup exists.

- [ ] **Step 3: Add Analyze model selector**

Insert after research depth:

```html
<h3 class="block-title">报告分析模型</h3>
<div class="segmented report-model-segmented" id="report-model-selector" role="radiogroup" aria-label="报告分析模型">
  <button type="button" class="segment active" data-report-model="deepseek-v4-pro" aria-checked="true">V4 Pro</button>
  <button type="button" class="segment" data-report-model="deepseek-v4-flash" aria-checked="false">V4 Flash</button>
</div>
<p class="hint model-hint" id="report-model-hint">当前报告分析使用 DeepSeek V4 Pro</p>
```

Wire buttons to local storage and reuse `getSelectedReportModel()` in `buildAnalysisPayload()`.

- [ ] **Step 4: Run tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_design_prototype.py -q
```

Expected: pass.

### Task 4: Hot Radar Modal And Queue Panel

**Files:**
- Modify: `docs/design/hot-radar.html`
- Test: `tests/test_design_prototype.py`

- [ ] **Step 1: Write failing design tests**

Assert Hot Radar contains `analysis-modal`, `openAnalysisModal`, `submitAnalysisModal`, `queue-panel`, `loadAnalysisQueue`, and does not directly navigate to Analyze on row analysis click.

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
.venv/bin/python -m pytest tests/test_design_prototype.py::test_hot_radar_calendar_sync_and_row_level_analysis_buttons -q
```

Expected: fail until modal and queue markup exists.

- [ ] **Step 3: Add modal markup and JS**

Add modal controls for analysts, depth, and model. On submit POST:

```js
{
  ts_code,
  stock_name,
  trade_date,
  analysts,
  research_depth,
  quick_model: selectedModel,
  deep_model: selectedModel,
  origin: "hot_radar"
}
```

After submit, close modal and call `loadAnalysisQueue()`.

- [ ] **Step 4: Add queue panel**

Render lanes:

```js
lanes.pro.capacity === 1
lanes.flash.capacity === 3
```

Queued rows get up/down/delete. Running rows get stop. Completed rows get report/remove.

- [ ] **Step 5: Run design tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_design_prototype.py -q
```

Expected: pass.

### Task 5: Full Regression And Browser Check

**Files:**
- No production files unless verification exposes bugs.

- [ ] **Step 1: Run full tests**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Start server**

Run:

```bash
.venv/bin/python -m uvicorn tradingagents.web.app:app --host 127.0.0.1 --port 8000
```

Expected: server starts.

- [ ] **Step 3: Browser verify**

Check:

- Analyze page shows report model selector.
- Hot Radar row `分析` opens modal.
- Modal submit adds queue row.
- Pro lane displays capacity 1.
- Flash lane displays capacity 3.
- Queued row has move/delete controls.
- Running row has stop control.
- Completed row can be removed from queue list while remaining in Reports.
