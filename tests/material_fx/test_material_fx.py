from __future__ import annotations

import cv2
import numpy as np
from PIL import ImageDraw

from color_palette.analyzer import analyze
from color_palette.copy import official_report
from color_palette.material_fx import (
    NO_EFFECT_SUMMARY,
    analyze_material_fx,
    display_names,
    legacy_effects,
)
from color_palette.render import render_report


def _structured(size: int = 512) -> np.ndarray:
    image = np.full((size, size, 3), 112, dtype=np.uint8)
    cv2.rectangle(image, (30, 30), (230, 230), (58, 92, 132), -1)
    cv2.rectangle(image, (282, 38), (482, 226), (186, 154, 96), -1)
    cv2.circle(image, (150, 370), 94, (214, 214, 214), -1)
    cv2.line(image, (280, 278), (470, 468), (25, 25, 25), 18)
    cv2.line(image, (470, 278), (280, 468), (235, 235, 235), 12)
    return image


def _names(image: np.ndarray) -> list[str]:
    result = analyze_material_fx(image, np.ones(image.shape[:2], dtype=bool))
    return [item["display_name"] for item in result["items"]]


def test_no_effect_uses_exact_official_copy():
    result = analyze_material_fx(_structured(), np.ones((512, 512), dtype=bool))
    assert result["items"] == []
    assert result["summary"] == NO_EFFECT_SUMMARY
    assert display_names({"material_effects": result}) == [NO_EFFECT_SUMMARY]


def test_fine_grain_uses_flat_roi_and_is_not_jpeg_noise():
    rng = np.random.default_rng(130)
    image = _structured().astype(np.int16)
    noise = rng.normal(0, 5.2, image.shape[:2]).round().astype(np.int16)
    image = np.clip(image + noise[..., None], 0, 255).astype(np.uint8)
    result = analyze_material_fx(image, np.ones(image.shape[:2], dtype=bool))
    grain = next(item for item in result["items"] if item["type"] == "grain")
    assert grain["display_name"] == "细颗粒"
    assert grain["subtype"] == "fine"
    assert result["diagnostics"]["roi_strategy"]["flat"]


def test_coarse_grain_is_distinct_from_fine_grain():
    rng = np.random.default_rng(131)
    base = _structured().astype(np.float32)
    noise = rng.normal(0, 15, base.shape[:2]).astype(np.float32)
    coarse = cv2.GaussianBlur(noise, (0, 0), 2.0)
    image = np.clip(base + coarse[..., None], 0, 255).astype(np.uint8)
    assert "粗颗粒" in _names(image)


def test_coarse_grain_fallback_uses_smaller_flat_regions():
    rng = np.random.default_rng(133)
    image = np.zeros((600, 600, 3), dtype=np.float32)
    image[:, :300] = 250
    image[:, 300:] = 5
    image[100:500, 200:400] = (178, 148, 132)
    noise = cv2.GaussianBlur(
        rng.normal(0, 12, image.shape[:2]).astype(np.float32),
        (0, 0),
        1.8,
    )
    subject = np.zeros(image.shape[:2], dtype=np.float32)
    subject[100:500, 200:400] = 1
    image += noise[..., None] * subject[..., None]
    names = _names(np.clip(image, 0, 255).astype(np.uint8))
    assert "粗颗粒" in names


def test_rgb_channel_displacement_is_detected():
    base = _structured()
    shifted = base.copy()
    shifted[..., 0] = np.roll(base[..., 0], 2, axis=1)
    shifted[..., 2] = np.roll(base[..., 2], -2, axis=1)
    assert "RGB 色彩偏移" in _names(shifted)


def test_whole_frame_gaussian_blur_is_detected():
    blurred = cv2.GaussianBlur(_structured(), (0, 0), 3.2)
    assert "高斯模糊" in _names(blurred)


def test_scale_normalized_blur_detects_consistent_full_frame_detail_loss():
    rng = np.random.default_rng(134)
    y, x = np.mgrid[:768, :768]
    texture = (
        128
        + 45 * np.sin(x / 8)
        + 35 * np.sin(y / 10.4)
        + rng.normal(0, 18, (768, 768))
    )
    texture = np.repeat(
        np.clip(texture, 0, 255).astype(np.uint8)[..., None],
        3,
        axis=2,
    )
    blurred = cv2.GaussianBlur(texture, (0, 0), 3.4)
    assert "高斯模糊" in _names(blurred)


def test_mild_whole_frame_detail_loss_has_supported_label():
    blurred = cv2.GaussianBlur(_structured(), (0, 0), 1.7)
    assert set(_names(blurred)) & {"柔化", "低清晰度"}


def test_highlight_diffusion_is_detected_but_hard_backlight_is_not():
    hard = np.full((512, 512, 3), 24, dtype=np.uint8)
    cv2.circle(hard, (256, 256), 55, (255, 255, 255), -1)
    assert "高光扩散" not in _names(hard)

    halo = cv2.GaussianBlur(hard, (0, 0), 22)
    cv2.circle(halo, (256, 256), 38, (255, 255, 255), -1)
    assert "高光扩散" in _names(halo)


def test_natural_depth_of_field_keeps_sharp_subject_exclusion():
    background = cv2.GaussianBlur(_structured(), (0, 0), 5)
    sharp = _structured()
    background[120:390, 150:360] = sharp[120:390, 150:360]
    names = _names(background)
    assert "柔化" not in names
    assert "高斯模糊" not in names


