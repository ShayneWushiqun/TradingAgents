"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.
"""

from __future__ import annotations

import re
from typing import Tuple


# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

_TIER_ALT = "|".join(RATINGS_5_TIER)

# Explicit English tier tokens only — avoids ``\w+`` greedily absorbing CJK/markdown around the value,
# which used to collapse many Chinese-labelled PM outputs to default **Hold**.
_TIER_BOUNDARY_RE = re.compile(rf"\b(?P<tier>{_TIER_ALT})\b", re.IGNORECASE)


def _labeled_rating_patterns() -> tuple[re.Pattern[str], ...]:
    """Explicit label → tier anchors (rating / Chinese 评级).

    Checked on every non-empty line; first structural match wins in document order.
    """
    return (
        re.compile(
            rf"(?:\*{{0,2}}\s*)?rating(?:\*{{0,2}}\s*)?[:\-]\s*\*{{0,2}}\s*\b({_TIER_ALT})\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:\*{{0,2}}\s*)?rating(?:\*{{0,2}}\s*)?[:\-]\s*\b({_TIER_ALT})\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:\*{{0,2}}\s*)?(?:评级|最终评级|最终裁决)(?:\*{{0,2}}\s*)?[：:]\s*\*{{0,2}}\s*\b({_TIER_ALT})\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?:\*{{0,2}}\s*)?(?:评级|最终评级|最终裁决)(?:\*{{0,2}}\s*)?[：:]\s*\b({_TIER_ALT})\b",
            re.IGNORECASE,
        ),
    )


_LABELED_LINE_HINT = re.compile(
    r"(rating|评级|最终评级|最终裁决|最终决定|最终决策|最终交易决策|recommendation\s*[:：]|action\s*[:：])",
    re.IGNORECASE,
)

_CHINESE_RATING_LABEL_RE = re.compile(
    r"(?:评级|最终评级|最终裁决|最终决定|最终决策|最终交易决策|交易决策|操作建议)\s*[：:\-]\s*"
    r"(?P<tier>买入|增持|持有|观望|中性|减仓|减持|减配|卖出|清仓)",
    re.IGNORECASE,
)

_CHINESE_RATING_MAP = {
    "买入": "Buy",
    "增持": "Overweight",
    "持有": "Hold",
    "观望": "Hold",
    "中性": "Hold",
    "减仓": "Underweight",
    "减持": "Underweight",
    "减配": "Underweight",
    "卖出": "Sell",
    "清仓": "Sell",
}


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Two-pass strategy:
    1. Look for an explicit "Rating: X" label (tolerant of markdown bold).
    2. Fall back to the first 5-tier rating word found anywhere in the text.

    Returns a Title-cased rating string, or ``default`` if no rating word appears.
    """
    lines = text.splitlines()
    if not any(l.strip() for l in lines):
        return default

    patterns = _labeled_rating_patterns()
    for line in lines:
        if not line.strip():
            continue
        chinese_match = _CHINESE_RATING_LABEL_RE.search(line)
        if chinese_match:
            return _CHINESE_RATING_MAP[chinese_match.group("tier")]
        for pat in patterns:
            m = pat.search(line)
            if m and m.group(1).lower() in _RATING_SET:
                return m.group(1).capitalize()

    head = lines[:200]
    priority = [ln for ln in head if _LABELED_LINE_HINT.search(ln)]
    ordered = priority + [ln for ln in head if ln not in priority]

    for line in ordered:
        if not line.strip():
            continue
        m = _TIER_BOUNDARY_RE.search(line)
        if m and m.group("tier").lower() in _RATING_SET:
            return m.group("tier").capitalize()

    for line in lines:
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                return clean.capitalize()

    return default
