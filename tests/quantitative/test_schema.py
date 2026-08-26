import json
from pathlib import Path

from jsonschema import Draft202012Validator

from color_palette.analyzer import analyze

ROOT = Path(__file__).resolve().parents[2]


def test_v015_analysis_and_legacy_field_subset_match_schema():
    schema = json.loads(
        (ROOT / "schemas/analysis.schema.json").read_text(encoding="utf-8")
    )
    analysis, _, _ = analyze(
        ROOT / "examples/synthetic_portrait.png", face_backend="none"
    )
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(analysis)) == []

    legacy_compatible = dict(analysis)
    legacy_compatible.pop("quantitative")
    legacy_compatible.pop("color_dna")
    assert list(validator.iter_errors(legacy_compatible)) == []


def test_quantitative_json_has_no_nan_or_infinity():
    analysis, _, _ = analyze(
        ROOT / "examples/synthetic_portrait.png", face_backend="none"
    )
    encoded = json.dumps(
        {"quantitative": analysis["quantitative"], "color_dna": analysis["color_dna"]},
        ensure_ascii=False,
        allow_nan=False,
    )
    assert "NaN" not in encoded
    assert "Infinity" not in encoded


def test_formal_renderer_source_is_not_changed_by_quantitative_schema():
    source = (ROOT / "src/color_palette/render.py").read_text(encoding="utf-8")
    assert "quantitative" not in source
    assert "color_dna" not in source
