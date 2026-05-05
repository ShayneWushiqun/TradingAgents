from __future__ import annotations

from datetime import datetime, time, timedelta
import threading
from zoneinfo import ZoneInfo

from tradingagents.web.hot_radar_service import HotRadarService


class HotRadarScheduler:
    def __init__(
        self,
        service: HotRadarService,
        *,
        run_at: str = "17:00",
        top_n: int = 20,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.service = service
        self.run_at = run_at
        self.top_n = top_n
        self.timezone = ZoneInfo(timezone)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(self.timezone)
            next_run = self._next_run(now)
            wait_seconds = max(1.0, (next_run - now).total_seconds())
            if self._stop.wait(wait_seconds):
                return
            try:
                self._run_scheduled_once(next_run.strftime("%Y-%m-%d"))
            except Exception:
                continue

    def _run_scheduled_once(self, end_date: str) -> None:
        trade_dates = self.service.trade_dates(end_date, limit=1)
        if not trade_dates:
            return
        # Scheduled work may refresh the leaderboard snapshot, but must never
        # enqueue Agent analysis tasks. Row-level analysis stays user initiated.
        trade_date = trade_dates[0]
        self.service.fetch_snapshot(
            trade_date,
            "daily",
            top_n=self.top_n,
            force_refresh=True,
        )

    def _next_run(self, now: datetime) -> datetime:
        today = now.date()
        hour, minute = self.run_at.split(":")
        candidate = datetime.combine(
            today,
            time(int(hour), int(minute)),
            tzinfo=self.timezone,
        )
        if candidate > now:
            return candidate
        tomorrow = today + timedelta(days=1)
        return datetime.combine(tomorrow, time(int(hour), int(minute)), tzinfo=self.timezone)
