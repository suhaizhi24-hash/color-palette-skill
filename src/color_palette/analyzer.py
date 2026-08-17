from __future__ import annotations

from pathlib import Path
import numpy as np
import cv2
from PIL import Image
from skimage.color import rgb2lab, rgb2hsv

from .colors import dominant_tonal_palette, hue_name
from .copy import official_report
from .faces import analyze_skin_anchors, detect_faces
from .io import LoadedImage, load_image
from .rules import (
    RULESET_VERSION,
    clipping_class,
    contrast_level,
    saturation_level,
    tone_code,
    white_balance_judgement,
)


def analyze(
    path: str | Path,
    *,
    max_side: int = 1600,
    analyze_faces: bool = True,
    include_palette: bool = True,
    face_backend: str | None = None,
) -> tuple[dict, LoadedImage, Image.Image]:
    loaded = load_image(path)
    source_rgb = loaded.rgb_image
    scale = min(1.0, max_side / max(source_rgb.size))
    working_size = (
        max(1, round(source_rgb.width * scale)),
        max(1, round(source_rgb.height * scale)),
    )
    working_image = source_rgb.resize(working_size, Image.Resampling.LANCZOS)
    rgb = np.asarray(working_image, dtype=np.uint8)
    rgb01 = rgb.astype(np.float32) / 255.0

    if loaded.valid_mask.shape != (source_rgb.height, source_rgb.width):
        raise ValueError("透明像素掩膜尺寸不一致")
    mask_image = Image.fromarray((loaded.valid_mask.astype(np.uint8) * 255), mode="L")
    working_mask = np.asarray(mask_image.resize(working_size, Image.Resampling.NEAREST)) > 0

    lab = rgb2lab(rgb01)
    hsv = rgb2hsv(rgb01)
    lightness = lab[..., 0]
    saturation = hsv[..., 1]
    valid_l = lightness[working_mask]
    valid_s = saturation[working_mask & (lightness > 8)]

    percentiles = {f"p{q}": round(float(np.percentile(valid_l, q)), 2) for q in [1, 5, 25, 50, 75, 95, 99]}
    shares = {
        "shadows": round(float(np.mean(valid_l < 35)), 6),
        "midtones": round(float(np.mean((valid_l >= 35) & (valid_l < 70))), 6),
        "highlights": round(float(np.mean(valid_l >= 70)), 6),
    }
    black_clip = round(float(np.mean(valid_l < 1)), 7)
    white_clip = round(float(np.mean(valid_l > 99)), 7)
    tone_key, tone_label = tone_code(shares, percentiles["p50"])

    span_l = round(percentiles["p95"] - percentiles["p5"], 2)
    contrast = contrast_level(span_l)
    contrast_description = {
        "低": "明暗过渡柔和，中间调层次是主要关系。",
        "中": "明暗层次清晰，整体反差保持适中。",
        "高": "深色与亮部形成清晰分离，主体立体感明显。",
    }[contrast]

    median_s = round(float(np.median(valid_s)), 4) if valid_s.size else 0.0
    sat_level = saturation_level(median_s)
    sat_shares = {
        "low": round(float(np.mean(valid_s < 0.20)), 6) if valid_s.size else 1.0,
        "mid": round(float(np.mean((valid_s >= 0.20) & (valid_s < 0.55))), 6) if valid_s.size else 0.0,
        "high": round(float(np.mean(valid_s >= 0.55)), 6) if valid_s.size else 0.0,
    }
    saturation_description = {
        "低": "灰阶与低浓度颜色占比较高，整体色彩表达克制。",
        "中": "综合色彩关系自然稳定，主色清晰但不过分浓烈。",
        "高": "综合色彩存在感较强，主色与点缀色表达鲜明。",
    }[sat_level]

    chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
    neutral_mask = working_mask & (chroma < 8) & (lightness > 20) & (lightness < 90)
    neutral_share = round(float(neutral_mask.sum() / max(working_mask.sum(), 1)), 6)
    neutral_coverage = _neutral_spatial_coverage(neutral_mask, working_mask)
    a_median = round(float(np.median(lab[..., 1][neutral_mask])), 2) if neutral_mask.any() else None
    b_median = round(float(np.median(lab[..., 2][neutral_mask])), 2) if neutral_mask.any() else None
    wb_status, wb_judgement = white_balance_judgement(
        neutral_share, neutral_coverage, a_median, b_median
    )

    tonal_regions = []
    for role, region_mask in [
        ("暗部", working_mask & (lightness < 35)),
        ("中间调", working_mask & (lightness >= 35) & (lightness < 70)),
        ("高光", working_mask & (lightness >= 70)),
    ]:
        if region_mask.any():
            median_rgb = np.median(rgb[region_mask], axis=0)
            rgb_values = [int(round(value)) for value in median_rgb]
            tonal_regions.append({"role": role, "rgb": rgb_values, "hue": hue_name(rgb_values)})
        else:
            tonal_regions.append({"role": role, "rgb": [128, 128, 128], "hue": "中性灰"})

    palette = dominant_tonal_palette(rgb01, lab, working_mask) if include_palette else []
    if analyze_faces:
        face_detection = detect_faces(rgb, backend=face_backend)
        skin = analyze_skin_anchors(rgb, lab, working_mask, face_detection)
        _scale_skin_to_source(skin, scale)
    else:
        skin = {
            "status": "未验证",
            "face_count": None,
            "detector": "disabled",
            "requested_backend": "none",
            "available_backends": [],
            "backend_degraded": False,
            "backend_note": "肤色分析已关闭",
            "primary_anchor": None,
            "secondary_anchor": None,
        }

    light = {
        "source": "暂不判定",
        "quality": "暂不判定",
        "ratio": {"低": "低", "中": "中", "高": "高"}[contrast],
        "status": "P1-C待校准",
    }
    effects = {
        "detected": [],
        "not_obvious": [],
        "conclusion": "未识别到可稳定确认的素材特效。",
        "status": "保守降级",
    }

    analysis = {
        "schema_version": "0.12.0",
        "ruleset_version": RULESET_VERSION,
        "official_language": "zh-CN",
        "zero_token": True,
        "source": loaded.metadata,
        "analysis": {
            "working_width": working_size[0],
            "working_height": working_size[1],
            "valid_pixel_share": loaded.metadata["valid_pixel_share"],
        },
        "tone": {
            "code": tone_key,
            "label": tone_label,
            "l_percentiles": percentiles,
            "shares": shares,
            "clipping": {
                "black_share": black_clip,
                "white_share": white_clip,
                "black_class": clipping_class(black_clip),
                "white_class": clipping_class(white_clip),
            },
        },
        "contrast": {"span_l": span_l, "level": contrast, "description": contrast_description},
        "saturation": {
            "metric": "HSV_S",
            "median": median_s,
            "level": sat_level,
            "shares": sat_shares,
            "description": saturation_description,
        },
        "white_balance": {
            "status": wb_status,
            "judgement": wb_judgement,
            "neutral_share": neutral_share,
            "neutral_spatial_coverage": neutral_coverage,
            "a_median": a_median,
            "b_median": b_median,
        },
        "tonal_regions": tonal_regions,
        "tonal_palette": palette,
        "skin": skin,
        "light": light,
        "effects": effects,
        "render_policy": {
            "official_report_format": "png",
            "show_skin_anchor_markers": False,
            "show_face_boxes": False,
            "show_landmarks": False,
            "show_skin_sample_crops": True,
            "skin_sample_crop_ratio": "1:1",
            "generate_jpg": False,
            "render_color_adjustment": False,
        },
    }
    analysis["official_report"] = official_report(analysis)
    return analysis, loaded, working_image


