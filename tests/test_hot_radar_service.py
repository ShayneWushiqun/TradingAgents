import pytest

from tradingagents.web.hot_radar_service import HotRadarService
from tradingagents.web.tasks import TaskRegistry
from tradingagents.web.analysis_service import AnalysisService


def _snapshot():
    return {
        "trade_date": "2026-04-30",
        "top_n": 2,
        "markets": {
            "热股": [
                {
                    "trade_date": "2026-04-30",
                    "market": "热股",
                    "ts_code": "000988.SZ",
                    "ts_name": "华工科技",
                    "rank": 1,
                    "pct_change": 7.42,
                    "current_price": 119.53,
                    "concept": "CPO;光模块",
                    "rank_reason": "10点新进",
                    "hot": 96.8,
                    "rank_time": "10:03:18",
                },
                {
                    "trade_date": "2026-04-30",
                    "market": "热股",
                    "ts_code": "603629.SH",
                    "ts_name": "利通电子",
                    "rank": 2,
                    "pct_change": 9.99,
                    "current_price": 144.41,
                    "concept": "消费电子;AI终端",
                    "rank_reason": "排名上升",
                    "hot": 94.2,
                    "rank_time": "10:03:18",
                },
            ],
            "ETF": [],
            "行业板块": [],
            "概念板块": [],
        },
    }


def test_hot_radar_run_creates_lightweight_analysis_tasks(tmp_path):
    seen_requests = []

    def fake_runner(request, config, emit):
        seen_requests.append(request)
        return (
            {
                "market_report": f"{request.ts_code} 热榜初筛",
                "final_trade_decision": "Rating: Hold\n热榜轻量观察。",
            },
            "Hold",
        )

    analysis_service = AnalysisService(
        TaskRegistry(),
        runner=fake_runner,
        run_inline=True,
        runtime_dir=tmp_path,
    )
    service = HotRadarService(
        analysis_service=analysis_service,
        database_url=f"sqlite:///{tmp_path / 'hot-radar.sqlite3'}",
        hot_snapshot_getter=lambda trade_date, top_n: _snapshot(),
        trade_dates_getter=lambda end_date, limit: ["2026-04-30", "2026-04-29"],
    )

    payload = service.run_batch("2026-04-30", "daily", top_n=2)

    assert payload["run"]["trade_date"] == "2026-04-30"
    assert payload["run"]["batch_time"] == "daily"
    assert payload["run"]["status"] == "completed"
    assert len(payload["items"]["热股"]) == 2
    assert len(payload["analysis_tasks"]) == 2
    assert seen_requests[0].ts_code == "000988.SZ"
    assert seen_requests[0].quick_model == "deepseek-v4-flash"
    assert seen_requests[0].deep_model == "deepseek-v4-flash"
    assert seen_requests[0].force_refresh is True
    assert seen_requests[0].research_depth == 1


def test_hot_radar_history_returns_saved_batch_without_rerun(tmp_path):
    calls = {"snapshot": 0}

    def snapshot_getter(trade_date, top_n):
        calls["snapshot"] += 1
        return _snapshot()

    analysis_service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        runtime_dir=tmp_path,
    )
    service = HotRadarService(
        analysis_service=analysis_service,
        database_url=f"sqlite:///{tmp_path / 'hot-radar.sqlite3'}",
        hot_snapshot_getter=snapshot_getter,
        trade_dates_getter=lambda end_date, limit: ["2026-04-30"],
    )
    service.run_batch("2026-04-30", "daily", top_n=2)

    payload = service.get_dashboard("2026-04-30", "daily", top_n=2)

    assert calls["snapshot"] == 1
    assert payload["run"]["trade_date"] == "2026-04-30"
    assert payload["items"]["热股"][0]["ts_code"] == "000988.SZ"
    assert payload["analysis_tasks"][0]["status"] == "completed"


