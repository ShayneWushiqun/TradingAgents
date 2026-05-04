from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import re
import threading

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.tushare_stock import resolve_stock_name
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpointer import clear_checkpoint
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .analysis_cache import AnalysisCache
from .analysis_store import AnalysisStore
from .schemas import AnalysisRequest
from .tasks import AnalysisTask, TaskRegistry, extract_report_sections


AnalysisRunner = Callable[[AnalysisRequest, dict, Callable[[str, dict], None]], tuple[dict, str]]
RAW_LOG_TICKER_ERROR = "unsupported operand type(s) for /: 'PosixPath' and 'NoneType'"


def _clean_extracted_stock_name(value: str) -> str:
    name = re.sub(r"[`\"'“”‘’\s]+", "", str(value or "")).strip()
    if not re.search(r"[\u4e00-\u9fff]", name):
        return ""
    if name in {"股票代码", "证券代码", "代码", "报告日期", "分析日期", "交易日"}:
        return ""
    return name if len(name) <= 40 else ""


def _extract_stock_name_from_text(text: str, ts_code: str) -> str:
    code = str(ts_code or "").strip().upper()
    if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
        return ""
    body = str(text or "")
    if not body:
        return ""
    code_pattern = re.escape(code)
    patterns = [
        rf"`?\s*{code_pattern}\s*`?\s*[（(]\s*([^（）()\n\r]{{2,40}})\s*[）)]",
        rf"([^，。；;：:\n\r（）()]{{2,40}})\s*[（(]\s*(?:股票代码|证券代码)?\s*[:：]?\s*`?\s*{code_pattern}\s*`?\s*[）)]",
    ]
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.IGNORECASE)
        name = _clean_extracted_stock_name(match.group(1) if match else "")
        if name:
            return name
    return ""


