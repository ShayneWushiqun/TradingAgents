from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .tushare_client import create_tushare_client


def _api_date(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%Y%m%d")


def _display_date(date: str) -> str:
    return datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")


def _first_record(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    return frame.iloc[0].where(pd.notnull(frame.iloc[0]), None).to_dict()


def _latest_daily_record(client, ts_code: str, api_date: str) -> dict[str, Any]:
    daily = _first_record(client.daily(ts_code=ts_code, trade_date=api_date))
    if daily:
        return daily

    start_date = (
        datetime.strptime(api_date, "%Y%m%d") - timedelta(days=14)
    ).strftime("%Y%m%d")
    recent = client.daily(ts_code=ts_code, start_date=start_date, end_date=api_date)
    if recent.empty:
        return {}
    recent = recent.sort_values("trade_date", ascending=False)
    return _first_record(recent)


def _daily_window(client, ts_code: str, api_date: str, days: int = 120, limit: int = 60) -> list[dict[str, Any]]:
    start_date = (
        datetime.strptime(api_date, "%Y%m%d") - timedelta(days=days)
    ).strftime("%Y%m%d")
    frame = client.daily(ts_code=ts_code, start_date=start_date, end_date=api_date)
    if frame.empty:
        return []
    frame = frame.sort_values("trade_date", ascending=True).tail(limit)
    records: list[dict[str, Any]] = []
    for row in frame.where(pd.notnull(frame), None).to_dict("records"):
        records.append(
            {
                "trade_date": _display_date(str(row.get("trade_date"))),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "pre_close": row.get("pre_close"),
                "pct_chg": row.get("pct_chg"),
                "amount": row.get("amount"),
            }
        )
    return records


def get_stock_snapshot(ts_code: str, trade_date: str, client=None) -> dict[str, Any]:
    client = client or create_tushare_client()
    api_date = _api_date(trade_date)

    daily = _latest_daily_record(client, ts_code, api_date)
    resolved_api_date = str(daily.get("trade_date", api_date))
    daily_basic = _first_record(client.daily_basic(ts_code=ts_code, trade_date=resolved_api_date))
    ohlcv = _daily_window(client, ts_code, resolved_api_date)

    return {
        "ts_code": ts_code,
        "name": "",
        "requested_trade_date": trade_date,
        "trade_date": _display_date(resolved_api_date),
        "is_fallback": resolved_api_date != api_date,
        "price": {
            "open": daily.get("open"),
            "high": daily.get("high"),
            "low": daily.get("low"),
            "close": daily.get("close"),
            "pre_close": daily.get("pre_close"),
            "pct_chg": daily.get("pct_chg"),
            "amount": daily.get("amount"),
        },
        "daily_basic": {
            "pe_ttm": daily_basic.get("pe_ttm"),
            "pb": daily_basic.get("pb"),
            "total_mv": daily_basic.get("total_mv"),
        },
        "ohlcv": ohlcv,
    }


def get_stock_data(ts_code: str, start_date: str, end_date: str) -> str:
    client = create_tushare_client()
    frame = client.daily(
        ts_code=ts_code,
        start_date=_api_date(start_date),
        end_date=_api_date(end_date),
    )
    return frame.to_csv(index=False)


def get_indicators(ts_code: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    return (
        f"Tushare indicator adapter received {indicator} for {ts_code}. "
        "MVP computes technical indicators from pro_bar in the web layer."
    )


def get_fundamentals(ts_code: str, curr_date: str = "") -> str:
    snapshot = get_stock_snapshot(ts_code, curr_date or "2026-04-30")
    return str(snapshot["daily_basic"])


def get_balance_sheet(ts_code: str, freq: str = "annual", curr_date: str = "") -> str:
    client = create_tushare_client()
    return client.balancesheet(ts_code=ts_code).head(8).to_csv(index=False)


def get_cashflow(ts_code: str, freq: str = "annual", curr_date: str = "") -> str:
    client = create_tushare_client()
    return client.cashflow(ts_code=ts_code).head(8).to_csv(index=False)


def get_income_statement(ts_code: str, freq: str = "annual", curr_date: str = "") -> str:
    client = create_tushare_client()
    return client.income(ts_code=ts_code).head(8).to_csv(index=False)
