from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy import Boolean, String, Table, Text, create_engine, delete, inspect, insert, select, text
from sqlalchemy import MetaData, Column
from sqlalchemy.engine import Engine

from .tasks import AnalysisTask


class AnalysisStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.metadata = MetaData()
        self.tasks = Table(
            "analysis_tasks",
            self.metadata,
            Column("task_id", String(64), primary_key=True),
            Column("ts_code", String(16), nullable=False),
            Column("trade_date", String(10), nullable=False),
            Column("request_json", Text, nullable=False),
            Column("status", String(24), nullable=False),
            Column("cached", Boolean, nullable=False, default=False),
            Column("cache_key", String(80), nullable=True),
            Column("report_sections_json", Text, nullable=False, default="{}"),
            Column("final_decision", Text, nullable=False, default=""),
            Column("decision", Text, nullable=False, default=""),
            Column("error", Text, nullable=False, default=""),
            Column("created_at", String(32), nullable=False),
            Column("updated_at", String(32), nullable=False),
        )
        self.metadata.create_all(self.engine)
        self._ensure_columns()

    def upsert_task(self, task: AnalysisTask, cache_key: str | None = None) -> None:
        payload = self._row_from_task(task, cache_key=cache_key)
        with self.engine.begin() as connection:
            connection.execute(delete(self.tasks).where(self.tasks.c.task_id == task.task_id))
            connection.execute(insert(self.tasks).values(**payload))

    def latest_task(self) -> dict[str, Any] | None:
        rows = self.history(limit=100)
        running = [row for row in rows if row["status"] in {"queued", "running"}]
        return running[0] if running else (rows[0] if rows else None)

    def latest_completed(self) -> dict[str, Any] | None:
        statement = (
            select(self.tasks)
            .where(self.tasks.c.status == "completed")
            .order_by(self.tasks.c.updated_at.desc())
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return self._decode_row(row) if row is not None else None

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        statement = select(self.tasks).where(self.tasks.c.task_id == task_id).limit(1)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return self._decode_row(row) if row is not None else None

    def delete_task(self, task_id: str) -> bool:
        statement = delete(self.tasks).where(self.tasks.c.task_id == task_id)
        with self.engine.begin() as connection:
            result = connection.execute(statement)
        return bool(result.rowcount)

    def history(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        cap = max(1, min(int(limit), 200))
        statement = select(self.tasks)
        st = str(status or "").strip()
        if st:
            statement = statement.where(self.tasks.c.status == st)
        statement = statement.order_by(self.tasks.c.updated_at.desc()).limit(cap)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._decode_row(row) for row in rows]

    def _row_from_task(self, task: AnalysisTask, cache_key: str | None) -> dict[str, Any]:
        return {
            "task_id": task.task_id,
            "ts_code": task.request.ts_code,
            "trade_date": task.request.trade_date,
            "request_json": json.dumps(
                task.request.model_dump(exclude={"force_refresh"}),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "status": task.status,
            "cached": task.cached,
            "cache_key": cache_key,
            "report_sections_json": json.dumps(
                task.report_sections,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "final_decision": task.final_decision,
            "decision": task.decision,
            "error": task.error,
            "created_at": self._iso(task.created_at),
            "updated_at": self._iso(task.updated_at),
        }

    def _decode_row(self, row: Any) -> dict[str, Any]:
        data = dict(row)
        data["request"] = json.loads(data.pop("request_json"))
        data["report_sections"] = json.loads(data.pop("report_sections_json", "{}") or "{}")
        data["cached"] = bool(data["cached"])
        return data

    def _iso(self, value: datetime) -> str:
        return value.isoformat(timespec="microseconds") + "Z"

    def _ensure_columns(self) -> None:
        existing = {column["name"] for column in inspect(self.engine).get_columns("analysis_tasks")}
        if "report_sections_json" in existing:
            return
        with self.engine.begin() as connection:
            connection.execute(text("ALTER TABLE analysis_tasks ADD COLUMN report_sections_json TEXT"))
            connection.execute(
                text("UPDATE analysis_tasks SET report_sections_json = '{}' WHERE report_sections_json = ''")
            )