def _neutral_spatial_coverage(
    neutral_mask: np.ndarray, valid_mask: np.ndarray, grid_size: int = 4
) -> float:
    """Return the share of grid cells containing a meaningful neutral sample."""
    height, width = neutral_mask.shape
    qualified = 0
    total = grid_size * grid_size
    for row in range(grid_size):
        y1 = row * height // grid_size
        y2 = (row + 1) * height // grid_size
        for column in range(grid_size):
            x1 = column * width // grid_size
            x2 = (column + 1) * width // grid_size
            valid_tile = valid_mask[y1:y2, x1:x2]
            valid_count = int(valid_tile.sum())
            if valid_count < 32:
                continue
            neutral_count = int((neutral_mask[y1:y2, x1:x2] & valid_tile).sum())
            if neutral_count / valid_count >= 0.01:
                qualified += 1
    return round(qualified / total, 4)


def _scale_skin_to_source(skin: dict, scale: float) -> None:
    if scale == 0:
        return
    inverse = 1.0 / scale
    for key in ["primary_anchor", "secondary_anchor"]:
        anchor = skin.get(key)
        if not anchor:
            continue
        if "center" in anchor:
            anchor["source_center"] = [round(value * inverse, 2) for value in anchor["center"]]
        crop = anchor.get("crop")
        if crop:
            anchor["source_crop"] = {
                "x": max(0, int(round(crop["x"] * inverse))),
                "y": max(0, int(round(crop["y"] * inverse))),
                "width": max(1, int(round(crop["width"] * inverse))),
                "height": max(1, int(round(crop["height"] * inverse))),
                "ratio": "1:1",
            }
