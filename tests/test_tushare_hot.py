import pandas as pd

from tradingagents.dataflows.tushare_hot import (
    get_recent_trade_dates,
    get_ths_hot_snapshot,
    resolve_trade_date,
)


class FakeTushareHotClient:
    def trade_cal(self, **kwargs):
        return pd.DataFrame(
            [
                {"cal_date": "20260424", "is_open": 1, "pretrade_date": "20260423"},
                {"cal_date": "20260425", "is_open": 0, "pretrade_date": "20260424"},
                {"cal_date": "20260426", "is_open": 0, "pretrade_date": "20260424"},
                {"cal_date": "20260427", "is_open": 1, "pretrade_date": "20260424"},
                {"cal_date": "20260428", "is_open": 1, "pretrade_date": "20260427"},
                {"cal_date": "20260429", "is_open": 1, "pretrade_date": "20260428"},
                {"cal_date": "20260430", "is_open": 1, "pretrade_date": "20260429"},
            ]
        )

    def ths_hot(self, **kwargs):
        assert kwargs["fields"] == "trade_date,data_type,ts_code,ts_name,rank,pct_change,current_price,concept,rank_reason,hot,rank_time"
        assert kwargs["is_new"] == "Y"
        market = kwargs["market"]
        if market == "热股":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20260430",
                        "data_type": "热股",
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
                        "trade_date": "20260430",
                        "data_type": "热股",
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
                ]
            )
        return pd.DataFrame(
            [
                {
                    "trade_date": "20260430",
                    "data_type": market,
                    "ts_code": "",
                    "ts_name": f"{market}一号",
                    "rank": 1,
                    "pct_change": 2.2,
                    "current_price": None,
                    "concept": market,
                    "rank_reason": "热度靠前",
                    "hot": 88.0,
                    "rank_time": "10:03:18",
                }
            ]
        )


def test_recent_trade_dates_only_returns_open_days_descending():
    dates = get_recent_trade_dates("2026-04-30", limit=4, client=FakeTushareHotClient())

    assert dates == ["2026-04-30", "2026-04-29", "2026-04-28", "2026-04-27"]


def test_resolve_trade_date_uses_previous_open_day_for_closed_day():
    resolved = resolve_trade_date("2026-04-26", client=FakeTushareHotClient())

    assert resolved == "2026-04-24"


def test_ths_hot_snapshot_groups_markets_and_limits_hot_stocks():
    snapshot = get_ths_hot_snapshot(
        "2026-04-30",
        top_n=1,
        client=FakeTushareHotClient(),
    )

    assert snapshot["trade_date"] == "2026-04-30"
    assert len(snapshot["markets"]["热股"]) == 1
    assert snapshot["markets"]["热股"][0]["ts_code"] == "000988.SZ"
    assert snapshot["markets"]["热股"][0]["hot"] == 96.8
    assert snapshot["markets"]["ETF"][0]["ts_name"] == "ETF一号"
    assert snapshot["markets"]["行业板块"][0]["rank_reason"] == "热度靠前"
    assert snapshot["markets"]["概念板块"][0]["rank"] == 1


def test_ths_hot_snapshot_deduplicates_hot_stocks_before_limit():
    class DuplicateHotClient(FakeTushareHotClient):
        def ths_hot(self, **kwargs):
            frame = super().ths_hot(**kwargs)
            if kwargs["market"] == "热股":
                return pd.concat([frame.iloc[[0]], frame.iloc[[0]], frame.iloc[[1]]], ignore_index=True)
            return frame

    snapshot = get_ths_hot_snapshot(
        "2026-04-30",
        top_n=2,
        client=DuplicateHotClient(),
    )

    assert [row["ts_code"] for row in snapshot["markets"]["热股"]] == [
        "000988.SZ",
        "603629.SH",
    ]


def test_ths_hot_snapshot_keeps_latest_rank_time_for_duplicate_stock():
    class LatestDuplicateHotClient(FakeTushareHotClient):
        def ths_hot(self, **kwargs):
            frame = super().ths_hot(**kwargs)
            if kwargs["market"] != "热股":
                return frame
            older = frame.iloc[[0]].copy()
            older.loc[older.index[0], "hot"] = 100.0
            older.loc[older.index[0], "rank_time"] = "2026-05-01 21:30:02"
            newer = frame.iloc[[0]].copy()
            newer.loc[newer.index[0], "hot"] = 200.0
            newer.loc[newer.index[0], "rank_time"] = "2026-05-01 22:30:00"
            return pd.concat([older, newer, frame.iloc[[1]]], ignore_index=True)

    snapshot = get_ths_hot_snapshot(
        "2026-05-01",
        top_n=2,
        client=LatestDuplicateHotClient(),
    )

    first = snapshot["markets"]["热股"][0]
    assert first["ts_code"] == "000988.SZ"
    assert first["hot"] == 200.0
    assert first["rank_time"] == "2026-05-01 22:30:00"


def test_ths_hot_snapshot_keeps_latest_rank_time_for_duplicate_hms_only_rows():
    """同一 ts_code 多条仅含 %H:%M:%S 的 rank_time 时，保留时间最晚的一条。"""

    class HmsTripletClient(FakeTushareHotClient):
        def ths_hot(self, **kwargs):
            frame = super().ths_hot(**kwargs)
            if kwargs["market"] != "热股":
                return frame

            def tweak(hot: float, rank_time: str):
                r = frame.iloc[[0]].copy()
                r.loc[r.index[0], "hot"] = hot
                r.loc[r.index[0], "rank_time"] = rank_time
                return r

            return pd.concat(
                [
                    tweak(100.0, "21:30:00"),
                    tweak(200.0, "22:00:00"),
                    tweak(300.0, "22:30:00"),
                    frame.iloc[[1]],
                ],
                ignore_index=True,
            )

    snapshot = get_ths_hot_snapshot(
        "2026-04-30",
        top_n=2,
        client=HmsTripletClient(),
    )
    first = snapshot["markets"]["热股"][0]
    assert first["ts_code"] == "000988.SZ"
    assert first["hot"] == 300.0
    assert first["rank_time"] == "22:30:00"
