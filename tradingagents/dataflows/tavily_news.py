from __future__ import annotations

import os
from typing import Any

import requests

from .vendor_errors import DataVendorUnavailable


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _api_key() -> str:
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        raise DataVendorUnavailable("TAVILY_API_KEY is not configured")
    return key


def _post_search(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            TAVILY_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise DataVendorUnavailable(f"Tavily request failed: {exc}") from exc

    if response.status_code in {401, 402, 403, 429, 432, 433}:
        raise DataVendorUnavailable(f"Tavily unavailable: HTTP {response.status_code}")
    if not response.ok:
        raise DataVendorUnavailable(f"Tavily request failed: HTTP {response.status_code}")

    return response.json()


def _format_results(title: str, body: dict[str, Any]) -> str:
    results = body.get("results") or []
    if not results:
        raise DataVendorUnavailable(f"{title} returned no results")

    rows = [f"## {title}"]
    answer = body.get("answer")
    if answer:
        rows.append(f"摘要: {answer}")

    for item in results[:6]:
        headline = item.get("title") or "未命名新闻"
        url = item.get("url") or ""
        content = item.get("content") or item.get("raw_content") or ""
        line = f"- {headline}"
        if url:
            line += f"\n  链接: {url}"
        if content:
            line += f"\n  摘要: {content[:500]}"
        rows.append(line)

    return "\n".join(rows)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    query = f"{ticker} A股 公司 新闻 公告 财报 行业政策"
    body = _post_search(
        {
            "query": query,
            "topic": "finance",
            "search_depth": "basic",
            "max_results": 6,
            "include_answer": "basic",
            "include_raw_content": False,
            "start_date": start_date,
            "end_date": end_date,
        }
    )
    return _format_results(f"Tavily 新闻搜索 {ticker} {start_date} 至 {end_date}", body)


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
    body = _post_search(
        {
            "query": "A股 市场 新闻 宏观政策 行业热点",
            "topic": "finance",
            "search_depth": "basic",
            "max_results": limit,
            "include_answer": "basic",
            "include_raw_content": False,
            "days": look_back_days,
            "end_date": curr_date,
        }
    )
    return _format_results(f"Tavily A股市场新闻 截至 {curr_date}", body)
