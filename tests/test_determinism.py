import json

from color_palette.pipeline import run


def test_analysis_is_deterministic(gradient_jpg, tmp_path):
    first = run(gradient_jpg, tmp_path / "one")
    second = run(gradient_jpg, tmp_path / "two")
    a = json.loads(first["analysis_json"].read_text(encoding="utf-8"))
    b = json.loads(second["analysis_json"].read_text(encoding="utf-8"))
    a.pop("outputs", None)
    b.pop("outputs", None)
    assert a == b
