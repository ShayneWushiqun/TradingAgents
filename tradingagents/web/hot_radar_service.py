from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, delete, insert, select, update
from sqlalchemy.engine import Engine

from tradingagents.dataflows.tushare_hot import (
    get_recent_trade_dates,
    get_ths_hot_snapshot,
)
from tradingagents.web.analysis_service import AnalysisService
from tradingagents.web.schemas import AnalysisRequest


HotSnapshotGetter = Callable[[str, int], dict[str, Any]]
TradeDatesGetter = Callable[[str | None, int], list[str]]


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="microseconds") + "Z"


class HotRadarStore:
    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.metadata = MetaData()
        self.runs = Table(
            "hot_radar_runs",
            self.metadata,
            Column("run_id", String(64), primary_key=True),
            Column("trade_date", String(10), nullable=False),
            Column("batch_time", String(5), nullable=False),
            Column("top_n", String(8), nullable=False),
            Column("status", String(24), nullable=False),
            Column("error", Text, nullable=False, default=""),
            Column("created_at", String(32), nullable=False),
            Column("updated_at", String(32), nullable=False),
        )
        self.items = Table(
            "hot_radar_items",
            self.metadata,
            Column("item_id", String(64), primary_key=True),
            Column("run_id", String(64), nullable=False),
            Column("market", String(24), nullable=False),
            Column("ts_code", String(16), nullable=False),
            Column("ts_name", String(80), nullable=False),
            Column("rank_value", String(16), nullable=False),
            Column("payload_json", Text, nullable=False),
        )
        self.analysis_tasks = Table(
            "hot_radar_analysis_tasks",
            self.metadata,
            Column("link_id", String(64), primary_key=True),
            Column("run_id", String(64), nullable=False),
            Column("ts_code", String(16), nullable=False),
            Column("rank_value", String(16), nullable=False),
            Column("analysis_task_id", String(64), nullable=False),
            Column("status", String(24), nullable=False),
            Column("decision", String(32), nullable=False),
            Column("verdict", String(24), nullable=False),
            Column("created_at", String(32), nullable=False),
        )
        self.metadata.create_all(self.engine)

    def save_run(
        self,
        *,
        run_id: str,
        trade_date: str,
        batch_time: str,
        top_n: int,
        status: str,
        items: dict[str, list[dict[str, Any]]],
        analysis_tasks: list[dict[str, Any]],
        error: str = "",
    ) -> None:
        now = _utc_now()
        with self.engine.begin() as connection:
            existing = self.find_run(trade_date, batch_time)
            if existing is not None:
                run_id = existing["run_id"]
                connection.execute(delete(self.items).where(self.items.c.run_id == run_id))
                connection.execute(delete(self.analysis_tasks).where(self.analysis_tasks.c.run_id == run_id))
                connection.execute(delete(self.runs).where(self.runs.c.run_id == run_id))
            connection.execute(
                insert(self.runs).values(
                    run_id=run_id,
                    trade_date=trade_date,
                    batch_time=batch_time,
                    top_n=str(top_n),
                    status=status,
                    error=error,
                    created_at=now,
                    updated_at=now,
                )
            )
            for market, rows in items.items():
                for row in rows:
                    connection.execute(
                        insert(self.items).values(
                            item_id=uuid4().hex,
                            run_id=run_id,
                            market=market,
                            ts_code=str(row.get("ts_code") or ""),
                            ts_name=str(row.get("ts_name") or ""),
                            rank_value=str(row.get("rank") or ""),
                            payload_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
                        )
                    )
            for row in analysis_tasks:
                connection.execute(
                    insert(self.analysis_tasks).values(
                        link_id=uuid4().hex,
                        run_id=run_id,
                        ts_code=str(row.get("ts_code") or ""),
                        rank_value=str(row.get("rank") or ""),
                        analysis_task_id=str(row.get("analysis_task_id") or ""),
                        status=str(row.get("status") or ""),
                        decision=str(row.get("decision") or ""),
                        verdict=str(row.get("verdict") or ""),
                        created_at=now,
                    )
                )

    def find_run(self, trade_date: str, batch_time: str) -> dict[str, Any] | None:
        statement = (
            select(self.runs)
            .where(self.runs.c.trade_date == trade_date)
            .where(self.runs.c.batch_time == batch_time)
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    def load_dashboard(self, trade_date: str, batch_time: str) -> dict[str, Any] | None:
        run = self.find_run(trade_date, batch_time)
        if run is None:
            return None
        with self.engine.connect() as connection:
            item_rows = connection.execute(
                select(self.items).where(self.items.c.run_id == run["run_id"])
            ).mappings().all()
            task_rows = connection.execute(
                select(self.analysis_tasks).where(self.analysis_tasks.c.run_id == run["run_id"])
            ).mappings().all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in item_rows:
            item = json.loads(row["payload_json"])
            grouped.setdefault(str(row["market"]), []).append(item)
        for rows in grouped.values():
            rows.sort(key=lambda item: item.get("rank") or 999999)
        tasks = [dict(row) for row in task_rows]
        tasks.sort(key=lambda row: int(row.get("rank_value") or 999999))
        return {"run": self._decode_run(run), "items": grouped, "analysis_tasks": tasks}

    def _decode_run(self, row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        decoded["top_n"] = int(decoded.get("top_n") or 0)
        return decoded

    def replace_snapshot_items_only(self, run_id: str, items: dict[str, list[dict[str, Any]]]) -> None:
        """Overwrite ths_hot items for an existing batch run; preserves analysis_tasks and run status."""

        now = _utc_now()
        with self.engine.begin() as connection:
            connection.execute(delete(self.items).where(self.items.c.run_id == run_id))
            for market, rows in items.items():
                for row in rows:
                    connection.execute(
                        insert(self.items).values(
                            item_id=uuid4().hex,
                            run_id=run_id,
                            market=market,
                            ts_code=str(row.get("ts_code") or ""),
                            ts_name=str(row.get("ts_name") or ""),
                            rank_value=str(row.get("rank") or ""),
                            payload_json=json.dumps(row, ensure_ascii=False, sort_keys=True),
                        )
                    )
            connection.execute(update(self.runs).where(self.runs.c.run_id == run_id).values(updated_at=now))


class HotRadarService:
    def __init__(
        self,
        *,
        analysis_service: AnalysisService,
        database_url: str,
        hot_snapshot_getter: HotSnapshotGetter | None = None,
        trade_dates_getter: TradeDatesGetter | None = None,
    ) -> None:
        self.analysis_service = analysis_service
        self.store = HotRadarStore(database_url)
        self.hot_snapshot_getter = hot_snapshot_getter or get_ths_hot_snapshot
        self.trade_dates_getter = trade_dates_getter or get_recent_trade_dates

    @classmethod
    def from_runtime(
        cls,
        *,
        analysis_service: AnalysisService,
        database_url: str | None,
        runtime_dir: str | Path,
        hot_snapshot_getter: HotSnapshotGetter | None = None,
        trade_dates_getter: TradeDatesGetter | None = None,
    ) -> "HotRadarService":
        url = database_url or f"sqlite:///{Path(runtime_dir) / 'hot-radar.sqlite3'}"
        return cls(
            analysis_service=analysis_service,
            database_url=url,
            hot_snapshot_getter=hot_snapshot_getter,
            trade_dates_getter=trade_dates_getter,
        )

    def trade_dates(self, end_date: str | None = None, limit: int = 30) -> list[str]:
        return self.trade_dates_getter(end_date, limit)

    def get_dashboard(
        self,
        trade_date: str,
        batch_time: str,
        top_n: int = 20,
        fetch_if_missing: bool = False,
    ) -> dict[str, Any]:
        """Load persisted dashboard. When ``fetch_if_missing`` and nothing is saved yet, pull ths_hot once."""

        saved = self.store.load_dashboard(trade_date, batch_time)
        if saved is not None:
            return saved
        if fetch_if_missing:
            snapshot = self.hot_snapshot_getter(trade_date, top_n)
            run_id = uuid4().hex
            self.store.save_run(
                run_id=run_id,
                trade_date=trade_date,
                batch_time=batch_time,
                top_n=top_n,
                status="hot_only",
                items=snapshot.get("markets") or {},
                analysis_tasks=[],
            )
            return self.store.load_dashboard(trade_date, batch_time) or {
                "run": {"run_id": run_id, "trade_date": trade_date, "batch_time": batch_time, "status": "hot_only"},
                "items": snapshot.get("markets") or {},
                "analysis_tasks": [],
            }
        return {
            "run": {
                "run_id": "",
                "trade_date": trade_date,
                "batch_time": batch_time,
                "top_n": top_n,
                "status": "missing",
                "error": "",
            },
            "items": {"热股": [], "ETF": [], "行业板块": [], "概念板块": []},
            "analysis_tasks": [],
        }

    def sync_hot_snapshot_from_source(
        self,
        trade_date: str,
        batch_time: str,
        top_n: int = 20,
        *,
        force_refresh: bool = True,
    ) -> dict[str, Any]:
        """Pull latest ths_hot and persist.

        ``force_refresh`` (default True): overwrite snapshot when forced from UI.
        When False and a row already exists for (trade_date, batch_time), returns the stored dashboard
        without calling Tushare (used for tolerant clients).

        Completed / partial_failed runs only replace hot_radar_items so analysis_tasks stay intact.

        Raises:
            Same as underlying ``hot_snapshot_getter`` on network/data errors.

        """

        saved = self.store.load_dashboard(trade_date, batch_time)
        if not force_refresh and saved is not None:
            return saved

        snapshot = self.hot_snapshot_getter(trade_date, top_n)
        items = snapshot.get("markets") or {}

        if saved is None:
            run_id = uuid4().hex
            self.store.save_run(
                run_id=run_id,
                trade_date=trade_date,
                batch_time=batch_time,
                top_n=top_n,
                status="hot_only",
                items=items,
                analysis_tasks=[],
            )
            return self.store.load_dashboard(trade_date, batch_time) or {
                "run": {"run_id": run_id, "trade_date": trade_date, "batch_time": batch_time, "status": "hot_only"},
                "items": items,
                "analysis_tasks": [],
            }

        run = saved.get("run") or {}
        run_id = str(run.get("run_id") or "")
        tasks = saved.get("analysis_tasks") or []
        status = run.get("status") or ""

        if not run_id:
            rid = uuid4().hex
            self.store.save_run(
                run_id=rid,
                trade_date=trade_date,
                batch_time=batch_time,
                top_n=top_n,
                status="hot_only",
                items=items,
                analysis_tasks=[],
            )
            return self.store.load_dashboard(trade_date, batch_time) or {
                "run": {"run_id": rid, "trade_date": trade_date, "batch_time": batch_time, "status": "hot_only"},
                "items": items,
                "analysis_tasks": [],
            }

        if status in {"completed", "partial_failed"} or len(tasks) > 0:
            self.store.replace_snapshot_items_only(run_id, items)
            loaded = self.store.load_dashboard(trade_date, batch_time)
            return loaded or saved

        self.store.save_run(
            run_id=run_id,
            trade_date=trade_date,
            batch_time=batch_time,
            top_n=top_n,
            status="hot_only",
            items=items,
            analysis_tasks=[],
        )
        return self.store.load_dashboard(trade_date, batch_time) or {
            "run": {"run_id": run_id, "trade_date": trade_date, "batch_time": batch_time, "status": "hot_only"},
            "items": items,
            "analysis_tasks": [],
        }

    def run_batch(self, trade_date: str, batch_time: str, top_n: int = 20) -> dict[str, Any]:
        if batch_time != "daily":
            raise ValueError("batch_time must be daily")
        snapshot = self.hot_snapshot_getter(trade_date, top_n)
        items = snapshot.get("markets") or {}
        run_id = uuid4().hex
        links: list[dict[str, Any]] = []
        status = "completed"
        error = ""
        for item in items.get("热股", [])[:top_n]:
            ts_code = str(item.get("ts_code") or "")
            if not ts_code.endswith((".SH", ".SZ", ".BJ")):
                continue
            request = AnalysisRequest(
                ts_code=ts_code,
                trade_date=trade_date,
                analysts=["market", "fundamentals", "news"],
                research_depth=1,
                llm_provider="deepseek",
                quick_model="deepseek-v4-flash",
                deep_model="deepseek-v4-flash",
                force_refresh=True,
            )
            task = self.analysis_service.create_task(request)
            decision = task.decision or ""
            links.append(
                {
                    "ts_code": ts_code,
                    "rank": item.get("rank") or "",
                    "analysis_task_id": task.task_id,
                    "status": task.status,
                    "decision": decision,
                    "verdict": self._verdict(decision),
                }
            )
            if task.status == "failed":
                status = "partial_failed"
                error = task.error
        self.store.save_run(
            run_id=run_id,
            trade_date=trade_date,
            batch_time=batch_time,
            top_n=top_n,
            status=status,
            items=items,
            analysis_tasks=links,
            error=error,
        )
        return self.store.load_dashboard(trade_date, batch_time) or {
            "run": {"run_id": run_id, "trade_date": trade_date, "batch_time": batch_time, "status": status},
            "items": items,
            "analysis_tasks": links,
        }

    def _verdict(self, decision: str) -> str:
        normalized = decision.lower()
        if "buy" in normalized or "overweight" in normalized:
            return "强关注"
        if "sell" in normalized or "underweight" in normalized:
            return "放弃"
        return "观察"