class AnalysisService:
    def __init__(
        self,
        registry: TaskRegistry,
        runner: AnalysisRunner | None = None,
        run_inline: bool = False,
        cache: AnalysisCache | None = None,
        runtime_dir: str | Path | None = None,
        store: AnalysisStore | None = None,
    ) -> None:
        self.registry = registry
        self.runner = runner or self._run_trading_graph
        self.run_inline = run_inline
        self.cache = cache or AnalysisCache()
        self.runtime_dir = Path(runtime_dir) if runtime_dir is not None else None
        self.store = store
        self._dispatch_lock = threading.RLock()

    def create_task(self, request: AnalysisRequest) -> AnalysisTask:
        request = self._with_stock_name(request)
        task = self.registry.create(request)
        self._sync_store(task)
        if not request.force_refresh:
            cached = self.cache.get(request)
            if cached is not None:
                self.registry.complete_from_cache(task.task_id, cached)
                self._sync_store(task)
                return task
        self._dispatch_queue()
        return task

    def restore_cached_task(self, request: AnalysisRequest) -> AnalysisTask | None:
        request = self._with_stock_name(request)
        cached = self.cache.get(request)
        if cached is None:
            return None
        task = self.registry.create(request)
        self.registry.complete_from_cache(task.task_id, cached)
        self._sync_store(task)
        return task

    def queue_status(self) -> dict:
        lanes = {}
        seen: set[str] = set()
        for lane, capacity in (("pro", 1), ("flash", 3)):
            lanes[lane] = {
                "capacity": capacity,
                "running": [self._task_queue_payload(task) for task in self.registry.running_for_lane(lane)],
                "queued": [self._task_queue_payload(task) for task in self.registry.queued_for_lane(lane)],
                "finished": [
                    self._task_queue_payload(task)
                    for task in self.registry.queue_visible_for_lane(
                        lane,
                        {"failed", "stopped", "stopping"},
                    )
                ],
            }
            for group in ("running", "queued", "finished"):
                seen.update(row["task_id"] for row in lanes[lane][group])
        self._merge_store_active_tasks_into_queue(lanes, seen)
        return {"lanes": lanes}

    def delete_queue_entry(self, task_id: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status in {"queued", "stopped"}:
            memory_deleted = self.registry.delete(task_id) is not None
            store_deleted = False
            if self.store is not None:
                store_deleted = self.store.delete_task(task_id)
            deleted = bool(memory_deleted or store_deleted)
            return {
                "deleted": deleted,
                "removed_from_queue": deleted,
                "task_id": task_id,
                "status": task.status,
            }
        task = self.registry.mark_removed_from_queue(task_id)
        if task is None:
            return None
        self._sync_store(task)
        return {
            "deleted": False,
            "removed_from_queue": True,
            "task_id": task_id,
            "status": task.status,
        }

    def stop_task(self, task_id: str) -> dict | None:
        memory_task = self.registry.get(task_id)
        task = memory_task or self.get_task(task_id)
        if task is None:
            return None
        if task.status == "queued":
            stopped = self.registry.mark_stopped(task_id)
            if stopped is not None:
                self._sync_store(stopped)
            return {"task_id": task_id, "status": "stopped", "stop_requested": True}
        if task.status == "stopping":
            """Idempotent stop: a second click force-clears a runner-stuck ``stopping`` state.

            Without this, tasks whose runner already exited (server reload, crash,
            or runner short-circuit) would be permanently stuck at ``stopping`` and
            the UI would show「停止」 forever with no effect.

            """
            stopped = self.registry.mark_stopped(task_id)
            if stopped is not None:
                self._sync_store(stopped)
                self._dispatch_queue()
            return {"task_id": task_id, "status": "stopped", "stop_requested": True}
        if task.status == "running":
            if memory_task is None:
                stopped = self.registry.mark_stopped(task_id)
                if stopped is not None:
                    self._sync_store(stopped)
                self._dispatch_queue()
                return {"task_id": task_id, "status": "stopped", "stop_requested": True}
            task.stop_requested = True
            task.status = "stopping"
            self._sync_store(task)
            self._dispatch_queue()
            return {"task_id": task_id, "status": "stopping", "stop_requested": True}
        return {"task_id": task_id, "status": task.status, "stop_requested": task.stop_requested}

    def move_queue_task(self, task_id: str, direction: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status != "queued":
            return {"task_id": task_id, "status": task.status, "moved": False}
        lane_tasks = self.registry.queued_for_lane(task.lane)
        index = next((i for i, item in enumerate(lane_tasks) if item.task_id == task_id), -1)
        if index < 0:
            return {"task_id": task_id, "status": task.status, "moved": False}
        target = index - 1 if direction == "up" else index + 1 if direction == "down" else index
        if target < 0 or target >= len(lane_tasks) or target == index:
            return {"task_id": task_id, "status": task.status, "moved": False}
        other = lane_tasks[target]
        task.queue_position, other.queue_position = other.queue_position, task.queue_position
        self._sync_store(task)
        self._sync_store(other)
        return {"task_id": task_id, "status": task.status, "moved": True}

    def latest_task(self) -> AnalysisTask | None:
        task = self.registry.latest()
        if task is not None:
            self._repair_task_status(task)
            return task
        if self.store is not None:
            stored = self.store.latest_task()
            if stored is not None:
                task = self._restore_stored_task(stored)
                if task is not None:
                    return task
        if self.store is None:
            cached = self.cache.latest()
            if cached is None:
                return None
            request = AnalysisRequest(**cached["request"])
            task = self.registry.create(request)
            self.registry.complete_from_cache(task.task_id, cached)
            self._sync_store(task)
            return task
        return None

    def get_task(self, task_id: str) -> AnalysisTask | None:
        task = self.registry.get(task_id)
        if task is not None:
            self._repair_task_status(task)
            return task
        if self.store is None and isinstance(task_id, str) and task_id.startswith("cache:"):
            cache_key = task_id[len("cache:") :]
            data = self.cache.load_by_key(cache_key)
            if data is None:
                return None
            try:
                request = AnalysisRequest(**(data.get("request") or {}))
            except Exception:
                return None
            request = self._with_stock_name(request)
            restored = self.registry.restore(
                task_id,
                request,
                "completed",
                report_sections=data.get("report_sections") or {},
                final_decision=str(data.get("final_decision") or ""),
                decision=str(data.get("decision") or ""),
                cached=True,
            )
            self._sync_store(restored)
            return restored
        if self.store is None:
            return None
        stored = self.store.get_task(task_id)
        if stored is None:
            return None
        return self._restore_stored_task(stored)

    def clear_completed_history(self) -> dict:
        """Hide completed analyses from Reports without deleting report files.

        Persistent rows are soft-deleted so the DB remains auditable. In-memory
        completed tasks are removed only from the visible runtime registry.
        Running / queued / stopping / failed / stopped tasks are not touched.

        """

        deleted_tasks: int = 0
        deleted_cache_files: int = 0
        deleted_runtime_files: int = 0

        if self.store is not None:
            deleted_tasks += self.store.soft_delete_completed()

        for task in self.registry.list_recent(200, status="completed"):
            if self.registry.delete(task.task_id) is not None:
                deleted_tasks += 1

        return {
            "deleted_tasks": deleted_tasks,
            "deleted_cache_files": deleted_cache_files,
            "deleted_runtime_files": deleted_runtime_files,
        }

    def delete_task(self, task_id: str) -> dict | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        if task.status in {"queued", "running"}:
            return {
                "deleted": False,
                "task_id": task_id,
                "status": task.status,
                "deleted_files": 0,
                "blocked": True,
            }

        if task.status == "completed":
            store_deleted = False
            if self.store is not None:
                store_deleted = self.store.soft_delete_task(task_id)
            memory_deleted = self.registry.delete(task_id) is not None
            return {
                "deleted": bool(store_deleted or memory_deleted),
                "task_id": task_id,
                "status": task.status,
                "deleted_files": 0,
                "blocked": False,
                "soft_deleted": True,
            }

        deleted_files = self.cache.delete(task.request)
        deleted_files.extend(self._delete_runtime_report_files(task.request))
        self._clear_runtime_checkpoint(task.request)

        store_deleted = False
        if self.store is not None:
            store_deleted = self.store.delete_task(task_id)
        memory_deleted = self.registry.delete(task_id) is not None
        return {
            "deleted": bool(store_deleted or memory_deleted),
            "task_id": task_id,
            "status": task.status,
            "deleted_files": len(deleted_files),
            "blocked": False,
        }

    def _dispatch_queue(self) -> None:
        with self._dispatch_lock:
            for lane, capacity in (("pro", 1), ("flash", 3)):
                available = capacity - len(self.registry.running_for_lane(lane))
                if available <= 0:
                    continue
                for task in self.registry.queued_for_lane(lane)[:available]:
                    self._start_task(task)

    def _start_task(self, task: AnalysisTask) -> None:
        self.registry.start(task.task_id)
        self._sync_store(task)
        if self.run_inline:
            self._run_task(task, already_started=True)
            return
        thread = threading.Thread(target=self._run_task, args=(task, True), daemon=True)
        thread.start()

    def _run_task(self, task: AnalysisTask, already_started: bool = False) -> None:
        if not already_started:
            self.registry.start(task.task_id)
            self._sync_store(task)
        self.registry.add_event(
            task.task_id,
            "task_progress",
            {
                "stage": "initializing",
                "message": "任务已进入后端队列，正在初始化 TradingAgentsGraph。",
            },
        )

        def emit(event: str, data: dict) -> None:
            if event == "report_section":
                section = data.get("section")
                content = data.get("content")
                if section and isinstance(content, str):
                    task.report_sections[str(section)] = content
                    if str(section) == "final_trade_decision":
                        task.final_decision = content
                    self._sync_store(task)
            self.registry.add_event(task.task_id, event, data)

        try:
            self.registry.add_event(
                task.task_id,
                "task_progress",
                {
                    "stage": "running_graph",
                    "message": "正在加载 Tushare 数据源和 LLM 配置，准备执行多智能体流程。",
                },
            )
            final_state, decision = self.runner(task.request, self.build_config(task.request), emit)
        except Exception as exc:  # pragma: no cover - exact provider errors vary
            if task.stop_requested or task.status == "stopping":
                stopped = self.registry.mark_stopped(task.task_id)
                if stopped is not None:
                    self._sync_store(stopped)
                self._dispatch_queue()
                return
            self.registry.fail(task.task_id, str(exc))
            self._sync_store(task)
            self._dispatch_queue()
            return

        if task.stop_requested or task.status == "stopping":
            stopped = self.registry.mark_stopped(task.task_id)
            if stopped is not None:
                self._sync_store(stopped)
            self._dispatch_queue()
            return

        report_sections = {**task.report_sections, **extract_report_sections(final_state)}
        self.cache.set(task.request, final_state, decision, report_sections)
        self.registry.complete(task.task_id, final_state, decision)
        self._sync_store(task)
        self._dispatch_queue()

    def history(self, limit: int = 50, status: str | None = None) -> list[dict]:
        """Merged history from (1) persistent store, (2) in-memory registry, (3) on-disk cache.

        On-disk cache is the only **durable** evidence of completion when no
        ``AnalysisStore`` is configured — without merging it in, every server
        reload would visually erase past completed analyses from Hot Radar.

        """

        capped = max(1, min(int(limit), 200))
        wanted = str(status or "").strip()

        rows: list[dict] = []
        seen_ids: set[str] = set()
        seen_keys: set[str] = set()

        def absorb(row: dict) -> None:
            row_status = str(row.get("status") or "")
            if wanted and row_status != wanted:
                return
            tid = str(row.get("task_id") or "")
            ck = str(row.get("cache_key") or "")
            if tid and tid in seen_ids:
                return
            if ck and ck in seen_keys:
                return
            if tid:
                seen_ids.add(tid)
            if ck:
                seen_keys.add(ck)
            rows.append(row)

        if self.store is not None:
            store_buckets: list[list[dict]] = []
            if wanted == "completed":
                store_buckets.append(self.store.history(limit=200, status="completed"))
                """Repair pass: failed rows with usable final_decision become completed on read."""
                store_buckets.append(self.store.history(limit=200, status="failed"))
            elif wanted:
                store_buckets.append(self.store.history(limit=200, status=wanted))
            else:
                store_buckets.append(self.store.history(limit=200))
            for raw in [row for bucket in store_buckets for row in bucket]:
                absorb(self._enrich_history_row_dict(self._repair_stored_status(raw)))

        for task in self.registry.list_recent(200, status=wanted or None):
            self._repair_task_status(task)
            absorb(
                self._enrich_history_row_dict(
                    {
                        "task_id": task.task_id,
                        "status": task.status,
                        "request": task.request.model_dump(),
                        "cached": task.cached,
                        "cache_key": self.cache.key_for(task.request),
                        "final_decision": task.final_decision,
                        "decision": task.decision,
                        "error": task.error,
                        "report_sections": task.report_sections,
                        "created_at": task.created_at.isoformat() + "Z",
                        "updated_at": task.updated_at.isoformat() + "Z",
                    }
                )
            )

        if self.store is None and (not wanted or wanted == "completed"):
            for cache_key, data, mtime in self.cache.iter_completed():
                if cache_key in seen_keys:
                    continue
                req_dict = data.get("request") or {}
                try:
                    request = AnalysisRequest(**req_dict)
                except Exception:
                    continue
                iso = (
                    datetime.utcfromtimestamp(mtime).isoformat(timespec="microseconds") + "Z"
                    if mtime
                    else ""
                )
                absorb(
                    self._enrich_history_row_dict(
                        {
                            "task_id": f"cache:{cache_key}",
                            "status": "completed",
                            "request": request.model_dump(),
                            "cached": True,
                            "cache_key": cache_key,
                            "final_decision": str(data.get("final_decision") or ""),
                            "decision": str(data.get("decision") or ""),
                            "error": "",
                            "report_sections": data.get("report_sections") or {},
                            "created_at": iso,
                            "updated_at": iso,
                        }
                    )
                )

        rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        return rows[:capped]

    def _needs_stock_name_resolution(self, request: AnalysisRequest) -> bool:
        sn = (request.stock_name or "").strip()
        if not sn:
            return True
        return sn.upper() == request.ts_code.upper()

    def enrich_request_for_response(self, request: AnalysisRequest) -> AnalysisRequest:
        """Fill ``stock_name`` from Tushare when missing or placeholder (does not affect cache_key)."""

        return self._with_stock_name(request)

    def _enrich_history_row_dict(self, row: dict) -> dict:
        row = dict(row)
        req_dict = dict(row.get("request") or {})
        try:
            request = AnalysisRequest(**req_dict)
        except Exception:
            return row
        enriched = self._with_stock_name(request)
        if self._needs_stock_name_resolution(enriched):
            inferred = self._stock_name_from_report_row(row, request.ts_code)
            if inferred:
                enriched = enriched.model_copy(update={"stock_name": inferred})
        row["request"] = enriched.model_dump()
        return row

    def _with_stock_name(self, request: AnalysisRequest) -> AnalysisRequest:
        if not self._needs_stock_name_resolution(request):
            return request
        try:
            name = resolve_stock_name(request.ts_code)
        except Exception:
            name = ""
        if not name:
            return request
        return request.model_copy(update={"stock_name": name})

    def _stock_name_from_report_row(self, row: dict, ts_code: str) -> str:
        chunks: list[str] = []
        report_sections = row.get("report_sections") or {}
        if isinstance(report_sections, dict):
            chunks.extend(str(value) for value in report_sections.values() if isinstance(value, str))
        for key in ("final_decision", "decision"):
            value = row.get(key)
            if isinstance(value, str):
                chunks.append(value)
        for chunk in chunks:
            name = _extract_stock_name_from_text(chunk, ts_code)
            if name:
                return name
        return ""

    def _task_queue_payload(self, task: AnalysisTask) -> dict:
        return {
            "task_id": task.task_id,
            "status": task.status,
            "request": task.request.model_dump(),
            "origin": task.origin,
            "lane": task.lane,
            "priority": task.priority,
            "queue_position": task.queue_position,
            "stop_requested": task.stop_requested,
            "removed_from_queue": task.removed_from_queue,
            "cached": task.cached,
            "decision": task.decision,
            "error": task.error,
            "created_at": task.created_at.isoformat() + "Z",
            "updated_at": task.updated_at.isoformat() + "Z",
        }

    def _merge_store_active_tasks_into_queue(self, lanes: dict, seen: set[str]) -> None:
        if self.store is None:
            return
        for stored in self.store.history(limit=200):
            stored = self._repair_stored_status(stored)
            task_id = str(stored.get("task_id") or "")
            status = str(stored.get("status") or "")
            if not task_id or task_id in seen or status not in {"queued", "running", "stopping"}:
                continue
            try:
                request = AnalysisRequest(**stored["request"])
            except Exception:
                continue
            if self._needs_stock_name_resolution(request):
                request = self._with_stock_name(request)
            lane = TaskRegistry.lane_for_request(request)
            target = "queued" if status == "queued" else "running"
            lanes.setdefault(
                lane,
                {"capacity": 3 if lane == "flash" else 1, "running": [], "queued": [], "finished": []},
            )[target].append(
                {
                    "task_id": task_id,
                    "status": status,
                    "request": request.model_dump(),
                    "origin": request.origin,
                    "lane": lane,
                    "priority": TaskRegistry.priority_for_request(request),
                    "queue_position": len(lanes[lane][target]) + 1,
                    "stop_requested": status == "stopping",
                    "removed_from_queue": False,
                    "cached": bool(stored.get("cached")),
                    "decision": str(stored.get("decision") or ""),
                    "error": str(stored.get("error") or ""),
                    "created_at": str(stored.get("created_at") or ""),
                    "updated_at": str(stored.get("updated_at") or ""),
                },
            )
            seen.add(task_id)

    def _sync_store(self, task: AnalysisTask) -> None:
        if self.store is None:
            return
        self.store.upsert_task(task, cache_key=self.cache.key_for(task.request))

    def _restore_stored_task(self, stored: dict) -> AnalysisTask | None:
        stored = self._repair_stored_status(stored)
        request = AnalysisRequest(**stored["request"])
        if stored.get("status") == "completed":
            cached = self.cache.get(request)
            if cached is not None:
                task = self.registry.restore(
                    stored["task_id"],
                    request,
                    "completed",
                    report_sections=cached.get("report_sections") or {},
                    final_decision=str(cached.get("final_decision") or ""),
                    decision=str(cached.get("decision") or ""),
                    cached=True,
                )
                self._sync_store(task)
                return task
        report_sections = stored.get("report_sections") or {}
        if not report_sections and stored.get("status") == "completed":
            return None
        return self.registry.restore(
            stored["task_id"],
            request,
            stored.get("status") or "failed",
            report_sections=report_sections,
            final_decision=str(stored.get("final_decision") or ""),
            decision=str(stored.get("decision") or ""),
            error=str(stored.get("error") or ""),
            cached=bool(stored.get("cached")),
        )

    def _repair_task_status(self, task: AnalysisTask) -> None:
        final_decision = self._recovered_final_decision(
            task.final_decision,
            task.report_sections,
        )
        if not self._is_raw_log_failure(task.status, task.error, final_decision):
            return
        task.status = "completed"
        task.final_decision = final_decision
        task.decision = task.decision or parse_rating(final_decision)
        task.error = ""
        self._sync_store(task)

    def _repair_stored_status(self, stored: dict) -> dict:
        final_decision = self._recovered_final_decision(
            str(stored.get("final_decision") or ""),
            stored.get("report_sections") or {},
        )
        if not self._is_raw_log_failure(
            str(stored.get("status") or ""),
            str(stored.get("error") or ""),
            final_decision,
        ):
            return stored
        repaired = dict(stored)
        repaired["status"] = "completed"
        repaired["final_decision"] = final_decision
        repaired["decision"] = repaired.get("decision") or parse_rating(final_decision)
        repaired["error"] = ""
        return repaired

    def _recovered_final_decision(
        self,
        final_decision: str,
        report_sections: dict[str, str],
    ) -> str:
        return final_decision or str(report_sections.get("final_trade_decision") or "")

    def _is_raw_log_failure(self, status: str, error: str, final_decision: str) -> bool:
        return (
            status == "failed"
            and bool(final_decision.strip())
            and RAW_LOG_TICKER_ERROR in error
        )

    def _delete_runtime_report_files(self, request: AnalysisRequest) -> list[Path]:
        if self.runtime_dir is None:
            return []
        log_path = (
            self.runtime_dir
            / "reports"
            / request.ts_code
            / "TradingAgentsStrategy_logs"
            / f"full_states_log_{request.trade_date}.json"
        )
        deleted: list[Path] = []
        try:
            log_path.unlink()
            deleted.append(log_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        self._remove_empty_parents(log_path.parent, self.runtime_dir)
        return deleted

    def _clear_runtime_checkpoint(self, request: AnalysisRequest) -> None:
        if self.runtime_dir is None:
            return
        try:
            clear_checkpoint(self.runtime_dir / "cache", request.ts_code, request.trade_date)
        except OSError:
            pass

    def _remove_empty_parents(self, start: Path, stop: Path) -> None:
        current = start
        stop = stop.resolve()
        while True:
            try:
                if current.resolve() == stop:
                    return
                current.rmdir()
            except OSError:
                return
            current = current.parent

    def build_config(self, request: AnalysisRequest) -> dict:
        config = DEFAULT_CONFIG.copy()
        if self.runtime_dir is not None:
            config["data_cache_dir"] = str(self.runtime_dir / "cache")
            config["results_dir"] = str(self.runtime_dir / "reports")
            config["memory_log_path"] = str(self.runtime_dir / "memory" / "trading_memory.md")
        config["data_vendors"] = {
            "core_stock_apis": "tushare",
            "technical_indicators": "tushare",
            "fundamental_data": "tushare",
            "news_data": "akshare,tavily,tushare",
        }
        config["llm_provider"] = request.llm_provider
        config["quick_think_llm"] = request.quick_model
        config["deep_think_llm"] = request.deep_model
        config["max_debate_rounds"] = request.research_depth
        config["max_risk_discuss_rounds"] = request.research_depth
        config["output_language"] = "Chinese"
        return config

    def _run_trading_graph(
        self,
        request: AnalysisRequest,
        config: dict,
        emit: Callable[[str, dict], None],
    ) -> tuple[dict, str]:
        graph = TradingAgentsGraph(
            selected_analysts=request.analysts,
            debug=False,
            config=config,
        )
        graph.ticker = request.ts_code
        emit(
            "task_progress",
            {
                "stage": "graph_ready",
                "message": "TradingAgentsGraph 已构建，正在启动首个分析师。",
            },
        )
        init_state = graph.propagator.create_initial_state(
            request.ts_code,
            request.trade_date,
            past_context=graph.memory_log.get_past_context(request.ts_code),
        )
        args = graph.propagator.get_graph_args()

        trace = []
        started_agents: set[str] = set()
        completed_sections: set[str] = set()

        for chunk in graph.graph.stream(init_state, **args):
            trace.append(chunk)
            self._emit_chunk_progress(chunk, request.analysts, started_agents, completed_sections, emit)

        if not trace:
            raise RuntimeError("TradingAgents graph returned no streamed state.")

        final_state = trace[-1]
        graph.curr_state = final_state
        graph._log_state(request.trade_date, final_state)
        graph.memory_log.store_decision(
            ticker=request.ts_code,
            trade_date=request.trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )
        decision = graph.process_signal(final_state["final_trade_decision"])
        return final_state, decision

    def _emit_chunk_progress(
        self,
        chunk: dict,
        analysts: list[str],
        started_agents: set[str],
        completed_sections: set[str],
        emit: Callable[[str, dict], None],
    ) -> None:
        analyst_map = {
            "market": ("Market Analyst", "market_report"),
            "fundamentals": ("Fundamentals", "fundamentals_report"),
            "news": ("News Analyst", "news_report"),
            "social": ("Social Analyst", "sentiment_report"),
        }
        for analyst in analysts:
            agent, section = analyst_map.get(analyst, (analyst.title(), ""))
            if agent not in started_agents:
                started_agents.add(agent)
                emit("agent_started", {"agent": agent})
            content = chunk.get(section)
            if content and section not in completed_sections:
                completed_sections.add(section)
                emit(
                    "report_section",
                    {"agent": agent, "section": section, "content": content},
                )
                emit("agent_completed", {"agent": agent, "section": section})

        debate_state = chunk.get("investment_debate_state") or {}
        if debate_state.get("judge_decision") and "investment_plan" not in completed_sections:
            completed_sections.add("investment_plan")
            emit("agent_started", {"agent": "Research Debate"})
            emit(
                "report_section",
                {
                    "agent": "Research Debate",
                    "section": "investment_plan",
                    "content": debate_state["judge_decision"],
                },
            )
            emit("agent_completed", {"agent": "Research Debate", "section": "investment_plan"})

        if chunk.get("trader_investment_plan") and "trader_investment_plan" not in completed_sections:
            completed_sections.add("trader_investment_plan")
            emit("agent_started", {"agent": "Trader"})
            emit(
                "report_section",
                {
                    "agent": "Trader",
                    "section": "trader_investment_plan",
                    "content": chunk["trader_investment_plan"],
                },
            )
            emit("agent_completed", {"agent": "Trader", "section": "trader_investment_plan"})

        risk_state = chunk.get("risk_debate_state") or {}
        if risk_state.get("judge_decision") and "final_trade_decision" not in completed_sections:
            completed_sections.add("final_trade_decision")
            emit("agent_started", {"agent": "Portfolio Manager"})
            emit(
                "report_section",
                {
                    "agent": "Portfolio Manager",
                    "section": "final_trade_decision",
                    "content": risk_state["judge_decision"],
                },
            )
            emit("agent_completed", {"agent": "Portfolio Manager", "section": "final_trade_decision"})
