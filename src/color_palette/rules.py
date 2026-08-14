from __future__ import annotations


RULESET_VERSION = "p1-rules-0.10.0"


def tone_code(shares: dict, median_l: float) -> tuple[str, str]:
    """Classify overall key without letting one large bright region dominate.

    High-key requires a genuinely bright median, or a very large highlight share
    combined with restrained shadows. Low-key mirrors the same logic.
    """
    if median_l >= 62:
        return "high_key", "高调结构"
    if shares["highlights"] >= 0.42 and shares["shadows"] <= 0.32:
        return "high_key", "高调结构"
    if median_l <= 35:
        return "low_key", "低调结构"
    if shares["shadows"] >= 0.55 and shares["highlights"] <= 0.25:
        return "low_key", "低调结构"
    return "mid_key", "中间调结构"


def contrast_level(span_l: float) -> str:
    if span_l >= 70:
        return "高"
    if span_l >= 50:
        return "中"
    return "低"


def saturation_level(median_s: float) -> str:
    if median_s < 0.20:
        return "低"
    if median_s < 0.45:
        return "中"
    return "高"


def clipping_class(share: float) -> str:
    if share >= 0.005:
        return "明显"
    if share >= 0.001:
        return "轻微"
    return "无"


def white_balance_judgement(
    neutral_share: float,
    neutral_coverage: float,
    a_median: float | None,
    b_median: float | None,
) -> tuple[str, str]:
    """Judge WB only when neutral pixels are both sufficient and spatially distributed."""
    if (
        neutral_share < 0.05
        or neutral_coverage < 0.25
        or a_median is None
        or b_median is None
    ):
        return "中性色不足", "可信中性色不足，暂不下确定结论"
    parts: list[str] = []
    if a_median > 2.5:
        parts.append("轻微偏洋红" if abs(a_median) < 5 else "偏洋红")
    elif a_median < -2.5:
        parts.append("轻微偏绿" if abs(a_median) < 5 else "偏绿")
    if b_median > 2.5:
        parts.append("轻微偏暖黄" if abs(b_median) < 5 else "偏暖黄")
    elif b_median < -2.5:
        parts.append("轻微偏冷蓝" if abs(b_median) < 5 else "偏冷蓝")
    return "有效", "、".join(parts) if parts else "接近中性"
