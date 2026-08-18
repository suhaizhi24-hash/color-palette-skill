from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import cv2
import numpy as np


LIGHTING_RULESET_VERSION = "lighting-0.14.0"

SOURCE_DISPLAY = {
    "natural": "自然光",
    "studio": "人工棚拍",
    "flash": "人工闪光",
    "mixed": "混合光",
    "self_luminous": "自发光",
    "unknown": "暂不判定",
}
QUALITY_DISPLAY = {
    "hard": "硬光",
    "soft": "柔光",
    "not_applicable": "不适用",
    "unknown": "暂不判定",
}
RATIO_DISPLAY = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "not_applicable": "不适用",
    "unknown": "暂不判定",
}


@dataclass(frozen=True)
class SourceFeatures:
    scene_dark_share: float
    scene_highlight_share: float
    background_uniformity: float
    subject_background_ev: float
    subject_separation: float
    chromatic_spread: float
    environment_texture: float
    bright_component_count: int
    bright_component_share: float
    subject_valid_share: float
    color_temperature_proxy: float


@dataclass(frozen=True)
class QualityFeatures:
    subject_dynamic_range: float
    fine_edge_strength: float
    coarse_edge_strength: float
    edge_sharpness: float
    localized_highlight: float
    valid_share: float


@dataclass(frozen=True)
class RatioFeatures:
    light_level: float
    shadow_level: float
    delta_ev: float
    subject_dynamic_range: float
    spatial_coherence: float
    lit_area_share: float
    shadow_area_share: float
    valid_share: float


@dataclass(frozen=True)
class SubjectRegion:
    kind: str
    box: tuple[int, int, int, int]
    mask: np.ndarray


def classify_source(features: SourceFeatures) -> str:
    """Classify source from scene/subject evidence only.

    Deliberately does not accept quality or ratio. The colour-temperature proxy
    is recorded for QA but is not used as a deciding signal because processed
    photographs may contain white-balance, LUT, HSL, or curve changes.
    """

    self_luminous_score = (
        0.48 * _ramp(features.scene_dark_share, 0.58, 0.88)
        + 0.24 * _band(features.bright_component_share, 0.0005, 0.18)
        + 0.16 * _ramp(float(features.bright_component_count), 0.0, 3.0)
        + 0.12 * _ramp(features.subject_background_ev, 0.8, 2.5)
    )
    if self_luminous_score >= 0.68 and features.scene_highlight_share <= 0.22:
        return "self_luminous"

    flash_score = (
        0.35 * _ramp(features.scene_dark_share, 0.30, 0.72)
        + 0.30 * _ramp(features.subject_background_ev, 0.65, 2.1)
        + 0.20 * _ramp(features.subject_separation, 0.10, 0.45)
        + 0.15 * _ramp(features.scene_highlight_share, 0.008, 0.09)
    )
    mixed_score = (
        0.62 * flash_score
        + 0.25 * _ramp(features.chromatic_spread, 0.16, 0.52)
        + 0.13 * _ramp(features.environment_texture, 0.08, 0.32)
    )
    if mixed_score >= 0.66 and features.chromatic_spread >= 0.20:
        return "mixed"
    if flash_score >= 0.70:
        return "flash"

    studio_score = (
        0.48 * _ramp(features.background_uniformity, 0.55, 0.91)
        + 0.30 * _ramp(features.subject_separation, 0.07, 0.35)
        + 0.22 * (1.0 - _ramp(features.environment_texture, 0.10, 0.32))
    )
    if studio_score >= 0.65 and features.subject_valid_share >= 0.08:
        return "studio"

    natural_score = (
        0.42 * _ramp(features.environment_texture, 0.06, 0.30)
        + 0.30 * (1.0 - _ramp(features.background_uniformity, 0.62, 0.92))
        + 0.18 * (1.0 - _ramp(features.scene_dark_share, 0.55, 0.84))
        + 0.10 * _ramp(features.subject_valid_share, 0.10, 0.35)
    )
    if natural_score >= 0.50:
        return "natural"
    return "unknown"


