#!/usr/bin/env python3
"""
调用 Tushare ths_hot（同花顺 App 热榜，doc_id=320）并打印返回示例。

官方文档: https://tushare.pro/document/2?doc_id=320

用法:
  export TUSHARE_API_TOKEN=你的token
  uv run python scripts/tushare_ths_hot_sample.py
  # 或指定日期、市场:
  TRADE_DATE=20260501 MARKET=热股 uv run python scripts/tushare_ths_hot_sample.py
"""

from __future__ import annotations

import os
import sys

import pandas as pd


def main() -> None:
    trade_date = os.getenv("TRADE_DATE", "20260501")  # YYYYMMDD
    market = os.getenv("MARKET", "热股")
    is_new = os.getenv("IS_NEW", "Y")

    token = (os.getenv("TUSHARE_API_TOKEN") or "").strip()
    if not token:
        print("请设置环境变量 TUSHARE_API_TOKEN", file=sys.stderr)
        sys.exit(1)

    import tushare as ts

    # 直接使用 token，避免 set_token 写入 ~/.tushare
    pro = ts.pro_api(token)

    # 与文档示例一致；fields 可省略以拉全量列
    kwargs = {
        "trade_date": trade_date,
        "market": market,
        "is_new": is_new,
    }
    print("请求参数:", kwargs)
    print()

    df = pro.ths_hot(**kwargs)

    print("返回类型:", type(df))
    print("行数 × 列数:", df.shape)
    print("列名:", list(df.columns))
    print()
    print("--- 前 10 行 ---")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 60)
    print(df.head(10))
    print()
    print("--- dtypes ---")
    print(df.dtypes)


if __name__ == "__main__":
    main()
