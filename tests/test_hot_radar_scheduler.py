from tradingagents.web.hot_radar_scheduler import HotRadarScheduler


def test_scheduled_run_fetches_snapshot_without_creating_analysis_tasks():
    class Service:
        def __init__(self):
            self.fetch_calls = []

        def trade_dates(self, end_date, limit):
            return ["2026-04-30"]

        def fetch_snapshot(self, trade_date, batch_time, top_n, force_refresh=False):
            self.fetch_calls.append((trade_date, batch_time, top_n, force_refresh))
            return {"run": {"status": "hot_only"}}

        def run_batch(self, *args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("scheduled Hot Radar must not create analysis tasks")

    service = Service()
    scheduler = HotRadarScheduler(service, top_n=20)

    scheduler._run_scheduled_once("2026-05-04")

    assert service.fetch_calls == [("2026-04-30", "daily", 20, True)]