def classify_quality(features: QualityFeatures) -> str:
    """Classify shadow-edge/penumbra structure inside the subject ROI."""

    if features.valid_share < 0.05 or features.subject_dynamic_range < 0.025:
        return "unknown"
    hard_structure = (
        features.subject_dynamic_range >= 0.16
        and features.fine_edge_strength >= 0.018
        and features.coarse_edge_strength >= 0.006
        and features.edge_sharpness >= 1.55
        and (
            features.localized_highlight >= 0.025
            or features.coarse_edge_strength >= 0.012
        )
    )
    if hard_structure:
        return "hard"
    soft_structure = (
        features.edge_sharpness <= 1.58
        and features.coarse_edge_strength >= 0.0005
        and features.subject_dynamic_range >= 0.04
    ) or (
        features.subject_dynamic_range < 0.16
        and features.fine_edge_strength < 0.032
        and features.coarse_edge_strength >= 0.0005
    )
    if soft_structure:
        return "soft"
    return "unknown"


def classify_ratio(features: RatioFeatures) -> str:
    """Classify lit-vs-shadow structure within one subject, never globally."""

    if features.valid_share < 0.05:
        return "unknown"
    if features.subject_dynamic_range < 0.045 or features.delta_ev < 0.42:
        return "low"
    balanced_regions = min(features.lit_area_share, features.shadow_area_share) >= 0.12
    if (
        features.delta_ev >= 1.18
        and features.subject_dynamic_range >= 0.22
        and features.spatial_coherence >= 0.14
        and balanced_regions
    ):
        return "high"
    if (
        features.delta_ev >= 0.58
        and features.subject_dynamic_range >= 0.10
        and features.spatial_coherence >= 0.08
        and balanced_regions
    ):
        return "medium"
    return "low"


def analyze_lighting(
    rgb: np.ndarray,
    valid_mask: np.ndarray,
    *,
    face_box: list[int] | tuple[int, int, int, int] | None = None,
) -> dict:
    """Return independent Light Source, Quality, and Ratio results.

    The debug section is machine-facing only. `official_report` exposes only
    the three Chinese display names.
    """

    _validate_inputs(rgb, valid_mask)
    subject = select_subject_region(valid_mask, face_box=face_box)
    luma = _linear_luma(rgb)
    source_features = extract_source_features(rgb, luma, valid_mask, subject)
    quality_features = extract_quality_features(luma, subject.mask, valid_mask)
    ratio_features = extract_ratio_features(luma, subject.mask, valid_mask)

    source = classify_source(source_features)
    if source == "self_luminous":
        quality = "not_applicable"
        ratio = "not_applicable"
    else:
        quality = classify_quality(quality_features)
        ratio = classify_ratio(ratio_features)

    return {
        "ruleset_version": LIGHTING_RULESET_VERSION,
        "source": {"code": source, "display_name": SOURCE_DISPLAY[source]},
        "quality": {"code": quality, "display_name": QUALITY_DISPLAY[quality]},
        "ratio": {"code": ratio, "display_name": RATIO_DISPLAY[ratio]},
        "subject_roi": {
            "type": subject.kind,
            "box": list(subject.box),
            "valid_share": round(float((subject.mask & valid_mask).sum() / max(valid_mask.sum(), 1)), 6),
        },
        "debug": {
            "source_features": _rounded(asdict(source_features)),
            "quality_features": _rounded(asdict(quality_features)),
            "ratio_features": _rounded(asdict(ratio_features)),
            "color_temperature_role": "auxiliary_only_not_decisive",
        },
    }


def legacy_light(lighting: dict) -> dict[str, str]:
    """Adapter retained for V0.12/V0.13 consumers of the old `light` object."""

    return {
        "source": lighting["source"]["display_name"],
        "quality": lighting["quality"]["display_name"],
        "ratio": lighting["ratio"]["display_name"],
        "status": "已分析",
    }


