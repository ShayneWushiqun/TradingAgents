from collections.abc import Callable
from pathlib import Path
import threading

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.checkpointer import clear_checkpoint
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .analysis_cache import AnalysisCache
from .analysis_store import AnalysisStore
from .schemas import AnalysisRequest
from .tasks import AnalysisTask, TaskRegistry, extract_report_sections


AnalysisRunner = Callable[[AnalysisRequest, dict, Callable[[str, dict], None]], tuple[dict, str]]
RAW_LOG_TICKER_ERROR = "unsupported operand type(s) for /: 'PosixPath' and 'NoneType'"


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

    def create_task(self, request: AnalysisRequest) -> AnalysisTask:
        task = self.registry.create(request)
        self._sync_store(task)
        if not request.force_refresh:
            cached = self.cache.get(request)
            if cached is not None:
                self.registry.complete_from_cache(task.task_id, cached)
                self._sync_store(task)
                return task
        if self.run_inline:
            self._run_task(task)
        else:
            thread = threading.Thread(target=self._run_task, args=(task,), daemon=True)
            thread.start()
        return task

    def restore_cached_task(self, request: AnalysisRequest) -> AnalysisTask | None:
        cached = self.cache.get(request)
        if cached is None:
            return None
        task = self.registry.create(request)
        self.registry.complete_from_cache(task.task_id, cached)
        self._sync_store(task)
        return task

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
        cached = self.cache.latest()
        if cached is None:
            return None
        request = AnalysisRequest(**cached["request"])
        task = self.registry.create(request)
        self.registry.complete_from_cache(task.task_id, cached)
        self._sync_store(task)
        return task

    def get_task(self, task_id: str) -> AnalysisTask | None:
        task = self.registry.get(task_id)
        if task is not None:
            self._repair_task_status(task)
            return task
        if self.store is None:
            return None
        stored = self.store.get_task(task_id)
        if stored is None:
            return None
        return self._restore_stored_task(stored)

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

    def _run_task(self, task: AnalysisTask) -> None:
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
            self.registry.fail(task.task_id, str(exc))
            self._sync_store(task)
            return

        report_sections = {**task.report_sections, **extract_report_sections(final_state)}
        self.cache.set(task.request, final_state, decision, report_sections)
        self.registry.complete(task.task_id, final_state, decision)
        self._sync_store(task)

    def history(self, limit: int = 50) -> list[dict]:
        capped = max(1, min(int(limit), 200))
        if self.store is not None:
            return [self._repair_stored_status(row) for row in self.store.history(limit=capped)]
        task = self.registry.latest()
        if task is None:
            return []
        self._repair_task_status(task)
        return [
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
        ]

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
