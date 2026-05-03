from __future__ import annotations

from typing import Any

import requests

from .vendor_errors import DataVendorUnavailable


TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbol}"


def _tencent_symbol(ts_code: str) -> str:
    code = ts_code.strip().upper()
    if code.endswith(".SZ"):
        return "sz" + code.split(".")[0]
    if code.endswith(".SH"):
        return "sh" + code.split(".")[0]
    if code.endswith(".BJ"):
        return "bj" + code.split(".")[0]
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    raise DataVendorUnavailable(f"Unsupported Tencent symbol: {ts_code}")


def get_quote(ts_code: str) -> dict[str, Any]:
    symbol = _tencent_symbol(ts_code)
    try:
        response = requests.get(
            TENCENT_QUOTE_URL.format(symbol=symbol),
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except requests.RequestException as exc:
        raise DataVendorUnavailable(f"Tencent Finance request failed: {exc}") from exc

    if not response.ok:
        raise DataVendorUnavailable(f"Tencent Finance HTTP {response.status_code}")

    text = response.text.strip()
    if "~" not in text:
        raise DataVendorUnavailable("Tencent Finance returned no quote fields")

    try:
        payload = text.split('"', 2)[1]
    except IndexError as exc:
        raise DataVendorUnavailable("Tencent Finance quote format changed") from exc

    fields = payload.split("~")
    if len(fields) < 33:
        raise DataVendorUnavailable("Tencent Finance quote fields are incomplete")

    return {
        "source": "tencent_finance",
        "symbol": symbol,
        "name": fields[1],
        "code": fields[2],
        "price": _to_float(fields[3]),
        "pre_close": _to_float(fields[4]),
        "open": _to_float(fields[5]),
        "volume": _to_float(fields[6]),
        "amount": _to_float(fields[37] if len(fields) > 37 else ""),
        "pct_chg": _to_float(fields[32]),
        "change": _to_float(fields[31]),
        "high": _to_float(fields[33] if len(fields) > 33 else ""),
        "low": _to_float(fields[34] if len(fields) > 34 else ""),
        "time": fields[30],
    }


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