def visible_light(analysis: dict) -> dict[str, str]:
    """Prefer V0.14 structured results and safely render legacy JSON."""

    lighting = analysis.get("lighting")
    if isinstance(lighting, dict):
        try:
            return legacy_light(lighting)
        except (KeyError, TypeError):
            pass
    legacy = analysis.get("light")
    if isinstance(legacy, dict):
        return {
            "source": str(legacy.get("source", "暂不判定")),
            "quality": str(legacy.get("quality", "暂不判定")),
            "ratio": str(legacy.get("ratio", "暂不判定")),
            "status": str(legacy.get("status", "兼容旧版")),
        }
    return {
        "source": "暂不判定",
        "quality": "暂不判定",
        "ratio": "暂不判定",
        "status": "兼容旧版",
    }


def select_subject_region(
    valid_mask: np.ndarray,
    *,
    face_box: list[int] | tuple[int, int, int, int] | None = None,
) -> SubjectRegion:
    """Face → upper body → full body → main-subject deterministic fallback."""

    height, width = valid_mask.shape
    image_area = max(height * width, 1)
    if face_box and len(face_box) == 4:
        x, y, box_width, box_height = [int(value) for value in face_box]
        face_share = max(box_width, 0) * max(box_height, 0) / image_area
        if face_share >= 0.035:
            box = _clip_box(
                x - round(box_width * 0.10),
                y - round(box_height * 0.08),
                round(box_width * 1.20),
                round(box_height * 1.26),
                width,
                height,
            )
            kind = "face"
        elif face_share >= 0.012:
            box = _clip_box(
                x - round(box_width * 0.85),
                y - round(box_height * 0.15),
                round(box_width * 2.70),
                round(box_height * 3.30),
                width,
                height,
            )
            kind = "upper_body"
        else:
            box = _clip_box(
                x - round(box_width * 1.45),
                y - round(box_height * 0.25),
                round(box_width * 3.90),
                round(box_height * 7.00),
                width,
                height,
            )
            kind = "full_body"
    else:
        valid_y, valid_x = np.where(valid_mask)
        if valid_x.size:
            left, right = int(valid_x.min()), int(valid_x.max()) + 1
            top, bottom = int(valid_y.min()), int(valid_y.max()) + 1
        else:
            left, right, top, bottom = 0, width, 0, height
        span_x, span_y = max(right - left, 1), max(bottom - top, 1)
        box = _clip_box(
            left + round(span_x * 0.16),
            top + round(span_y * 0.10),
            round(span_x * 0.68),
            round(span_y * 0.82),
            width,
            height,
        )
        kind = "main_subject"

    x, y, box_width, box_height = box
    mask = np.zeros_like(valid_mask, dtype=bool)
    mask[y : y + box_height, x : x + box_width] = True
    mask &= valid_mask
    return SubjectRegion(kind=kind, box=box, mask=mask)


