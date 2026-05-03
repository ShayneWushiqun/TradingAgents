from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .tushare_client import create_tushare_client


HOT_RADAR_MARKETS: tuple[str, ...] = ("热股", "ETF", "行业板块", "概念板块")
THS_HOT_FIELDS = (
    "trade_date,data_type,ts_code,ts_name,rank,pct_change,current_price,"
    "concept,rank_reason,hot,rank_time"
)


def _api_date(date: str) -> str:
    return datetime.strptime(date, "%Y-%m-%d").strftime("%Y%m%d")


def _display_date(date: str) -> str:
    return datetime.strptime(str(date), "%Y%m%d").strftime("%Y-%m-%d")


def _clean(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _rank_time_key(value: Any) -> datetime:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt == "%H:%M:%S":
                return datetime(1900, 1, 1, parsed.hour, parsed.minute, parsed.second)
            return parsed
        except ValueError:
            continue
    return datetime.min


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        {key: _clean(value) for key, value in row.items()}
        for row in frame.where(pd.notnull(frame), None).to_dict("records")
    ]


def get_recent_trade_dates(
    end_date: str | None = None,
    limit: int = 30,
    client=None,
) -> list[str]:
    client = client or create_tushare_client()
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
    start = (end - timedelta(days=70)).strftime("%Y%m%d")
    frame = client.trade_cal(
        exchange="SSE",
        start_date=start,
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
    )
    if frame.empty:
        return []
    frame = frame.sort_values("cal_date", ascending=False).head(limit)
    return [_display_date(row["cal_date"]) for row in _records(frame)]


def resolve_trade_date(target_date: str | None = None, client=None) -> str:
    client = client or create_tushare_client()
    target = datetime.strptime(target_date, "%Y-%m-%d") if target_date else datetime.now()
    start = (target - timedelta(days=14)).strftime("%Y%m%d")
    api_target = target.strftime("%Y%m%d")
    frame = client.trade_cal(
        exchange="SSE",
        start_date=start,
        end_date=api_target,
    )
    if frame.empty:
        return target.strftime("%Y-%m-%d")
    frame = frame[frame["cal_date"].astype(str) <= api_target]
    if frame.empty:
        return target.strftime("%Y-%m-%d")
    frame = frame.sort_values("cal_date", ascending=False)
    for row in _records(frame):
        if int(row.get("is_open") or 0) == 1:
            return _display_date(row["cal_date"])
    latest = frame.iloc[0].to_dict()
    previous = latest.get("pretrade_date") or latest.get("cal_date")
    return _display_date(previous)


def _normalize_hot_row(row: dict[str, Any], market: str, trade_date: str) -> dict[str, Any]:
    raw_date = row.get("trade_date") or trade_date
    display_date = _display_date(raw_date) if str(raw_date).isdigit() else str(raw_date)
    return {
        "trade_date": display_date,
        "market": market,
        "ts_code": str(row.get("ts_code") or row.get("code") or ""),
        "ts_name": str(row.get("ts_name") or row.get("name") or ""),
        "rank": _safe_int(row.get("rank")),
        "pct_change": row.get("pct_change"),
        "current_price": row.get("current_price"),
        "concept": str(row.get("concept") or ""),
        "rank_reason": str(row.get("rank_reason") or ""),
        "hot": row.get("hot"),
        "rank_time": str(row.get("rank_time") or ""),
    }


def _dedupe_hot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("ts_code") or row.get("ts_name") or row.get("rank") or "")
        existing = by_key.get(key)
        if existing is None or _rank_time_key(row.get("rank_time")) >= _rank_time_key(existing.get("rank_time")):
            by_key[key] = row
    deduped = list(by_key.values())
    deduped.sort(key=lambda item: item.get("rank") or 999999)
    return deduped


def get_ths_hot_snapshot(
    trade_date: str,
    top_n: int = 20,
    client=None,
    markets: tuple[str, ...] = HOT_RADAR_MARKETS,
    is_new: str = "Y",
) -> dict[str, Any]:
    client = client or create_tushare_client()
    api_date = _api_date(trade_date)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        frame = client.ths_hot(
            trade_date=api_date,
            market=market,
            is_new=is_new,
            fields=THS_HOT_FIELDS,
        )
        rows = [_normalize_hot_row(row, market, trade_date) for row in _records(frame)]
        rows = sorted(rows, key=lambda item: item.get("rank") or 999999)
        rows = _dedupe_hot_rows(rows)
        grouped[market] = rows[:top_n]
    return {
        "trade_date": trade_date,
        "top_n": top_n,
        "is_new": is_new,
        "markets": grouped,
    }
