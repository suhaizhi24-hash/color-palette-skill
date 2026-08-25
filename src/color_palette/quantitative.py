from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, lab2rgb
from sklearn.cluster import MiniBatchKMeans

from .faces import skin_candidate_mask
from .lighting import SubjectRegion

LUMINANCE_PERCENTILES = (1, 5, 25, 50, 75, 95, 99)
CHROMA_PERCENTILES = (25, 50, 75, 90)
LUMINANCE_HISTOGRAM_BINS = 64
LUMINANCE_HISTOGRAM_RANGE = (0.0, 100.0)
CHROMA_HISTOGRAM_BINS = 48
CHROMA_HISTOGRAM_RANGE = (0.0, 120.0)
LOW_CHROMA_MAX = 10.0
HIGH_CHROMA_MIN = 30.0
HUE_ELIGIBLE_CHROMA_MIN = 10.0
HUE_ELIGIBLE_L_MIN = 5.0
HUE_ELIGIBLE_L_MAX = 95.0
NEUTRAL_CHROMA_MAX = 8.0
NEUTRAL_L_MIN = 10.0
NEUTRAL_L_MAX = 95.0
NEUTRAL_GRID_SIZE = 4
NEUTRAL_CONFIDENCE_VALID_MIN = 0.68
NEUTRAL_SHARE_SCORE_RANGE = (0.03, 0.15)
NEUTRAL_COVERAGE_SCORE_RANGE = (0.25, 0.75)
NEUTRAL_REGION_SHARE_SCORE_RANGE = (0.01, 0.08)
NEUTRAL_CONCENTRATION_SCORE_RANGE = (0.60, 0.25)
NEUTRAL_DISPERSION_SCORE_RANGE = (5.5, 2.5)
TONE_SPAN_NEUTRAL_MIN = 0.8
TONE_SPAN_NEUTRAL_MAX = 1.2
MAIN_SUBJECT_GRABCUT_SEED = 42
SCENE_PALETTE_CLUSTERS = 6
SCENE_PALETTE_MAX_SAMPLES = 30_000
SCENE_PALETTE_SEED = 42
SCENE_CLUSTER_MERGE_DELTA_E00 = 4.0
SUBJECT_BACKGROUND_MARGIN_SHARE = 0.03
EPSILON = 1e-6

HUE_LABELS = (
    "红",
    "橙",
    "黄",
    "黄绿",
    "绿",
    "青绿",
    "青",
    "蓝青",
    "蓝",
    "蓝紫",
    "洋红",
    "红紫",
)

PALETTE_ROLE_DISPLAY = {
    "primary": "主色",
    "secondary": "辅助色",
    "accent": "点缀色",
    "other": "其他",
}

NEUTRAL_TONE_BANDS = (
    ("深黑", 0.0, 20.0),
    ("阴影", 20.0, 40.0),
    ("中间调", 40.0, 60.0),
    ("亮部", 60.0, 80.0),
    ("高光", 80.0, 100.000001),
)

NEUTRAL_RANGES = (
    ("shadow", 0.0, 35.0),
    ("midtone", 35.0, 70.0),
    ("highlight", 70.0, 100.000001),
)


@dataclass(frozen=True)
class QuantitativeResult:
    quantitative: dict
    color_dna: dict


