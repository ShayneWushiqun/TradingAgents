import pandas as pd

from tradingagents.dataflows.tushare_stock import get_stock_snapshot


class FakeTushareClient:
    def daily(self, **kwargs):
        assert kwargs["ts_code"] == "600519.SH"
        return pd.DataFrame(
            [
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
                }
            ]
        )

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


def test_get_stock_snapshot_normalizes_tushare_rows():
    snapshot = get_stock_snapshot(
        "600519.SH",
        "2026-04-30",
        client=FakeTushareClient(),
    )

    assert snapshot["ts_code"] == "600519.SH"
    assert snapshot["trade_date"] == "2026-04-30"
    assert snapshot["price"]["close"] == 1684.2
    assert snapshot["price"]["pct_chg"] == 1.82
    assert snapshot["daily_basic"]["pe_ttm"] == 28.4
    assert snapshot["daily_basic"]["pb"] == 8.2