def test_hot_radar_does_not_repull_hot_only_on_repeat_get_but_force_sync_updates(tmp_path):
    snapshots = [
        {
            **_snapshot(),
            "markets": {
                **_snapshot()["markets"],
                "热股": [
                    {
                        **_snapshot()["markets"]["热股"][0],
                        "ts_code": "600186.SH",
                        "ts_name": "旧切片",
                    }
                ],
            },
        },
        _snapshot(),
    ]

    def snapshot_getter(trade_date, top_n):
        return snapshots.pop(0)

    analysis_service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        runtime_dir=tmp_path,
    )
    service = HotRadarService(
        analysis_service=analysis_service,
        database_url=f"sqlite:///{tmp_path / 'hot-radar.sqlite3'}",
        hot_snapshot_getter=snapshot_getter,
        trade_dates_getter=lambda end_date, limit: ["2026-04-30"],
    )

    first = service.get_dashboard("2026-04-30", "daily", top_n=2, fetch_if_missing=True)
    cached = service.get_dashboard("2026-04-30", "daily", top_n=2, fetch_if_missing=True)

    assert first["run"]["status"] == "hot_only"
    assert first["items"]["热股"][0]["ts_code"] == "600186.SH"
    assert cached["run"]["status"] == "hot_only"
    assert cached["items"]["热股"][0]["ts_code"] == "600186.SH"

    forced = service.sync_hot_snapshot_from_source("2026-04-30", "daily", top_n=2, force_refresh=True)
    assert forced["run"]["status"] == "hot_only"
    assert forced["items"]["热股"][0]["ts_code"] == "000988.SZ"


def test_hot_radar_completed_items_refresh_on_force_sync(tmp_path):
    calls = {"n": 0}

    def snapshot_getter(trade_date, top_n):
        calls["n"] += 1
        base = _snapshot()
        row0 = dict(base["markets"]["热股"][0])
        if calls["n"] >= 2:
            row0["ts_name"] = "强制刷新后改名"
        return {
            **base,
            "markets": {**base["markets"], "热股": [row0, base["markets"]["热股"][1]]},
        }

    analysis_service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        runtime_dir=tmp_path,
    )
    service = HotRadarService(
        analysis_service=analysis_service,
        database_url=f"sqlite:///{tmp_path / 'hot-radar.sqlite3'}",
        hot_snapshot_getter=snapshot_getter,
        trade_dates_getter=lambda end_date, limit: ["2026-04-30"],
    )
    service.run_batch("2026-04-30", "daily", top_n=2)
    assert calls["n"] == 1

    updated = service.sync_hot_snapshot_from_source("2026-04-30", "daily", top_n=2, force_refresh=True)
    assert calls["n"] == 2
    assert updated["run"]["status"] == "completed"
    assert updated["items"]["热股"][0]["ts_name"] == "强制刷新后改名"
    assert len(updated["analysis_tasks"]) == 2


def test_hot_radar_completed_dashboard_not_overwritten_by_hot_refresh(tmp_path):
    calls = {"snapshot": 0}

    def snapshot_getter(trade_date, top_n):
        calls["snapshot"] += 1
        base = _snapshot()
        if calls["snapshot"] == 1:
            return base
        return {
            **base,
            "markets": {
                **base["markets"],
                "热股": [
                    {
                        **base["markets"]["热股"][0],
                        "ts_name": "若被覆盖则失败",
                    },
                    base["markets"]["热股"][1],
                ],
            },
        }

    analysis_service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        runtime_dir=tmp_path,
    )
    service = HotRadarService(
        analysis_service=analysis_service,
        database_url=f"sqlite:///{tmp_path / 'hot-radar.sqlite3'}",
        hot_snapshot_getter=snapshot_getter,
        trade_dates_getter=lambda end_date, limit: ["2026-04-30"],
    )
    service.run_batch("2026-04-30", "daily", top_n=2)
    assert calls["snapshot"] == 1

    again = service.get_dashboard("2026-04-30", "daily", top_n=2, fetch_if_missing=True)

    assert calls["snapshot"] == 1
    assert again["run"]["status"] == "completed"
    assert again["items"]["热股"][0]["ts_name"] == "华工科技"


def test_hot_radar_run_batch_requires_daily(tmp_path):
    analysis_service = AnalysisService(
        TaskRegistry(),
        runner=lambda request, config, emit: ({"final_trade_decision": "Rating: Hold"}, "Hold"),
        run_inline=True,
        runtime_dir=tmp_path,
    )
    service = HotRadarService(
        analysis_service=analysis_service,
        database_url=f"sqlite:///{tmp_path / 'hot-radar.sqlite3'}",
        hot_snapshot_getter=lambda trade_date, top_n: _snapshot(),
        trade_dates_getter=lambda end_date, limit: ["2026-04-30"],
    )
    with pytest.raises(ValueError, match="daily"):
        service.run_batch("2026-04-30", "12:00", top_n=2)