def analyze_quantitative(
    rgb: np.ndarray,
    lab: np.ndarray,
    valid_mask: np.ndarray,
    *,
    subject: SubjectRegion,
    lighting: dict,
    material_effects: dict,
) -> QuantitativeResult:
    """Measure display-referred sRGB pixels without inferring edit parameters."""

    started = time.perf_counter()
    _validate_inputs(rgb, lab, valid_mask)
    valid_count = int(valid_mask.sum())
    lstar = lab[..., 0].astype(np.float64, copy=False)
    astar = lab[..., 1].astype(np.float64, copy=False)
    bstar = lab[..., 2].astype(np.float64, copy=False)
    chroma = np.hypot(astar, bstar)
    valid_l = lstar[valid_mask]
    valid_c = chroma[valid_mask]
    quantitative_subject, subject_exclusion, subject_diagnostics = (
        _prepare_quantitative_subject(rgb, lab, valid_mask, subject)
    )

    luminance_percentiles = _percentiles(valid_l, LUMINANCE_PERCENTILES)
    chroma_percentiles = _percentiles(valid_c, CHROMA_PERCENTILES)
    luminance_shares = {
        "l_below_5": _share(valid_l < 5.0),
        "l_below_10": _share(valid_l < 10.0),
        "l_above_90": _share(valid_l > 90.0),
        "l_above_95": _share(valid_l > 95.0),
        "l_above_99": _share(valid_l > 99.0),
        "near_black_share": _share(valid_l < 5.0),
        "shadow_share": _share(valid_l < 10.0),
        "highlight_share": _share(valid_l > 90.0),
        "near_white_share": _share(valid_l > 95.0),
        "black_clip_share": _share(valid_l <= 1.0),
        "white_clip_share": _share(valid_l >= 99.0),
    }

    luminance_histogram = _normalized_histogram(
        valid_l,
        bins=LUMINANCE_HISTOGRAM_BINS,
        value_range=LUMINANCE_HISTOGRAM_RANGE,
    )
    chroma_in_range = valid_c[valid_c <= CHROMA_HISTOGRAM_RANGE[1]]
    chroma_histogram = _normalized_histogram(
        chroma_in_range,
        bins=CHROMA_HISTOGRAM_BINS,
        value_range=CHROMA_HISTOGRAM_RANGE,
        denominator=valid_c.size,
    )

    local_contrast = _local_contrast(
        lstar,
        valid_mask,
        quantitative_subject,
        background_exclusion=subject_exclusion,
    )
    global_contrast = luminance_percentiles["p95"] - luminance_percentiles["p5"]
    midtone_contrast = luminance_percentiles["p75"] - luminance_percentiles["p25"]
    contrast = {
        "global_l_p95_p5": _round(global_contrast),
        "midtone_l_p75_p25": _round(midtone_contrast),
        **local_contrast,
    }

    tone_signature = _tone_signature(luminance_percentiles)
    chroma_shares = {
        "low_chroma_share": _share(valid_c < LOW_CHROMA_MAX),
        "mid_chroma_share": _share(
            (valid_c >= LOW_CHROMA_MAX) & (valid_c < HIGH_CHROMA_MIN)
        ),
        "high_chroma_share": _share(valid_c >= HIGH_CHROMA_MIN),
        "overflow_share": _share(valid_c > CHROMA_HISTOGRAM_RANGE[1]),
    }
    chroma_result = {
        "percentiles": chroma_percentiles,
        "shares": chroma_shares,
        "histogram": chroma_histogram,
    }

    hue_distribution = _hue_distribution(lstar, astar, bstar, chroma, valid_mask)
    neutral_axis, neutral_mask = _neutral_axis(
        lstar,
        astar,
        bstar,
        chroma,
        valid_mask,
        subject_mask=quantitative_subject.mask,
        background_exclusion=subject_exclusion,
    )
    neutral_tone_palette = _neutral_tone_palette(
        rgb, lab, lstar, neutral_mask, valid_count
    )
    scene_palette = _scene_palette(rgb, lab, valid_mask)
    subject_background = _subject_background(
        lab,
        lstar,
        chroma,
        valid_mask,
        quantitative_subject,
        background_exclusion=subject_exclusion,
        diagnostics=subject_diagnostics,
    )
    confidence = _confidence_summary(lighting, material_effects)

    quantitative = {
        "measurement_context": {
            "input_interpretation": "ICC标准化后的sRGB显示成片",
            "lightness_model": "CIELAB L*",
            "chroma_model": "CIELAB C*ab",
            "edit_parameter_inference": False,
        },
        "luminance": {
            "percentiles": luminance_percentiles,
            "shares": luminance_shares,
        },
        "histograms": {"luminance_lstar": luminance_histogram},
        "contrast": contrast,
        "tone_signature": tone_signature,
        "chroma": chroma_result,
        "hue_distribution": hue_distribution,
        "neutral_axis": neutral_axis,
        "palettes": {
            "neutral_tone_palette": neutral_tone_palette,
            "scene_palette": scene_palette,
        },
        "subject_background": subject_background,
        "confidence": confidence,
        "summary_zh": _summary_zh(
            luminance_percentiles,
            contrast,
            chroma_percentiles,
            neutral_axis,
        ),
        "performance": {
            "quantitative_runtime_ms": round(
                (time.perf_counter() - started) * 1000.0, 3
            ),
            "image_max_side": int(max(rgb.shape[:2])),
            "valid_pixel_count": valid_count,
            "scene_palette_sample_count": scene_palette["sample_count"],
            "local_contrast_kernel_px": local_contrast["kernel_px"],
        },
    }
    color_dna = _color_dna(
        luminance_percentiles,
        contrast,
        tone_signature,
        chroma_percentiles,
        neutral_axis,
        subject_background,
        confidence,
    )
    return QuantitativeResult(quantitative=quantitative, color_dna=color_dna)


def _validate_inputs(rgb: np.ndarray, lab: np.ndarray, valid_mask: np.ndarray) -> None:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or lab.shape != rgb.shape:
        raise ValueError("Quantitative分析需要同尺寸RGB与Lab三通道图像")
    if valid_mask.shape != rgb.shape[:2]:
        raise ValueError("Quantitative透明像素掩膜尺寸不一致")
    if int(valid_mask.sum()) < 100:
        raise ValueError("Quantitative有效像素过少")
    if not np.isfinite(lab[valid_mask]).all():
        raise ValueError("Quantitative输入包含无效Lab像素")


