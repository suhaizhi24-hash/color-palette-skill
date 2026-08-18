from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from color_palette.copy import official_report
from color_palette.lighting import (
    QualityFeatures,
    RatioFeatures,
    SourceFeatures,
    analyze_lighting,
    classify_quality,
    classify_ratio,
    classify_source,
    select_subject_region,
)
from scripts.run_lighting_benchmark import load_manifest, run


ROOT = Path(__file__).resolve().parents[2]


def _source_features(**overrides) -> SourceFeatures:
    values = {
        "scene_dark_share": 0.12,
        "scene_highlight_share": 0.03,
        "background_uniformity": 0.88,
        "subject_background_ev": 0.65,
        "subject_separation": 0.28,
        "chromatic_spread": 0.05,
        "environment_texture": 0.03,
        "bright_component_count": 2,
        "bright_component_share": 0.04,
        "subject_valid_share": 0.30,
        "color_temperature_proxy": 0.0,
    }
    values.update(overrides)
    return SourceFeatures(**values)


def test_studio_source_does_not_imply_soft_quality():
    source = classify_source(_source_features())
    quality = classify_quality(
        QualityFeatures(0.34, 0.09, 0.03, 3.0, 0.10, 0.28)
    )
    assert source == "studio"
    assert quality == "hard"


def test_hard_quality_does_not_imply_high_ratio():
    quality = classify_quality(
        QualityFeatures(0.31, 0.08, 0.03, 2.67, 0.09, 0.28)
    )
    ratio = classify_ratio(
        RatioFeatures(0.55, 0.32, 0.72, 0.23, 0.40, 0.35, 0.35, 0.28)
    )
    assert quality == "hard"
    assert ratio == "medium"


def test_natural_source_does_not_imply_hard_quality():
    source = classify_source(
        _source_features(
            background_uniformity=0.18,
            subject_background_ev=0.20,
            subject_separation=0.10,
            environment_texture=0.34,
        )
    )
    quality = classify_quality(
        QualityFeatures(0.18, 0.012, 0.010, 1.20, 0.035, 0.28)
    )
    assert source == "natural"
    assert quality == "soft"


def test_warm_and_cool_proxies_do_not_decide_source():
    warm = classify_source(_source_features(color_temperature_proxy=0.85))
    cool = classify_source(_source_features(color_temperature_proxy=-0.85))
    assert warm == cool == "studio"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {
                "scene_dark_share": 0.65,
                "scene_highlight_share": 0.08,
                "background_uniformity": 0.30,
                "subject_background_ev": 2.0,
                "subject_separation": 0.45,
                "chromatic_spread": 0.05,
                "environment_texture": 0.10,
                "bright_component_share": 0.08,
            },
            "flash",
        ),
        (
            {
                "scene_dark_share": 0.65,
                "scene_highlight_share": 0.08,
                "background_uniformity": 0.25,
                "subject_background_ev": 2.0,
                "subject_separation": 0.45,
                "chromatic_spread": 0.50,
                "environment_texture": 0.30,
                "bright_component_share": 0.08,
            },
            "mixed",
        ),
    ],
)
def test_flash_and_mixed_source_categories_are_reachable(overrides, expected):
    assert classify_source(_source_features(**overrides)) == expected


def test_global_contrast_is_not_lighting_ratio():
    image = np.full((320, 320, 3), 128, dtype=np.uint8)
    image[:, :70] = 0
    image[:, 250:] = 255
    mask = np.ones((320, 320), dtype=bool)
    result = analyze_lighting(image, mask, face_box=[100, 90, 120, 130])
    assert result["ratio"]["code"] == "low"


def test_public_synthetic_penumbra_fixtures_exercise_soft_and_hard_rules():
    soft = analyze_lighting(
        cv2.cvtColor(cv2.imread(str(ROOT / "examples/public/synthetic_soft_light.png")), cv2.COLOR_BGR2RGB),
        np.ones((320, 480), dtype=bool),
    )
    hard = analyze_lighting(
        cv2.cvtColor(cv2.imread(str(ROOT / "examples/public/synthetic_hard_light.png")), cv2.COLOR_BGR2RGB),
        np.ones((320, 480), dtype=bool),
    )
    assert soft["quality"]["code"] == "soft"
    assert hard["quality"]["code"] == "hard"


