from __future__ import annotations

from copy import deepcopy

import numpy as np

from color_palette.lighting import SubjectRegion
from color_palette.quantitative import analyze_quantitative


def _result(
    lab: np.ndarray,
    *,
    subject_box: tuple[int, int, int, int] | None = None,
    valid_mask: np.ndarray | None = None,
):
    height, width = lab.shape[:2]
    rgb = np.full((height, width, 3), 128, dtype=np.uint8)
    valid = (
        np.ones((height, width), dtype=bool)
        if valid_mask is None
        else valid_mask.astype(bool, copy=True)
    )
    if subject_box is None:
        subject_box = (width // 4, height // 4, width // 2, height // 2)
    x, y, box_width, box_height = subject_box
    subject_mask = np.zeros_like(valid)
    subject_mask[y : y + box_height, x : x + box_width] = True
    subject = SubjectRegion("main_subject", subject_box, subject_mask)
    lighting = {
        "debug": {
            "classifiers": {
                "source": {"confidence": 0.87},
                "quality": {"confidence": 0.91},
                "ratio": {"confidence": 0.82},
            }
        }
    }
    material = {
        "items": [
            {"display_name": "细颗粒", "confidence": 0.84},
        ]
    }
    return analyze_quantitative(
        rgb,
        lab.astype(np.float64),
        valid,
        subject=subject,
        lighting=lighting,
        material_effects=material,
    )


def _lstar_gradient(start: float, end: float, width: int = 512) -> np.ndarray:
    lstar = np.linspace(start, end, width, dtype=np.float64)
    lab = np.zeros((128, width, 3), dtype=np.float64)
    lab[..., 0] = lstar
    return lab


def test_lstar_gradient_percentiles_histogram_and_neutral_chroma():
    result = _result(_lstar_gradient(0.0, 100.0)).quantitative
    percentiles = result["luminance"]["percentiles"]
    assert list(percentiles.values()) == sorted(percentiles.values())
    normalized = result["histograms"]["luminance_lstar"]["normalized"]
    assert abs(sum(normalized) - 1.0) < 1e-8
    assert result["chroma"]["percentiles"]["p90"] == 0.0
    assert result["chroma"]["shares"]["low_chroma_share"] == 1.0


def test_raised_blacks_raise_floors_and_reduce_black_share():
    normal = _result(_lstar_gradient(0.0, 100.0)).quantitative
    raised = _result(_lstar_gradient(20.0, 100.0)).quantitative
    assert (
        raised["luminance"]["percentiles"]["p1"]
        > normal["luminance"]["percentiles"]["p1"]
    )
    assert (
        raised["luminance"]["percentiles"]["p5"]
        > normal["luminance"]["percentiles"]["p5"]
    )
    assert (
        raised["luminance"]["shares"]["near_black_share"]
        < normal["luminance"]["shares"]["near_black_share"]
    )


def test_compressed_highlights_change_ceiling_shoulder_and_headroom():
    normal_lab = _lstar_gradient(0.0, 100.0)
    compressed_lab = normal_lab.copy()
    lstar = compressed_lab[..., 0]
    compressed_lab[..., 0] = np.where(
        lstar <= 70.0, lstar, 70.0 + (lstar - 70.0) * 0.35
    )
    normal = _result(normal_lab).quantitative
    compressed = _result(compressed_lab).quantitative
    assert (
        compressed["luminance"]["percentiles"]["p95"]
        < normal["luminance"]["percentiles"]["p95"]
    )
    assert (
        compressed["luminance"]["percentiles"]["p99"]
        < normal["luminance"]["percentiles"]["p99"]
    )
    assert (
        compressed["tone_signature"]["shoulder_ratio"]
        < normal["tone_signature"]["shoulder_ratio"]
    )
    assert (
        compressed["tone_signature"]["highlight_headroom"]
        > normal["tone_signature"]["highlight_headroom"]
    )


def test_chroma_metrics_are_monotonic():
    low = np.zeros((128, 160, 3), dtype=np.float64)
    low[..., 0], low[..., 1] = 55.0, 5.0
    high = low.copy()
    high[..., 1] = 50.0
    low_result = _result(low).quantitative["chroma"]
    high_result = _result(high).quantitative["chroma"]
    assert high_result["percentiles"]["p50"] > low_result["percentiles"]["p50"]
    assert high_result["percentiles"]["p90"] > low_result["percentiles"]["p90"]
    assert (
        high_result["shares"]["high_chroma_share"]
        > low_result["shares"]["high_chroma_share"]
    )


def test_fixed_lab_hues_map_to_twelve_sector_labels():
    angles_and_labels = [
        (15, "红"),
        (75, "黄"),
        (135, "绿"),
        (195, "青"),
        (255, "蓝"),
        (315, "洋红"),
    ]
    width = 120 * len(angles_and_labels)
    lab = np.zeros((120, width, 3), dtype=np.float64)
    lab[..., 0] = 55.0
    for index, (angle, _) in enumerate(angles_and_labels):
        radians = np.radians(angle)
        lab[:, index * 120 : (index + 1) * 120, 1] = 45.0 * np.cos(radians)
        lab[:, index * 120 : (index + 1) * 120, 2] = 45.0 * np.sin(radians)
    sectors = _result(lab).quantitative["hue_distribution"]["sectors"]
    shares = {item["label"]: item["area_share"] for item in sectors}
    for _, label in angles_and_labels:
        assert shares[label] > 0.16


def test_neutral_axis_tracks_blue_and_yellow_directions():
    gray = np.zeros((128, 160, 3), dtype=np.float64)
    gray[..., 0] = 55.0
    blue = gray.copy()
    blue[..., 2] = -5.0
    yellow = gray.copy()
    yellow[..., 2] = 5.0
    gray_axis = _result(gray).quantitative["neutral_axis"]
    blue_axis = _result(blue).quantitative["neutral_axis"]
    yellow_axis = _result(yellow).quantitative["neutral_axis"]
    assert gray_axis["overall"]["status"] == "valid"
    assert gray_axis["neutral_pixel_share"] == 1.0
    assert gray_axis["neutral_spatial_coverage"] == 1.0
    assert blue_axis["overall"]["b_median"] < 0
    assert yellow_axis["overall"]["b_median"] > 0


def test_scene_palette_assigns_blue_orange_and_red_roles_without_affecting_neutral_axis():
    height, width = 100, 100
    lab = np.zeros((height, width, 3), dtype=np.float64)
    lab[:, :60] = [48.0, 22.0, -52.0]
    lab[:, 60:90] = [62.0, 38.0, 42.0]
    lab[:, 90:] = [53.0, 72.0, 45.0]
    result = _result(lab).quantitative
    palette = result["palettes"]["scene_palette"]
    by_role = {item["role"]: item for item in palette["clusters"]}
    assert by_role["primary"]["hue_angle"] > 240
    assert 30 < by_role["secondary"]["hue_angle"] < 60
    assert by_role["accent"]["chroma"] > by_role["secondary"]["chroma"]
    assert result["neutral_axis"]["overall"]["status"] == "insufficient"


def test_subject_background_delta_l_changes_sign():
    box = (40, 30, 80, 60)
    bright_subject = np.zeros((120, 160, 3), dtype=np.float64)
    bright_subject[..., 0] = 25.0
    bright_subject[30:90, 40:120, 0] = 75.0
    dark_subject = np.zeros((120, 160, 3), dtype=np.float64)
    dark_subject[..., 0] = 80.0
    dark_subject[30:90, 40:120, 0] = 25.0
    bright = _result(bright_subject, subject_box=box).quantitative["subject_background"]
    dark = _result(dark_subject, subject_box=box).quantitative["subject_background"]
    assert bright["status"] == dark["status"] == "valid"
    assert bright["delta_l"] > 0
    assert dark["delta_l"] < 0
    assert bright["delta_e00"] > 0


def test_local_contrast_is_not_global_image_standard_deviation():
    lab = np.zeros((200, 200, 3), dtype=np.float64)
    lab[:, :100, 0] = 20.0
    lab[:, 100:, 0] = 80.0
    contrast = _result(lab).quantitative["contrast"]
    assert contrast["global_l_p95_p5"] == 60.0
    assert contrast["local_contrast_median"] == 0.0
    assert contrast["local_contrast_p75"] == 0.0


def test_fully_invalid_pixels_do_not_enter_metrics():
    lab = np.zeros((120, 200, 3), dtype=np.float64)
    lab[:, 100:, 0] = 60.0
    valid = np.zeros((120, 200), dtype=bool)
    valid[:, 100:] = True
    quantitative = _result(lab, valid_mask=valid).quantitative
    assert quantitative["luminance"]["percentiles"]["p50"] == 60.0
    assert quantitative["luminance"]["shares"]["near_black_share"] == 0.0
    assert quantitative["performance"]["valid_pixel_count"] == 12_000


def test_quantitative_metrics_are_deterministic_across_five_runs():
    lab = np.zeros((120, 180, 3), dtype=np.float64)
    lab[..., 0] = np.linspace(10.0, 92.0, 180)
    lab[:, :90, 1:] = [28.0, -34.0]
    lab[:, 90:, 1:] = [42.0, 38.0]
    outputs = []
    for _ in range(5):
        result = deepcopy(_result(lab).quantitative)
        result.pop("performance")
        outputs.append(result)
    assert outputs[1:] == outputs[:-1]


def test_color_dna_uses_null_for_missing_effect_confidence():
    lab = _lstar_gradient(0.0, 100.0)
    result = _result(lab)
    assert result.color_dna["lighting_confidence"] == 0.82
    assert result.color_dna["material_fx_confidence_max"] == 0.84
    assert {"L50", "L95_minus_L5", "L75_minus_L25", "C50", "C90"} <= set(
        result.color_dna
    )
    assert all(
        np.isfinite(value)
        for value in result.color_dna.values()
        if isinstance(value, float)
    )
