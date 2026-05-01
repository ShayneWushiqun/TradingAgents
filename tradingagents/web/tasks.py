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