def test_self_luminous_sets_quality_and_ratio_not_applicable():
    image = np.full((320, 320, 3), 3, dtype=np.uint8)
    cv2.circle(image, (160, 160), 27, (255, 150, 35), -1)
    cv2.circle(image, (160, 160), 8, (255, 255, 255), -1)
    result = analyze_lighting(image, np.ones((320, 320), dtype=bool))
    assert result["source"]["code"] == "self_luminous"
    assert result["quality"] == {
        "code": "not_applicable",
        "display_name": "不适用",
    }
    assert result["ratio"] == {
        "code": "not_applicable",
        "display_name": "不适用",
    }
    analysis = _minimal_report_input()
    analysis["lighting"] = result
    assert official_report(analysis)["素材特效&光线构成"]["光线构成"] == {
        "光源": "自发光",
        "光质": "不适用",
        "光比": "不适用",
    }


def test_subject_roi_uses_face_then_body_then_main_subject_fallback():
    mask = np.ones((600, 400), dtype=bool)
    face = select_subject_region(mask, face_box=[100, 80, 120, 120])
    upper = select_subject_region(mask, face_box=[150, 70, 60, 60])
    main = select_subject_region(mask)
    assert face.kind == "face"
    assert upper.kind == "upper_body"
    assert main.kind == "main_subject"
    assert all(region.mask.any() for region in [face, upper, main])


def test_renderer_copy_prefers_v014_and_hides_internal_debug():
    analysis = _minimal_report_input()
    analysis["lighting"] = {
        "ruleset_version": "lighting-0.14.0",
        "source": {"code": "natural", "display_name": "自然光"},
        "quality": {"code": "hard", "display_name": "硬光"},
        "ratio": {"code": "high", "display_name": "高"},
        "subject_roi": {"type": "face", "box": [1, 2, 3, 4]},
        "debug": {"confidence": 0.99, "evidence": ["内部证据"], "delta_ev": 2.0},
    }
    report = official_report(analysis)
    visible = report["素材特效&光线构成"]["光线构成"]
    assert visible == {"光源": "自然光", "光质": "硬光", "光比": "高"}
    assert "confidence" not in str(report)
    assert "内部证据" not in str(report)
    assert "delta_ev" not in str(report)


def test_legacy_json_renderer_fallback_is_preserved():
    analysis = _minimal_report_input()
    analysis["light"] = {"source": "人工闪光", "quality": "硬光", "ratio": "中"}
    assert official_report(analysis)["素材特效&光线构成"]["光线构成"] == {
        "光源": "人工闪光",
        "光质": "硬光",
        "光比": "中",
    }


def test_benchmark_manifest_registers_six_pending_external_anchors():
    document = json.loads(
        (ROOT / "tests" / "lighting" / "lighting_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    anchors = document["anchors"]
    assert [anchor["id"] for anchor in anchors] == list("ABCDEF")
    assert all(anchor["status"] == "pending_external_asset" for anchor in anchors)
    assert [(a["expected"]["source"], a["expected"]["quality"], a["expected"]["ratio"]) for a in anchors] == [
        ("natural", "hard", "high"),
        ("studio", "soft", "medium"),
        ("studio", "hard", "high"),
        ("natural", "hard", "high"),
        ("mixed", "hard", "high"),
        ("natural", "soft", "medium"),
    ]
    serialized = json.dumps(document, ensure_ascii=False)
    assert "/Users/" not in serialized
    assert "sha256" not in serialized.casefold()


def test_benchmark_runner_reports_pending_without_faking_assets(tmp_path):
    manifest = load_manifest(ROOT / "tests" / "lighting" / "lighting_benchmark.json")
    result = run(manifest, tmp_path)
    assert result["status"] == "PENDING"
    assert result["passed"] == result["failed"] == 0
    assert result["pending"] == 6
    assert all(item["actual"] is None for item in result["results"])


def test_analysis_schema_exposes_v014_lighting_enums():
    schema = json.loads((ROOT / "schemas" / "analysis.schema.json").read_text(encoding="utf-8"))
    lighting = schema["properties"]["lighting"]["properties"]
    assert lighting["source"]["properties"]["code"]["enum"] == [
        "natural", "studio", "flash", "mixed", "self_luminous", "unknown"
    ]
    assert lighting["quality"]["properties"]["code"]["enum"] == [
        "hard", "soft", "not_applicable", "unknown"
    ]
    assert lighting["ratio"]["properties"]["code"]["enum"] == [
        "low", "medium", "high", "not_applicable", "unknown"
    ]


def _minimal_report_input() -> dict:
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
        "effects": {"detected": [], "not_obvious": [], "conclusion": "未识别。"},
        "light": {"source": "暂不判定", "quality": "暂不判定", "ratio": "中"},
    }
