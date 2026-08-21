from pathlib import Path
import json
from PIL import Image
import pytest

from color_palette.errors import RenderError
from color_palette.pipeline import run


def test_png_json_only(gradient_jpg, tmp_path):
    outputs = run(gradient_jpg, tmp_path / "out")
    assert set(outputs) == {"analysis_json", "color_report_png"}
    assert outputs["analysis_json"].exists()
    assert outputs["color_report_png"].exists()
    assert not list((tmp_path / "out").glob("*.jpg"))
    assert not list((tmp_path / "out").glob("*.jpeg"))
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == [
        "gradient_analysis.json",
        "gradient_color_report.png",
    ]


def test_input_file_is_not_modified(gradient_jpg, tmp_path):
    import hashlib

    before = hashlib.sha256(gradient_jpg.read_bytes()).hexdigest()
    run(gradient_jpg, tmp_path / "out")
    after = hashlib.sha256(gradient_jpg.read_bytes()).hexdigest()
    assert after == before


def test_report_dimensions(gradient_jpg, tmp_path):
    outputs = run(gradient_jpg, tmp_path / "out")
    with Image.open(outputs["color_report_png"]) as image:
        assert image.size == (1600, 1200)
        assert image.format == "PNG"


def test_official_modules_and_policy(gradient_jpg, tmp_path):
    outputs = run(gradient_jpg, tmp_path / "out")
    data = json.loads(outputs["analysis_json"].read_text(encoding="utf-8"))
    assert data["official_language"] == "zh-CN"
    assert data["zero_token"] is True
    assert data["schema_version"] == "0.15.0"
    assert "quantitative" in data
    assert "color_dna" in data
    assert data["quantitative"]["measurement_context"]["edit_parameter_inference"] is False
    assert data["render_policy"]["official_report_format"] == "png"
    assert data["render_policy"]["generate_jpg"] is False
    assert data["official_report"]["官方模块"] == [
        "影调结构", "明暗关系", "色彩浓度", "白平衡&色相", "影调色卡", "肤色锚点", "素材特效&光线构成"
    ]


def test_analysis_json_matches_schema(gradient_jpg, tmp_path):
    from pathlib import Path
    from jsonschema import Draft202012Validator

    outputs = run(gradient_jpg, tmp_path / "schema", face_backend="none")
    data = json.loads(outputs["analysis_json"].read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "analysis.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(data))
    assert errors == [], [error.message for error in errors]


def test_png_save_failure_keeps_chinese_render_error(monkeypatch, gradient_jpg, tmp_path):
    def fail_save(*args, **kwargs):
        raise OSError("synthetic save failure")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(RenderError, match="PNG报告保存失败"):
        run(gradient_jpg, tmp_path / "save-error", face_backend="none")
