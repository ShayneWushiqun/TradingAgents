from dataclasses import dataclass, field
from datetime import datetime
import threading
from uuid import uuid4

from .schemas import AnalysisRequest


def extract_report_sections(final_state: dict) -> dict[str, str]:
    report_sections = {
        key: value
        for key, value in final_state.items()
        if key.endswith("_report") and isinstance(value, str) and value.strip()
    }
    if final_state.get("investment_plan"):
        report_sections["investment_plan"] = final_state["investment_plan"]
    if final_state.get("trader_investment_plan"):
        report_sections["trader_investment_plan"] = final_state[
            "trader_investment_plan"
        ]
    return report_sections


@dataclass
class AnalysisTask:
    task_id: str
    request: AnalysisRequest
    status: str = "queued"
    events: list[dict] = field(default_factory=list)
    report_sections: dict[str, str] = field(default_factory=dict)
    final_decision: str = ""
    decision: str = ""
    error: str = ""
    cached: bool = False
    origin: str = "analyze"
    lane: str = "pro"
    priority: int = 100
    queue_position: int = 0
    stop_requested: bool = False
    removed_from_queue: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, AnalysisTask] = {}
        self._condition = threading.Condition()
        self._sequence = 0

    def _next_position(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def lane_for_request(request: AnalysisRequest) -> str:
        return "flash" if request.quick_model == "deepseek-v4-flash" or request.deep_model == "deepseek-v4-flash" else "pro"

    @staticmethod
    def priority_for_request(request: AnalysisRequest) -> int:
        return 100 if request.origin == "analyze" else 50

    def create(self, request: AnalysisRequest) -> AnalysisTask:
        with self._condition:
            task = AnalysisTask(
                task_id=uuid4().hex,
                request=request,
                origin=request.origin,
                lane=self.lane_for_request(request),
                priority=self.priority_for_request(request),
                queue_position=self._next_position(),
            )
            self._tasks[task.task_id] = task
            return task

    def restore(
        self,
        task_id: str,
        request: AnalysisRequest,
        status: str,
        report_sections: dict[str, str] | None = None,
        final_decision: str = "",
        decision: str = "",
        error: str = "",
        cached: bool = False,
    ) -> AnalysisTask:
        with self._condition:
            task = AnalysisTask(
                task_id=task_id,
                request=request,
                status=status,
                report_sections=report_sections or {},
                final_decision=final_decision,
                decision=decision,
                error=error,
                cached=cached,
                origin=request.origin,
                lane=self.lane_for_request(request),
                priority=self.priority_for_request(request),
                queue_position=self._next_position(),
            )
            self._tasks[task.task_id] = task
            return task

    def get(self, task_id: str) -> AnalysisTask | None:
        with self._condition:
            return self._tasks.get(task_id)

    def delete(self, task_id: str) -> AnalysisTask | None:
        with self._condition:
            return self._tasks.pop(task_id, None)

    def latest(self) -> AnalysisTask | None:
        with self._condition:
            running = [
                task
                for task in self._tasks.values()
                if task.status in {"queued", "running"}
            ]
            if running:
                return max(running, key=lambda task: task.updated_at)
            if not self._tasks:
                return None
            return max(self._tasks.values(), key=lambda task: task.updated_at)

    def list_recent(self, limit: int = 50, status: str | None = None) -> list[AnalysisTask]:
        """In-memory tasks, newest ``updated_at`` first. Optional ``status`` filters before truncating."""
        cap = max(1, min(int(limit), 200))
        want = str(status or "").strip()
        with self._condition:
            ordered = sorted(
                self._tasks.values(),
                key=lambda task: task.updated_at,
                reverse=True,
            )
            if want:
                ordered = [t for t in ordered if str(t.status) == want]
            return ordered[:cap]

    def queued_for_lane(self, lane: str) -> list[AnalysisTask]:
        with self._condition:
            return sorted(
                [
                    task
                    for task in self._tasks.values()
                    if task.lane == lane and task.status == "queued" and not task.removed_from_queue
                ],
                key=lambda task: (-task.priority, task.queue_position, task.created_at),
            )

    def running_for_lane(self, lane: str) -> list[AnalysisTask]:
        with self._condition:
            return sorted(
                [
                    task
                    for task in self._tasks.values()
                    if task.lane == lane and task.status == "running" and not task.removed_from_queue
                ],
                key=lambda task: task.updated_at,
            )

    def queue_visible_for_lane(self, lane: str, statuses: set[str]) -> list[AnalysisTask]:
        with self._condition:
            return sorted(
                [
                    task
                    for task in self._tasks.values()
                    if task.lane == lane and task.status in statuses and not task.removed_from_queue
                ],
                key=lambda task: (-task.priority, task.queue_position, task.created_at),
            )

    def mark_removed_from_queue(self, task_id: str) -> AnalysisTask | None:
        with self._condition:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.removed_from_queue = True
            task.updated_at = datetime.utcnow()
            self._condition.notify_all()
            return task

    def mark_stopped(self, task_id: str) -> AnalysisTask | None:
        with self._condition:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = "stopped"
            task.stop_requested = True
            task.updated_at = datetime.utcnow()
            self._condition.notify_all()
            return task

    def add_event(self, task_id: str, event: str, data: dict | None = None) -> dict:
        with self._condition:
            task = self._tasks[task_id]
            task.updated_at = datetime.utcnow()
            entry = {
                "id": len(task.events) + 1,
                "event": event,
                "data": data or {},
                "created_at": task.updated_at.isoformat() + "Z",
            }
            task.events.append(entry)
            self._condition.notify_all()
            return entry

    def start(self, task_id: str) -> None:
        with self._condition:
            task = self._tasks[task_id]
            task.status = "running"
            task.updated_at = datetime.utcnow()
        self.add_event(task_id, "task_started", {"status": "running"})

    def complete(self, task_id: str, final_state: dict, decision: str) -> None:
        report_sections = extract_report_sections(final_state)

        with self._condition:
            task = self._tasks[task_id]
            task.status = "completed"
            task.report_sections.update(report_sections)
            task.final_decision = str(final_state.get("final_trade_decision", ""))
            task.decision = decision
            task.updated_at = datetime.utcnow()

        self.add_event(
            task_id,
            "task_completed",
            {
                "status": "completed",
                "decision": decision,
                "final_decision": str(final_state.get("final_trade_decision", "")),
                "report_sections": report_sections,
            },
        )

    def complete_from_cache(self, task_id: str, cached: dict) -> None:
        report_sections = cached.get("report_sections") or {}
        final_decision = str(cached.get("final_decision") or "")
        decision = str(cached.get("decision") or "")

        with self._condition:
            task = self._tasks[task_id]
            task.status = "completed"
            task.cached = True
            task.report_sections.update(report_sections)
            task.final_decision = final_decision
            task.decision = decision
            task.updated_at = datetime.utcnow()

        self.add_event(
            task_id,
            "cache_hit",
            {
                "status": "completed",
                "message": "命中历史分析缓存，已直接载入报告。",
            },
        )
        self.add_event(
            task_id,
            "task_completed",
            {
                "status": "completed",
                "decision": decision,
                "final_decision": final_decision,
                "report_sections": report_sections,
                "cached": True,
            },
        )

    def fail(self, task_id: str, error: str) -> None:
        with self._condition:
            task = self._tasks[task_id]
            task.status = "failed"
            task.error = error
            task.updated_at = datetime.utcnow()
        self.add_event(task_id, "task_failed", {"status": "failed", "error": error})

    def events_since(self, task_id: str, last_event_id: int) -> list[dict]:
        with self._condition:
            task = self._tasks[task_id]
            return [event for event in task.events if event["id"] > last_event_id]

    def wait_for_events(self, task_id: str, last_event_id: int, timeout: float) -> list[dict]:
        with self._condition:
            self._condition.wait_for(
                lambda: any(
                    event["id"] > last_event_id
                    for event in self._tasks[task_id].events
                ),
                timeout=timeout,
            )
            return [
                event
                for event in self._tasks[task_id].events
                if event["id"] > last_event_id
            ]
