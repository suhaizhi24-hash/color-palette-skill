import json

from color_palette.pipeline import run


def test_transparent_pixels_ignored(transparent_png, tmp_path):
    outputs = run(transparent_png, tmp_path / "out")
    data = json.loads(outputs["analysis_json"].read_text(encoding="utf-8"))
    assert data["source"]["has_alpha"] is True
    assert 0.49 <= data["source"]["valid_pixel_share"] <= 0.51
    # Transparent red half must not dominate visible analysis.
    middle = data["tonal_palette"][2]["rgb"]
    assert middle[2] >= middle[0]


def test_webp_input(sample_webp, tmp_path):
    outputs = run(sample_webp, tmp_path / "out")
    assert outputs["analysis_json"].exists()
    assert outputs["color_report_png"].exists()
