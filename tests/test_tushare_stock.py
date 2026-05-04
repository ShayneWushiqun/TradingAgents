import pandas as pd

from tradingagents.dataflows.tushare_stock import get_stock_snapshot


class FakeTushareClient:
    def daily(self, **kwargs):
        assert kwargs["ts_code"] == "600519.SH"
        rows = [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260430",
                "open": 1660.0,
                "high": 1698.0,
                "low": 1650.0,
                "close": 1684.2,
                "pre_close": 1654.1,
                "pct_chg": 1.82,
                "amount": 4260000.0,
            },
            {
                "ts_code": "600519.SH",
                "trade_date": "20260429",
                "open": 1630.0,
                "high": 1660.0,
                "low": 1624.0,
                "close": 1654.1,
                "pre_close": 1635.0,
                "pct_chg": 1.1682,
                "amount": 3210000.0,
            },
        ]
        if "trade_date" in kwargs:
            return pd.DataFrame([rows[0]])
        return pd.DataFrame(rows)

    def daily_basic(self, **kwargs):
        assert kwargs["ts_code"] == "600519.SH"
        return pd.DataFrame(
            [
                {
                    "ts_code": "600519.SH",
                    "trade_date": "20260430",
                    "pe_ttm": 28.4,
                    "pb": 8.2,
                    "total_mv": 2110000.0,
                }
            ]
        )


class FakeWeekendTushareClient:
    def daily(self, **kwargs):
        assert kwargs["ts_code"] == "002081.SZ"
        if "trade_date" in kwargs:
            assert kwargs["trade_date"] == "20260502"
            return pd.DataFrame()
        assert kwargs["end_date"] in {"20260502", "20260430"}
        return pd.DataFrame(
            [
                {
                    "ts_code": "002081.SZ",
                    "trade_date": "20260430",
                    "open": 5.17,
                    "high": 5.9,
                    "low": 5.07,
                    "close": 5.9,
                    "pre_close": 5.36,
                    "pct_chg": 10.0746,
                    "amount": 3220259.781,
                }
            ]
        )

    def daily_basic(self, **kwargs):
        assert kwargs["ts_code"] == "002081.SZ"
        assert kwargs["trade_date"] == "20260430"
        return pd.DataFrame(
            [
                {
                    "ts_code": "002081.SZ",
                    "trade_date": "20260430",
                    "pe_ttm": 38.6151,
                    "pb": 1.1244,
                    "total_mv": 1566640.9765,
                }
            ]
        )


class FakeNamedTushareClient(FakeWeekendTushareClient):
    def daily(self, **kwargs):
        assert kwargs["ts_code"] == "600186.SH"
        if "trade_date" in kwargs:
            return pd.DataFrame(
                [
                    {
                        "ts_code": "600186.SH",
                        "trade_date": "20260430",
                        "open": 10.2,
                        "high": 11.0,
                        "low": 10.1,
                        "close": 10.72,
                        "pre_close": 10.82,
                        "pct_chg": -0.92,
                        "amount": 5285000.0,
                    }
                ]
            )
        return pd.DataFrame(
            [
                {
                    "ts_code": "600186.SH",
                    "trade_date": "20260430",
                    "open": 10.2,
                    "high": 11.0,
                    "low": 10.1,
                    "close": 10.72,
                    "pre_close": 10.82,
                    "pct_chg": -0.92,
                    "amount": 5285000.0,
                }
            ]
        )

    def daily_basic(self, **kwargs):
        assert kwargs["ts_code"] == "600186.SH"
        return pd.DataFrame(
            [
                {
                    "ts_code": "600186.SH",
                    "trade_date": "20260430",
                    "pe_ttm": 54.66,
                    "pb": 3.1,
                    "total_mv": 1922000.0,
                }
            ]
        )

    def stock_basic(self, **kwargs):
        assert kwargs["ts_code"] == "600186.SH"
        return pd.DataFrame([{"ts_code": "600186.SH", "name": "莲花控股"}])


def test_get_stock_snapshot_normalizes_tushare_rows():
    snapshot = get_stock_snapshot(
        "600519.SH",
        "2026-04-30",
        client=FakeTushareClient(),
    )

    assert snapshot["ts_code"] == "600519.SH"
    assert snapshot["name"] == ""
    assert snapshot["trade_date"] == "2026-04-30"
    assert snapshot["price"]["close"] == 1684.2
    assert snapshot["price"]["pct_chg"] == 1.82
    assert snapshot["daily_basic"]["pe_ttm"] == 28.4
    assert snapshot["daily_basic"]["pb"] == 8.2
    assert len(snapshot["ohlcv"]) == 2
    assert snapshot["ohlcv"][0]["trade_date"] == "2026-04-29"
    assert snapshot["ohlcv"][1]["close"] == 1684.2


def test_get_stock_snapshot_falls_back_to_latest_trading_day():
    snapshot = get_stock_snapshot(
        "002081.SZ",
        "2026-05-02",
        client=FakeWeekendTushareClient(),
    )

    assert snapshot["requested_trade_date"] == "2026-05-02"
    assert snapshot["trade_date"] == "2026-04-30"
    assert snapshot["is_fallback"] is True
    assert snapshot["price"]["close"] == 5.9
    assert snapshot["daily_basic"]["pe_ttm"] == 38.6151


def test_get_stock_snapshot_resolves_name_from_stock_basic_when_daily_lacks_name():
    snapshot = get_stock_snapshot(
        "600186.SH",
        "2026-04-30",
        client=FakeNamedTushareClient(),
    )

    assert snapshot["name"] == "莲花控股"
