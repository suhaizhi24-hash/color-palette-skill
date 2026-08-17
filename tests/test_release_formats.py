import json

from color_palette.io import load_image
from color_palette.pipeline import run


def test_exif_orientation_is_applied(exif_rotated_jpg):
    loaded = load_image(exif_rotated_jpg)
    assert loaded.rgb_image.size == (140, 240)
    assert loaded.metadata["exif_orientation_before"] == 6
    assert loaded.metadata["orientation_applied"] is True
    assert loaded.metadata["orientation"] == "portrait"


def test_srgb_icc_is_recorded_and_applied(srgb_icc_png):
    loaded = load_image(srgb_icc_png)
    assert loaded.metadata["icc_present"] is True
    assert loaded.metadata["icc_conversion_applied"] is True
    assert loaded.metadata["working_space"] == "sRGB"
    assert loaded.metadata["icc_profile_sha256"]
    assert loaded.metadata["icc_profile_name"]


def test_invalid_icc_degrades_without_crash(invalid_icc_png):
    loaded = load_image(invalid_icc_png)
    assert loaded.metadata["icc_present"] is True
    assert loaded.metadata["icc_conversion_applied"] is False
    assert "失败" in loaded.metadata["icc_note"]


def test_partial_alpha_metadata_and_analysis(partial_alpha_png, tmp_path):
    outputs = run(partial_alpha_png, tmp_path / "out", face_backend="none")
    data = json.loads(outputs["analysis_json"].read_text(encoding="utf-8"))
    assert data["source"]["has_alpha"] is True
    assert 0.66 <= data["source"]["valid_pixel_share"] <= 0.67
    assert 0.32 <= data["source"]["partial_alpha_pixel_share"] <= 0.34
    assert data["skin"]["status"] == "未验证"


def test_webp_metadata(sample_webp):
    loaded = load_image(sample_webp)
    assert loaded.metadata["format"] == "WEBP"
    assert loaded.metadata["working_space"] == "sRGB"