def _prepare_quantitative_subject(
    rgb: np.ndarray,
    lab: np.ndarray,
    valid_mask: np.ndarray,
    subject: SubjectRegion,
) -> tuple[SubjectRegion, np.ndarray, dict]:
    """Refine only face-based quantitative ROI; retain the original exclusion.

    The original region remains the background exclusion so hair and nearby face
    pixels cannot leak into background statistics. If the conservative face-core
    skin mask is too small, quantitative ROI fails closed instead of reverting to
    the contaminated rectangular face region.
    """

    original = subject.mask & valid_mask
    valid_count = int(valid_mask.sum())
    region_count = int(original.sum())
    if subject.kind == "main_subject":
        refined = _main_subject_foreground(rgb, original, subject.box)
        refined_count = int(refined.sum())
        minimum = max(64, _minimum_sample_count(valid_count))
        if refined_count >= minimum:
            return (
                SubjectRegion(subject.kind, subject.box, refined),
                original,
                {
                    "mask_method": "main_subject_grabcut",
                    "pixel_share": round(refined_count / max(valid_count, 1), 8),
                    "region_pixel_share": round(
                        refined_count / max(region_count, 1), 8
                    ),
                },
            )
    if subject.kind != "face":
        return (
            SubjectRegion(subject.kind, subject.box, original),
            original,
            {
                "mask_method": "region_mask",
                "pixel_share": round(region_count / max(valid_count, 1), 8),
                "region_pixel_share": 1.0 if region_count else 0.0,
            },
        )

    x, y, width, height = subject.box
    core = np.zeros_like(valid_mask, dtype=np.uint8)
    center = (x + width // 2, y + round(height * 0.52))
    axes = (max(1, round(width * 0.36)), max(1, round(height * 0.39)))
    cv2.ellipse(core, center, axes, 0, 0, 360, 1, -1)
    candidates = (
        core.astype(bool) & original & skin_candidate_mask(rgb, lab, valid_mask)
    )
    if int(candidates.sum()):
        values = lab[candidates]
        median = np.median(values, axis=0)
        mad = np.median(np.abs(values - median), axis=0)
        limits = np.maximum(3.0 * mad, np.array([18.0, 8.0, 8.0]))
        robust = np.all(np.abs(lab - median) <= limits, axis=2)
        candidates &= robust

    minimum = max(64, _minimum_sample_count(valid_count))
    sample_count = int(candidates.sum())
    sufficient = sample_count >= minimum
    refined = candidates if sufficient else np.zeros_like(valid_mask, dtype=bool)
    diagnostics = {
        "mask_method": (
            "face_core_skin_mask" if sufficient else "face_core_skin_mask_insufficient"
        ),
        "pixel_share": round(sample_count / max(valid_count, 1), 8),
        "region_pixel_share": round(sample_count / max(region_count, 1), 8),
    }
    return SubjectRegion(subject.kind, subject.box, refined), original, diagnostics


def _main_subject_foreground(
    rgb: np.ndarray,
    region_mask: np.ndarray,
    box: tuple[int, int, int, int],
) -> np.ndarray:
    """Conservatively remove obvious background from main-subject fallback."""

    height, width = region_mask.shape
    scale = min(1.0, 640.0 / max(height, width))
    small_size = (max(2, round(width * scale)), max(2, round(height * scale)))
    small_rgb = cv2.resize(rgb, small_size, interpolation=cv2.INTER_AREA)
    x, y, box_width, box_height = box
    rect = (
        max(1, round(x * scale)),
        max(1, round(y * scale)),
        min(small_size[0] - 2, max(1, round(box_width * scale))),
        min(small_size[1] - 2, max(1, round(box_height * scale))),
    )
    rect = (
        min(rect[0], small_size[0] - 2),
        min(rect[1], small_size[1] - 2),
        min(rect[2], small_size[0] - rect[0] - 1),
        min(rect[3], small_size[1] - rect[1] - 1),
    )
    if rect[2] < 2 or rect[3] < 2:
        return np.zeros_like(region_mask, dtype=bool)
    grabcut_mask = np.zeros(small_rgb.shape[:2], dtype=np.uint8)
    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)
    try:
        cv2.setRNGSeed(MAIN_SUBJECT_GRABCUT_SEED)
        cv2.grabCut(
            small_rgb,
            grabcut_mask,
            rect,
            background_model,
            foreground_model,
            3,
            cv2.GC_INIT_WITH_RECT,
        )
    except cv2.error:
        return np.zeros_like(region_mask, dtype=bool)
    foreground = np.isin(grabcut_mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    if component_count <= 1:
        return np.zeros_like(region_mask, dtype=bool)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    foreground = (labels == largest).astype(np.uint8)
    foreground = cv2.resize(
        foreground, (width, height), interpolation=cv2.INTER_NEAREST
    ).astype(bool)
    return foreground & region_mask


def _percentiles(values: np.ndarray, percentiles: tuple[int, ...]) -> dict[str, float]:
    measured = np.percentile(values, percentiles)
    return {
        f"p{percentile}": _round(value)
        for percentile, value in zip(percentiles, measured)
    }


def _share(condition: np.ndarray) -> float:
    return round(float(np.mean(condition)) if condition.size else 0.0, 8)


def _normalized_histogram(
    values: np.ndarray,
    *,
    bins: int,
    value_range: tuple[float, float],
    denominator: int | None = None,
) -> dict:
    counts, edges = np.histogram(values, bins=bins, range=value_range)
    total = int(denominator if denominator is not None else values.size)
    normalized = counts.astype(np.float64) / max(total, 1)
    return {
        "range": [value_range[0], value_range[1]],
        "bins": bins,
        "bin_edges": [_round(value, 6) for value in edges],
        "normalized": [_round(value, 10) for value in normalized],
    }


def _local_contrast(
    lstar: np.ndarray,
    valid_mask: np.ndarray,
    subject: SubjectRegion,
    *,
    background_exclusion: np.ndarray,
) -> dict:
    short_side = min(lstar.shape)
    kernel = max(15, min(61, round(short_side * 0.03)))
    if kernel % 2 == 0:
        kernel += 1
    kernel = min(kernel, 61)
    mask_float = valid_mask.astype(np.float32)
    l_float = lstar.astype(np.float32)
    area = float(kernel * kernel)
    count = cv2.boxFilter(
        mask_float,
        cv2.CV_32F,
        (kernel, kernel),
        normalize=False,
        borderType=cv2.BORDER_CONSTANT,
    )
    sum_l = cv2.boxFilter(
        l_float * mask_float,
        cv2.CV_32F,
        (kernel, kernel),
        normalize=False,
        borderType=cv2.BORDER_CONSTANT,
    )
    sum_l2 = cv2.boxFilter(
        l_float * l_float * mask_float,
        cv2.CV_32F,
        (kernel, kernel),
        normalize=False,
        borderType=cv2.BORDER_CONSTANT,
    )
    valid_window = count >= area - 0.5
    mean = sum_l / np.maximum(count, 1.0)
    variance = np.maximum(sum_l2 / np.maximum(count, 1.0) - mean * mean, 0.0)
    local_std = np.sqrt(variance)
    values = local_std[valid_window]
    result = {
        "kernel_px": kernel,
        "local_contrast_median": _optional_percentile(values, 50),
        "local_contrast_p75": _optional_percentile(values, 75),
        "subject_local_contrast_median": None,
        "background_local_contrast_median": None,
    }
    subject_values = local_std[valid_window & subject.mask & valid_mask]
    if subject_values.size >= 32:
        result["subject_local_contrast_median"] = _round(np.median(subject_values))
    margin = _dilate(
        background_exclusion,
        max(1, round(short_side * SUBJECT_BACKGROUND_MARGIN_SHARE)),
    )
    background_values = local_std[valid_window & valid_mask & ~margin]
    if background_values.size >= 32:
        result["background_local_contrast_median"] = _round(
            np.median(background_values)
        )
    return result


def _tone_signature(percentiles: dict[str, float]) -> dict:
    midtone = max(percentiles["p75"] - percentiles["p25"], EPSILON)
    toe_ratio = (percentiles["p25"] - percentiles["p5"]) / midtone
    shoulder_ratio = (percentiles["p95"] - percentiles["p75"]) / midtone
    return {
        "black_floor_p1": percentiles["p1"],
        "shadow_floor_p5": percentiles["p5"],
        "highlight_ceiling_p99": percentiles["p99"],
        "highlight_headroom": _round(100.0 - percentiles["p95"]),
        "midtone_spread": _round(percentiles["p75"] - percentiles["p25"]),
        "toe_ratio": _round(toe_ratio),
        "shoulder_ratio": _round(shoulder_ratio),
        "toe_state": _tone_span_state(toe_ratio),
        "shoulder_state": _tone_span_state(shoulder_ratio),
    }


def _tone_span_state(ratio: float) -> str:
    if ratio < TONE_SPAN_NEUTRAL_MIN:
        return "compressed"
    if ratio <= TONE_SPAN_NEUTRAL_MAX:
        return "neutral"
    return "expanded"


def _hue_distribution(
    lstar: np.ndarray,
    astar: np.ndarray,
    bstar: np.ndarray,
    chroma: np.ndarray,
    valid_mask: np.ndarray,
) -> dict:
    eligible = (
        valid_mask
        & (chroma >= HUE_ELIGIBLE_CHROMA_MIN)
        & (lstar > HUE_ELIGIBLE_L_MIN)
        & (lstar < HUE_ELIGIBLE_L_MAX)
    )
    hue = (np.degrees(np.arctan2(bstar[eligible], astar[eligible])) + 360.0) % 360.0
    eligible_chroma = chroma[eligible]
    counts, _ = np.histogram(hue, bins=12, range=(0.0, 360.0))
    weighted, _ = np.histogram(
        hue, bins=12, range=(0.0, 360.0), weights=eligible_chroma
    )
    total_count = int(counts.sum())
    total_weight = float(weighted.sum())
    area = counts / max(total_count, 1)
    chroma_weighted = weighted / max(total_weight, EPSILON)
    sectors = [
        {
            "index": index,
            "label": HUE_LABELS[index],
            "start_degree": index * 30,
            "end_degree": (index + 1) * 30,
            "area_share": _round(area[index], 8),
            "chroma_weighted_share": _round(chroma_weighted[index], 8),
        }
        for index in range(12)
    ]
    order = sorted(range(12), key=lambda index: (-chroma_weighted[index], index))
    names = [HUE_LABELS[index] for index in order if weighted[index] > 0]
    return {
        "eligible_pixel_share": round(
            float(eligible.sum() / max(valid_mask.sum(), 1)), 8
        ),
        "eligible_pixel_count": int(eligible.sum()),
        "dominant_hue": names[0] if names else None,
        "secondary_hue": names[1] if len(names) > 1 else None,
        "accent_hue": names[2] if len(names) > 2 else None,
        "hue_concentration": _round(chroma_weighted[order[0]], 8) if names else 0.0,
        "concentration_definition": "dominant_chroma_weighted_share",
        "sectors": sectors,
    }


def _neutral_axis(
    lstar: np.ndarray,
    astar: np.ndarray,
    bstar: np.ndarray,
    chroma: np.ndarray,
    valid_mask: np.ndarray,
    *,
    subject_mask: np.ndarray,
    background_exclusion: np.ndarray,
) -> tuple[dict, np.ndarray]:
    neutral = (
        valid_mask
        & (chroma <= NEUTRAL_CHROMA_MAX)
        & (lstar >= NEUTRAL_L_MIN)
        & (lstar <= NEUTRAL_L_MAX)
    )
    valid_count = int(valid_mask.sum())
    minimum = _minimum_sample_count(valid_count)
    coverage, concentration, active_tiles = _neutral_spatial_diagnostics(
        neutral, valid_mask
    )
    subject_valid = subject_mask & valid_mask
    background_valid = valid_mask & ~_dilate(
        background_exclusion,
        max(1, round(min(valid_mask.shape) * SUBJECT_BACKGROUND_MARGIN_SHARE)),
    )
    subject_share = _masked_share(neutral, subject_valid)
    background_share = _masked_share(neutral, background_valid)
    result = {
        "candidate_definition": {
            "c_max": NEUTRAL_CHROMA_MAX,
            "l_min": NEUTRAL_L_MIN,
            "l_max": NEUTRAL_L_MAX,
        },
        "neutral_pixel_share": round(float(neutral.sum() / valid_count), 8),
        "neutral_spatial_coverage": coverage,
        "subject_neutral_share": subject_share,
        "background_neutral_share": background_share,
        "neutral_spatial_concentration": concentration,
        "neutral_active_tile_count": active_tiles,
        "neutral_a_mad": None,
        "neutral_b_mad": None,
        "neutral_confidence": 0.0,
        "validity_reason": "insufficient_neutral_samples",
        "overall": _axis_segment(astar, bstar, chroma, neutral, valid_count, minimum),
        "segments": {},
    }
    for name, low, high in NEUTRAL_RANGES:
        segment = neutral & (lstar >= low) & (lstar < high)
        result["segments"][name] = _axis_segment(
            astar, bstar, chroma, segment, valid_count, minimum
        )
    if int(neutral.sum()) >= minimum:
        a_mad = float(np.median(np.abs(astar[neutral] - np.median(astar[neutral]))))
        b_mad = float(np.median(np.abs(bstar[neutral] - np.median(bstar[neutral]))))
        result["neutral_a_mad"] = _round(a_mad)
        result["neutral_b_mad"] = _round(b_mad)
        segment_score = sum(
            item["status"] == "valid" for item in result["segments"].values()
        ) / len(NEUTRAL_RANGES)
        available_region_shares = [
            value for value in (subject_share, background_share) if value is not None
        ]
        region_score = (
            sum(
                _scaled_score(value, *NEUTRAL_REGION_SHARE_SCORE_RANGE)
                for value in available_region_shares
            )
            / len(available_region_shares)
            if available_region_shares
            else 0.0
        )
        dispersion = math.hypot(a_mad, b_mad)
        score = (
            0.35
            * _scaled_score(result["neutral_pixel_share"], *NEUTRAL_SHARE_SCORE_RANGE)
            + 0.15 * _scaled_score(coverage, *NEUTRAL_COVERAGE_SCORE_RANGE)
            + 0.20 * region_score
            + 0.10 * segment_score
            + 0.10 * _scaled_score(concentration, *NEUTRAL_CONCENTRATION_SCORE_RANGE)
            + 0.10 * _scaled_score(dispersion, *NEUTRAL_DISPERSION_SCORE_RANGE)
        )
        result["neutral_confidence"] = _round(score, 6)
        if score >= NEUTRAL_CONFIDENCE_VALID_MIN:
            result["validity_reason"] = "multi_evidence_valid"
        else:
            result["overall"]["status"] = "low_confidence"
            result["validity_reason"] = "multi_evidence_low_confidence"
    return result, neutral


def _axis_segment(
    astar: np.ndarray,
    bstar: np.ndarray,
    chroma: np.ndarray,
    mask: np.ndarray,
    valid_count: int,
    minimum: int,
) -> dict:
    count = int(mask.sum())
    base = {
        "status": "valid" if count >= minimum else "insufficient",
        "sample_share": round(count / max(valid_count, 1), 8),
        "sample_count": count,
        "a_median": None,
        "b_median": None,
        "c_median": None,
    }
    if count >= minimum:
        base.update(
            {
                "a_median": _round(np.median(astar[mask])),
                "b_median": _round(np.median(bstar[mask])),
                "c_median": _round(np.median(chroma[mask])),
            }
        )
    return base


def _neutral_spatial_diagnostics(
    neutral: np.ndarray, valid_mask: np.ndarray
) -> tuple[float, float, int]:
    height, width = neutral.shape
    qualified = 0
    considered = 0
    tile_neutral_counts: list[int] = []
    for row in range(NEUTRAL_GRID_SIZE):
        y1, y2 = (
            row * height // NEUTRAL_GRID_SIZE,
            (row + 1) * height // NEUTRAL_GRID_SIZE,
        )
        for column in range(NEUTRAL_GRID_SIZE):
            x1 = column * width // NEUTRAL_GRID_SIZE
            x2 = (column + 1) * width // NEUTRAL_GRID_SIZE
            tile_valid = valid_mask[y1:y2, x1:x2]
            count = int(tile_valid.sum())
            if count < 32:
                continue
            considered += 1
            tile_neutral = int(neutral[y1:y2, x1:x2][tile_valid].sum())
            tile_neutral_counts.append(tile_neutral)
            if tile_neutral / count >= 0.01:
                qualified += 1
    total_neutral = sum(tile_neutral_counts)
    concentration = (
        max(tile_neutral_counts, default=0) / total_neutral if total_neutral else 1.0
    )
    active_tiles = sum(count > 0 for count in tile_neutral_counts)
    return (
        round(qualified / max(considered, 1), 8),
        round(concentration, 8),
        active_tiles,
    )


def _masked_share(target: np.ndarray, region: np.ndarray) -> float | None:
    count = int(region.sum())
    if count < 64:
        return None
    return round(float(target[region].mean()), 8)


def _scaled_score(value: float, low: float, high: float) -> float:
    if low == high:
        return 1.0 if value >= high else 0.0
    scaled = (value - low) / (high - low)
    return min(1.0, max(0.0, scaled))


def _neutral_tone_palette(
    rgb: np.ndarray,
    lab: np.ndarray,
    lstar: np.ndarray,
    neutral_mask: np.ndarray,
    valid_count: int,
) -> list[dict]:
    minimum = _minimum_sample_count(valid_count)
    result: list[dict] = []
    for role, low, high in NEUTRAL_TONE_BANDS:
        mask = neutral_mask & (lstar >= low) & (lstar < high)
        count = int(mask.sum())
        item = {
            "role": role,
            "status": "valid" if count >= minimum else "insufficient",
            "pixel_share": round(count / max(valid_count, 1), 8),
            "sample_count": count,
            "rgb": None,
            "hex": None,
            "lab": None,
        }
        if count >= minimum:
            rgb_value = np.rint(np.median(rgb[mask], axis=0)).astype(int).tolist()
            lab_value = np.median(lab[mask], axis=0)
            item.update(
                {
                    "rgb": rgb_value,
                    "hex": _hex(rgb_value),
                    "lab": _lab_dict(lab_value),
                }
            )
        result.append(item)
    return result


def _scene_palette(rgb: np.ndarray, lab: np.ndarray, valid_mask: np.ndarray) -> dict:
    flat_lab = lab[valid_mask].astype(np.float64, copy=False)
    valid_count = flat_lab.shape[0]
    rng = np.random.default_rng(SCENE_PALETTE_SEED)
    if valid_count > SCENE_PALETTE_MAX_SAMPLES:
        ids = rng.choice(valid_count, SCENE_PALETTE_MAX_SAMPLES, replace=False)
        samples = flat_lab[ids]
    else:
        samples = flat_lab
    rounded_unique = np.unique(np.round(samples, 4), axis=0)
    cluster_count = min(SCENE_PALETTE_CLUSTERS, len(rounded_unique))
    if cluster_count == 0:
        return {
            "status": "insufficient",
            "sample_count": 0,
            "clusters": [],
            "roles": {},
        }
    model = MiniBatchKMeans(
        n_clusters=cluster_count,
        random_state=SCENE_PALETTE_SEED,
        n_init=5,
        batch_size=2048,
        reassignment_ratio=0.0,
    )
    model.fit(samples)
    labels = model.predict(flat_lab)
    counts = np.bincount(labels, minlength=cluster_count)
    clusters = [
        {
            "lab_array": model.cluster_centers_[index].astype(np.float64),
            "area_share": float(counts[index] / max(valid_count, 1)),
        }
        for index in range(cluster_count)
        if counts[index] > 0
    ]
    clusters = _merge_clusters(clusters)
    clusters.sort(key=lambda item: (-item["area_share"], tuple(item["lab_array"])))
    roles = _assign_palette_roles(clusters)
    formatted = []
    for index, cluster in enumerate(clusters):
        lab_value = cluster["lab_array"]
        rgb_value = _lab_to_rgb(lab_value)
        formatted.append(
            {
                "id": f"cluster_{index + 1}",
                "role": roles.get(index, "other"),
                "role_display_name": PALETTE_ROLE_DISPLAY[roles.get(index, "other")],
                "area_share": _round(cluster["area_share"], 8),
                "lab": _lab_dict(lab_value),
                "rgb": rgb_value,
                "hex": _hex(rgb_value),
                "chroma": _round(math.hypot(lab_value[1], lab_value[2])),
                "hue_angle": _round(
                    (math.degrees(math.atan2(lab_value[2], lab_value[1])) + 360.0)
                    % 360.0
                ),
            }
        )
    role_map = {
        role: formatted[index]["id"]
        for index, role in roles.items()
        if role in {"primary", "secondary", "accent"}
    }
    return {
        "status": "valid",
        "method": "deterministic_minibatch_kmeans_lab",
        "seed": SCENE_PALETTE_SEED,
        "max_samples": SCENE_PALETTE_MAX_SAMPLES,
        "sample_count": int(samples.shape[0]),
        "merge_delta_e00": SCENE_CLUSTER_MERGE_DELTA_E00,
        "clusters": formatted,
        "roles": role_map,
    }


def _merge_clusters(clusters: list[dict]) -> list[dict]:
    pending = sorted(clusters, key=lambda item: -item["area_share"])
    merged: list[dict] = []
    for cluster in pending:
        target = None
        for existing in merged:
            if (
                _delta_e(cluster["lab_array"], existing["lab_array"])
                < SCENE_CLUSTER_MERGE_DELTA_E00
            ):
                target = existing
                break
        if target is None:
            merged.append(
                {
                    "lab_array": cluster["lab_array"].copy(),
                    "area_share": cluster["area_share"],
                }
            )
            continue
        combined = target["area_share"] + cluster["area_share"]
        target["lab_array"] = (
            target["lab_array"] * target["area_share"]
            + cluster["lab_array"] * cluster["area_share"]
        ) / combined
        target["area_share"] = combined
    return merged


def _assign_palette_roles(clusters: list[dict]) -> dict[int, str]:
    if not clusters:
        return {}
    roles: dict[int, str] = {0: "primary"}
    primary = clusters[0]["lab_array"]
    secondary_candidates = [
        index
        for index in range(1, len(clusters))
        if _delta_e(primary, clusters[index]["lab_array"]) >= 8.0
    ]
    if secondary_candidates:
        roles[secondary_candidates[0]] = "secondary"
    accent_candidates = []
    for index in range(1, len(clusters)):
        if roles.get(index) == "secondary":
            continue
        value = clusters[index]
        chroma = math.hypot(value["lab_array"][1], value["lab_array"][2])
        delta = _delta_e(primary, value["lab_array"])
        if 0.005 <= value["area_share"] <= 0.20 and chroma >= 30.0 and delta >= 15.0:
            accent_candidates.append((chroma * delta, index))
    if accent_candidates:
        _, index = max(accent_candidates, key=lambda item: (item[0], -item[1]))
        roles[index] = "accent"
    return roles


def _subject_background(
    lab: np.ndarray,
    lstar: np.ndarray,
    chroma: np.ndarray,
    valid_mask: np.ndarray,
    subject: SubjectRegion,
    *,
    background_exclusion: np.ndarray,
    diagnostics: dict,
) -> dict:
    subject_mask = subject.mask & valid_mask
    margin = _dilate(
        background_exclusion,
        max(1, round(min(valid_mask.shape) * SUBJECT_BACKGROUND_MARGIN_SHARE)),
    )
    background_mask = valid_mask & ~margin
    valid_count = int(valid_mask.sum())
    minimum = max(64, _minimum_sample_count(valid_count))
    base = {
        "status": "insufficient",
        "roi": {
            "type": subject.kind,
            "box": list(subject.box),
            **diagnostics,
        },
        "subject": None,
        "background": None,
        "delta_l": None,
        "delta_c": None,
        "delta_e00": None,
    }
    if int(subject_mask.sum()) < minimum or int(background_mask.sum()) < minimum:
        return base
    subject_stats = _region_stats(lab, lstar, chroma, subject_mask, valid_count)
    background_stats = _region_stats(lab, lstar, chroma, background_mask, valid_count)
    subject_lab = np.array(
        [subject_stats["lab_median"][key] for key in ("l", "a", "b")], dtype=float
    )
    background_lab = np.array(
        [background_stats["lab_median"][key] for key in ("l", "a", "b")], dtype=float
    )
    base.update(
        {
            "status": "valid",
            "subject": subject_stats,
            "background": background_stats,
            "delta_l": _round(subject_stats["l_p50"] - background_stats["l_p50"]),
            "delta_c": _round(subject_stats["c_p50"] - background_stats["c_p50"]),
            "delta_e00": _round(_delta_e(subject_lab, background_lab)),
        }
    )
    return base


def _region_stats(
    lab: np.ndarray,
    lstar: np.ndarray,
    chroma: np.ndarray,
    mask: np.ndarray,
    valid_count: int,
) -> dict:
    median_lab = np.median(lab[mask], axis=0)
    return {
        "sample_count": int(mask.sum()),
        "sample_share": round(float(mask.sum() / max(valid_count, 1)), 8),
        "l_p50": _round(np.median(lstar[mask])),
        "lab_median": _lab_dict(median_lab),
        "c_p50": _round(np.median(chroma[mask])),
    }


def _confidence_summary(lighting: dict, material_effects: dict) -> dict:
    classifiers = lighting.get("debug", {}).get("classifiers", {})
    lighting_confidence = {
        name: _nullable_confidence(classifiers.get(name, {}).get("confidence"))
        for name in ("source", "quality", "ratio")
    }
    effects = [
        {
            "name": item.get("display_name"),
            "confidence": _nullable_confidence(item.get("confidence")),
        }
        for item in material_effects.get("items", [])
        if isinstance(item, dict) and item.get("display_name")
    ]
    return {"lighting": lighting_confidence, "material_fx": effects}


def _color_dna(
    luminance: dict,
    contrast: dict,
    tone: dict,
    chroma: dict,
    neutral: dict,
    subject_background: dict,
    confidence: dict,
) -> dict:
    overall = neutral["overall"]
    lighting_values = [
        value for value in confidence["lighting"].values() if value is not None
    ]
    material_values = [
        item["confidence"]
        for item in confidence["material_fx"]
        if item["confidence"] is not None
    ]
    return {
        "L50": luminance["p50"],
        "L95_minus_L5": contrast["global_l_p95_p5"],
        "L75_minus_L25": contrast["midtone_l_p75_p25"],
        "black_floor_p1": tone["black_floor_p1"],
        "highlight_headroom": tone["highlight_headroom"],
        "C50": chroma["p50"],
        "C90": chroma["p90"],
        "neutral_a": overall["a_median"],
        "neutral_b": overall["b_median"],
        "neutral_share": neutral["neutral_pixel_share"],
        "neutral_coverage": neutral["neutral_spatial_coverage"],
        "toe_ratio": tone["toe_ratio"],
        "shoulder_ratio": tone["shoulder_ratio"],
        "subject_background_delta_l": subject_background["delta_l"],
        "subject_background_delta_e00": subject_background["delta_e00"],
        "lighting_confidence": _round(min(lighting_values), 6)
        if lighting_values
        else None,
        "material_fx_confidence_max": _round(max(material_values), 6)
        if material_values
        else None,
    }


def _summary_zh(
    luminance: dict,
    contrast: dict,
    chroma: dict,
    neutral: dict,
) -> str:
    l50 = luminance["p50"]
    global_contrast = contrast["global_l_p95_p5"]
    midtone_contrast = contrast["midtone_l_p75_p25"]
    c50 = chroma["p50"]
    l_description = (
        "全局画面像素中位明度偏暗"
        if l50 < 42
        else "全局画面像素中位明度偏亮"
        if l50 > 58
        else "全局画面像素中位明度居中"
    )
    contrast_description = (
        "全局反差较大"
        if global_contrast >= 65
        else "全局反差适中"
        if global_contrast >= 42
        else "全局反差较小"
    )
    chroma_description = (
        "综合色度较高" if c50 >= 30 else "综合色度中等" if c50 >= 10 else "综合色度较低"
    )
    overall = neutral["overall"]
    if overall["status"] == "insufficient":
        neutral_description = "中性色样本不足"
    elif overall["status"] == "low_confidence":
        neutral_description = "中性色轴置信度较低"
    else:
        a_value = overall["a_median"]
        b_value = overall["b_median"]
        neutral_description = f"中性色轴为 a* {a_value:+.2f} / b* {b_value:+.2f}"
    return (
        f"全局 L* P50 = {l50:.2f}，Global Contrast = {global_contrast:.2f} L*，"
        f"Midtone Contrast = {midtone_contrast:.2f} L*，C* P50 = {c50:.2f}。"
        f"{l_description}，{contrast_description}；{chroma_description}，{neutral_description}。"
    )


def _minimum_sample_count(valid_count: int) -> int:
    return max(32, min(512, math.ceil(valid_count * 0.0005)))


def _optional_percentile(values: np.ndarray, percentile: int) -> float | None:
    return _round(np.percentile(values, percentile)) if values.size else None


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    size = max(3, radius * 2 + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    return cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)


def _lab_to_rgb(lab_value: np.ndarray) -> list[int]:
    converted = lab2rgb(np.asarray(lab_value, dtype=float).reshape(1, 1, 3))[0, 0]
    return np.rint(np.clip(converted, 0.0, 1.0) * 255.0).astype(int).tolist()


def _lab_dict(value: np.ndarray) -> dict[str, float]:
    return {"l": _round(value[0]), "a": _round(value[1]), "b": _round(value[2])}


def _hex(rgb: list[int]) -> str:
    return "#" + "".join(f"{value:02X}" for value in rgb)


def _delta_e(left: np.ndarray, right: np.ndarray) -> float:
    value = deltaE_ciede2000(
        np.asarray(left, dtype=float).reshape(1, 1, 3),
        np.asarray(right, dtype=float).reshape(1, 1, 3),
    )[0, 0]
    return float(value)


def _nullable_confidence(value) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return min(1.0, max(0.0, round(float(value), 6)))
    return None


def _round(value, digits: int = 4) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Quantitative指标不得包含NaN或Infinity")
    rounded = round(number, digits)
    return 0.0 if rounded == 0 else rounded
