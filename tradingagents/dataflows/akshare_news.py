from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any

import pandas as pd

from .vendor_errors import DataVendorUnavailable


def _load_akshare():
    try:
        return importlib.import_module("akshare")
    except ImportError as exc:
        raise DataVendorUnavailable("AKShare is not installed") from exc


def _plain_symbol(ticker: str) -> str:
    return ticker.strip().upper().split(".")[0]


def _format_records(title: str, frame: pd.DataFrame, limit: int = 8) -> str:
    if frame.empty:
        raise DataVendorUnavailable(f"{title} returned no records")

    rows: list[str] = [f"## {title}"]
    for _, row in frame.head(limit).iterrows():
        values = {str(key): value for key, value in row.where(pd.notnull(row), "").to_dict().items()}
        headline = (
            values.get("标题")
            or values.get("title")
            or values.get("新闻标题")
            or values.get("公告标题")
            or values.get("内容")
            or "未命名条目"
        )
        date = values.get("发布时间") or values.get("日期") or values.get("公告日期") or values.get("time") or ""
        source = values.get("文章来源") or values.get("来源") or values.get("source") or "AKShare"
        url = values.get("新闻链接") or values.get("url") or values.get("链接") or ""
        summary = values.get("摘要") or values.get("内容") or values.get("summary") or ""

        line = f"- {headline}"
        if date:
            line += f" ({date})"
        line += f" | 来源: {source}"
        if summary and summary != headline:
            line += f"\n  摘要: {summary}"
        if url:
            line += f"\n  链接: {url}"
        rows.append(line)

    return "\n".join(rows)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    ak = _load_akshare()
    symbol = _plain_symbol(ticker)

    try:
        try:
            frame = ak.stock_news_em(symbol=symbol)
        except TypeError:
            frame = ak.stock_news_em(stock=symbol)
    except Exception as exc:
        raise DataVendorUnavailable(f"AKShare stock_news_em failed: {exc}") from exc

    return _format_records(f"AKShare 个股新闻 {ticker} {start_date} 至 {end_date}", frame)


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
    ak = _load_akshare()

    try:
        frame = ak.stock_news_main_cx()
    except Exception as exc:
        raise DataVendorUnavailable(f"AKShare stock_news_main_cx failed: {exc}") from exc

    cutoff = datetime.strptime(curr_date, "%Y-%m-%d")
    title = f"AKShare 市场新闻 截至 {cutoff.date()}，近 {look_back_days} 天"
    return _format_records(title, frame, limit=limit)
