from __future__ import annotations

import json
from pathlib import Path

from color_palette.analyzer import analyze
from color_palette.golden_cli import main as golden_main
from color_palette.ground_truth import compare_analysis, validate_dataset
from color_palette.io import sha256_file


def _fixture_ground_truth(image: Path) -> dict:
    analysis, _, _ = analyze(image, analyze_faces=False, include_palette=False)
    return {
        "schema_version": "1.0.0",
        "dataset": {
            "name": "pytest 临时样本",
            "version": "0.1.0",
            "status": "示例",
            "privacy": "公开",
        },
        "samples": [
            {
                "id": "gradient",
                "file_hint": image.name,
                "sha256": sha256_file(image),
                "expected": {
                    "tone.label": analysis["tone"]["label"],
                    "contrast.level": analysis["contrast"]["level"],
                    "saturation.level": analysis["saturation"]["level"],
                    "white_balance.judgement": analysis["white_balance"]["judgement"],
                },
                "advisory": {
                    "skin.status": "无人像",
                },
                "metrics": [
                    {
                        "path": "tone.l_percentiles.p50",
                        "value": analysis["tone"]["l_percentiles"]["p50"],
                        "tolerance": 0.2,
                    }
                ],
            }
        ],
    }


def test_compare_analysis_reports_required_mismatch():
    analysis = {"tone": {"label": "中间调结构"}, "skin": {"status": "无人像"}}
    sample = {
        "expected": {"tone.label": "高调结构"},
        "advisory": {"skin.status": "无人像"},
    }
    result = compare_analysis(analysis, sample)
    assert result["status"] == "失败"
    assert result["required_failure_count"] == 1
    assert result["advisory_mismatch_count"] == 0


def test_validate_dataset_passes_confirmed_fixture(gradient_jpg):
    ground_truth = _fixture_ground_truth(gradient_jpg)
    report = validate_dataset(gradient_jpg, ground_truth, strict_missing=True)
    assert report["status"] == "通过"
    assert report["summary"]["matched_sample_count"] == 1
    assert report["summary"]["required_failure_count"] == 0


def test_validate_dataset_skips_face_advisory_by_default(gradient_jpg):
    ground_truth = _fixture_ground_truth(gradient_jpg)
    ground_truth["samples"][0]["advisory"]["skin.status"] = "单人"
    report = validate_dataset(gradient_jpg, ground_truth, strict_missing=True)
    assert report["status"] == "通过"
    assert report["include_advisory"] is False
    assert report["summary"]["advisory_mismatch_count"] == 0


def test_golden_cli_writes_report(gradient_jpg, tmp_path):
    ground_truth = _fixture_ground_truth(gradient_jpg)
    gt_path = tmp_path / "ground_truth.json"
    report_path = tmp_path / "golden_report.json"
    gt_path.write_text(json.dumps(ground_truth, ensure_ascii=False), encoding="utf-8")
    code = golden_main(
        [
            str(gradient_jpg),
            "--ground-truth",
            str(gt_path),
            "--output",
            str(report_path),
            "--strict-missing",
        ]
    )
    assert code == 0
    result = json.loads(report_path.read_text(encoding="utf-8"))
    assert result["status"] == "通过"


def test_public_example_contains_only_public_synthetic_sample():
    root = Path(__file__).resolve().parents[1]
    example = json.loads(
        (root / "examples" / "golden_ground_truth.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert example["dataset"]["privacy"] == "公开"
    assert [sample["id"] for sample in example["samples"]] == ["synthetic_portrait"]