def extract_source_features(
    rgb: np.ndarray,
    luma: np.ndarray,
    valid_mask: np.ndarray,
    subject: SubjectRegion,
) -> SourceFeatures:
    height, width = valid_mask.shape
    subject_mask = subject.mask & valid_mask
    background_mask = valid_mask & ~subject_mask
    if int(background_mask.sum()) < 64:
        border = np.zeros_like(valid_mask)
        border_size_y = max(1, round(height * 0.12))
        border_size_x = max(1, round(width * 0.12))
        border[:border_size_y] = True
        border[-border_size_y:] = True
        border[:, :border_size_x] = True
        border[:, -border_size_x:] = True
        background_mask = border & valid_mask

    scene_values = luma[valid_mask]
    subject_values = luma[subject_mask]
    background_values = luma[background_mask]
    if not subject_values.size:
        subject_values = scene_values
    if not background_values.size:
        background_values = scene_values

    smooth = cv2.GaussianBlur(luma.astype(np.float32), (0, 0), 2.2)
    background_std = float(np.std(smooth[background_mask])) if background_mask.any() else 0.3
    background_uniformity = 1.0 - min(background_std / 0.22, 1.0)
    subject_median = float(np.median(subject_values))
    background_median = float(np.median(background_values))
    subject_background_ev = math.log2((subject_median + 0.025) / (background_median + 0.025))
    subject_separation = abs(subject_median - background_median)

    gray = np.clip(luma * 255.0, 0, 255).astype(np.uint8)
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(sobel_x, sobel_y) / 1020.0
    environment_texture = float(np.percentile(gradient[background_mask], 80)) if background_mask.any() else 0.0

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    tile_colours: list[np.ndarray] = []
    for row in range(3):
        y1, y2 = row * height // 3, (row + 1) * height // 3
        for column in range(3):
            x1, x2 = column * width // 3, (column + 1) * width // 3
            tile_mask = background_mask[y1:y2, x1:x2]
            if int(tile_mask.sum()) >= 32:
                tile_colours.append(np.median(lab[y1:y2, x1:x2][tile_mask, 1:3], axis=0))
    chromatic_spread = (
        float(np.mean(np.std(np.stack(tile_colours), axis=0)) / 64.0)
        if len(tile_colours) >= 2
        else 0.0
    )

    bright = (luma >= 0.78) & valid_mask
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        bright.astype(np.uint8), connectivity=8
    )
    meaningful = 0
    meaningful_area = 0
    min_area = max(4, round(valid_mask.sum() * 0.0004))
    for component in range(1, component_count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area >= min_area:
            meaningful += 1
            meaningful_area += area

    valid_rgb = rgb[valid_mask].astype(np.float32)
    red_blue_balance = (
        float(np.median(valid_rgb[:, 0] - valid_rgb[:, 2]) / 255.0)
        if valid_rgb.size
        else 0.0
    )
    return SourceFeatures(
        scene_dark_share=float(np.mean(scene_values <= 0.10)),
        scene_highlight_share=float(np.mean(scene_values >= 0.78)),
        background_uniformity=background_uniformity,
        subject_background_ev=subject_background_ev,
        subject_separation=subject_separation,
        chromatic_spread=chromatic_spread,
        environment_texture=environment_texture,
        bright_component_count=meaningful,
        bright_component_share=meaningful_area / max(int(valid_mask.sum()), 1),
        subject_valid_share=float(subject_mask.sum() / max(valid_mask.sum(), 1)),
        color_temperature_proxy=red_blue_balance,
    )


def extract_quality_features(
    luma: np.ndarray,
    subject_mask: np.ndarray,
    valid_mask: np.ndarray,
) -> QualityFeatures:
    mask = subject_mask & valid_mask
    values = luma[mask]
    valid_share = float(mask.sum() / max(valid_mask.sum(), 1))
    if values.size < 32:
        return QualityFeatures(0.0, 0.0, 0.0, 0.0, 0.0, valid_share)

    fine = cv2.GaussianBlur(luma.astype(np.float32), (0, 0), 1.0)
    coarse = cv2.GaussianBlur(luma.astype(np.float32), (0, 0), 4.5)
    fine_gradient = _gradient_magnitude(fine)
    coarse_gradient = _gradient_magnitude(coarse)
    # A narrow cast-shadow boundary may cover only one or two percent of a
    # subject ROI. The 99th percentile captures that penumbra without letting a
    # single hot pixel decide the result.
    fine_strength = float(np.percentile(fine_gradient[mask], 99))
    coarse_strength = float(np.percentile(coarse_gradient[mask], 99))
    dynamic = float(np.percentile(values, 90) - np.percentile(values, 10))
    localized_highlight = float(np.percentile(values, 99) - np.percentile(values, 85))
    return QualityFeatures(
        subject_dynamic_range=dynamic,
        fine_edge_strength=fine_strength,
        coarse_edge_strength=coarse_strength,
        edge_sharpness=fine_strength / max(coarse_strength, 1e-5),
        localized_highlight=localized_highlight,
        valid_share=valid_share,
    )


def extract_ratio_features(
    luma: np.ndarray,
    subject_mask: np.ndarray,
    valid_mask: np.ndarray,
) -> RatioFeatures:
    mask = subject_mask & valid_mask
    valid_share = float(mask.sum() / max(valid_mask.sum(), 1))
    if int(mask.sum()) < 32:
        return RatioFeatures(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, valid_share)

    sigma = max(2.0, min(luma.shape) * 0.018)
    illumination = cv2.GaussianBlur(luma.astype(np.float32), (0, 0), sigma)
    values = illumination[mask]
    light_level = float(np.percentile(values, 80))
    shadow_level = float(np.percentile(values, 20))
    dynamic = light_level - shadow_level
    delta_ev = math.log2((light_level + 0.025) / (shadow_level + 0.025))
    lit = mask & (illumination >= np.percentile(values, 65))
    shadow = mask & (illumination <= np.percentile(values, 35))
    lit_share = float(lit.sum() / max(mask.sum(), 1))
    shadow_share = float(shadow.sum() / max(mask.sum(), 1))
    coherence = min(_largest_component_share(lit), _largest_component_share(shadow))
    return RatioFeatures(
        light_level=light_level,
        shadow_level=shadow_level,
        delta_ev=delta_ev,
        subject_dynamic_range=dynamic,
        spatial_coherence=coherence,
        lit_area_share=lit_share,
        shadow_area_share=shadow_share,
        valid_share=valid_share,
    )


def _linear_luma(rgb: np.ndarray) -> np.ndarray:
    values = rgb.astype(np.float32) / 255.0
    linear = np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[..., 0] + 0.7152 * linear[..., 1] + 0.0722 * linear[..., 2]


def _gradient_magnitude(values: np.ndarray) -> np.ndarray:
    horizontal = cv2.Sobel(values, cv2.CV_32F, 1, 0, ksize=3)
    vertical = cv2.Sobel(values, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(horizontal, vertical) / 8.0


def _largest_component_share(mask: np.ndarray) -> float:
    count = int(mask.sum())
    if count == 0:
        return 0.0
    components, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    if components <= 1:
        return 0.0
    largest = max(int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, components))
    return largest / count


def _clip_box(
    x: int,
    y: int,
    width: int,
    height: int,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    left = max(0, min(int(x), max(image_width - 1, 0)))
    top = max(0, min(int(y), max(image_height - 1, 0)))
    right = max(left + 1, min(int(x + width), image_width))
    bottom = max(top + 1, min(int(y + height), image_height))
    return left, top, right - left, bottom - top


def _validate_inputs(rgb: np.ndarray, valid_mask: np.ndarray) -> None:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("光线分析需要uint8 RGB图像")
    if valid_mask.shape != rgb.shape[:2] or valid_mask.dtype != bool:
        raise ValueError("光线分析有效像素掩膜不匹配")
    if int(valid_mask.sum()) < 100:
        raise ValueError("光线分析有效像素过少")


def _ramp(value: float, low: float, high: float) -> float:
    if high <= low:
        return float(value >= high)
    return min(1.0, max(0.0, (value - low) / (high - low)))


def _band(value: float, low: float, high: float) -> float:
    if value < low or value > high:
        return 0.0
    midpoint = (low + high) / 2.0
    half = max((high - low) / 2.0, 1e-6)
    return 1.0 - 0.35 * abs(value - midpoint) / half


def _rounded(values: dict) -> dict:
    return {
        key: round(float(value), 6) if isinstance(value, float) else value
        for key, value in values.items()
    }