def test_saturation_and_smooth_regions_are_not_material_fx():
    image = np.zeros((512, 512, 3), dtype=np.uint8)
    image[:256, :256] = (255, 0, 0)
    image[:256, 256:] = (0, 255, 0)
    image[256:, :256] = (0, 0, 255)
    image[256:, 256:] = (255, 255, 0)
    assert _names(image) == []


def test_smooth_skin_with_sharp_features_is_not_global_blur():
    image = _structured()
    cv2.ellipse(image, (256, 260), (88, 118), 0, 0, 360, (205, 156, 132), -1)
    cv2.circle(image, (225, 235), 9, (25, 25, 25), -1)
    cv2.circle(image, (287, 235), 9, (25, 25, 25), -1)
    cv2.line(image, (226, 310), (286, 310), (45, 30, 30), 5)
    names = _names(image)
    assert "柔化" not in names
    assert "高斯模糊" not in names
    assert "低清晰度" not in names


def test_low_fi_and_film_border_categories_are_reachable():
    rng = np.random.default_rng(132)
    tiny = rng.integers(30, 225, (64, 64, 3), dtype=np.uint8)
    low_fi = cv2.resize(tiny, (512, 512), interpolation=cv2.INTER_NEAREST)
    assert "画质降低" in _names(low_fi)

    bordered = _structured()
    bordered[:28] = 8
    bordered[-28:] = 8
    bordered[:, :28] = 8
    bordered[:, -28:] = 8
    assert "胶片边框" in _names(bordered)


def test_multilabel_copy_only_exposes_display_names():
    material_effects = {
        "ruleset_version": "material-fx-0.13.0",
        "items": [
            {
                "type": "grain",
                "display_name": "细颗粒",
                "confidence": 0.91,
                "evidence": ["内部证据"],
                "alternatives": ["数字噪声"],
                "regions": ["flat"],
                "subtype": "fine",
            },
            {
                "type": "highlight_diffusion",
                "display_name": "高光扩散",
                "confidence": 0.87,
                "evidence": ["内部证据"],
                "alternatives": ["真实逆光"],
                "regions": ["highlight"],
            },
        ],
        "summary": "细颗粒\n高光扩散",
        "status": "已识别",
        "diagnostics": {},
    }
    analysis = _minimal_analysis(material_effects)
    report = official_report(analysis)
    visible = report["素材特效&光线构成"]["素材特效"]
    assert visible == {"标签": ["细颗粒", "高光扩散"], "结论": "细颗粒\n高光扩散"}
    assert "confidence" not in str(visible)
    assert "内部证据" not in str(visible)


def test_v012_legacy_effects_fallback_and_adapter():
    legacy = {"effects": {"detected": ["柔化"], "not_obvious": [], "conclusion": "柔化"}}
    assert display_names(legacy) == ["柔化"]
    current = {
        "ruleset_version": "material-fx-0.13.0",
        "items": [],
        "summary": NO_EFFECT_SUMMARY,
        "status": "未发现明显",
    }
    assert legacy_effects(current)["conclusion"] == NO_EFFECT_SUMMARY


def test_renderer_one_and_multiple_labels_never_draw_internal_fields(
    gradient_jpg, tmp_path, monkeypatch
):
    analysis, loaded, _ = analyze(gradient_jpg, analyze_faces=False)
    captured: list[str] = []
    original_text = ImageDraw.ImageDraw.text

    def record_text(self, xy, text, *args, **kwargs):
        captured.append(str(text))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    effect_types = {
        "细颗粒": "grain",
        "高光扩散": "highlight_diffusion",
        "柔化": "softness",
    }
    for labels in (["细颗粒"], ["细颗粒", "高光扩散", "柔化"]):
        analysis["material_effects"] = {
            "ruleset_version": "material-fx-0.13.0",
            "items": [
                {
                    "type": effect_types[label],
                    "display_name": label,
                    "confidence": 0.99,
                    "evidence": ["绝不进入正式报告"],
                    "alternatives": ["内部候选"],
                    "regions": ["flat"],
                }
                for label in labels
            ],
            "summary": "\n".join(labels),
            "status": "已识别",
            "diagnostics": {"ROI": "内部字段"},
        }
        analysis["official_report"] = official_report(analysis)
        output = tmp_path / f"report-{len(labels)}.png"
        render_report(analysis, loaded, output)
        assert output.is_file()

    visible = " ".join(captured)
    for label in ["细颗粒", "高光扩散", "柔化"]:
        assert label in visible
    for forbidden in ["confidence", "evidence", "绝不进入正式报告", "内部候选", "ROI"]:
        assert forbidden not in visible


def _minimal_analysis(material_effects: dict) -> dict:
    return {
        "tone": {"code": "mid_key", "clipping": {"black_class": "无", "white_class": "无"}},
        "contrast": {"level": "中", "description": "明暗描述。"},
        "saturation": {"level": "中", "description": "色彩描述。"},
        "white_balance": {"judgement": "接近中性"},
        "tonal_regions": [
            {"role": "暗部", "hue": "蓝"},
            {"role": "中间调", "hue": "橙黄"},
            {"role": "高光", "hue": "中性灰"},
        ],
        "tonal_palette": [],
        "skin": {"status": "无人像", "face_count": 0},
        "material_effects": material_effects,
        "effects": legacy_effects(material_effects),
        "light": {"source": "暂不判定", "quality": "暂不判定", "ratio": "中"},
    }
