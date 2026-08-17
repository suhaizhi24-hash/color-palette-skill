from color_palette.rules import (
    contrast_level,
    saturation_level,
    tone_code,
    white_balance_judgement,
)


def test_bright_region_alone_does_not_force_high_key():
    code, label = tone_code(
        {"shadows": 0.40, "midtones": 0.24, "highlights": 0.36},
        51.0,
    )
    assert (code, label) == ("mid_key", "中间调结构")


def test_bright_median_is_high_key():
    assert tone_code(
        {"shadows": 0.31, "midtones": 0.28, "highlights": 0.41},
        64.0,
    )[0] == "high_key"


def test_low_key_requires_real_shadow_weight():
    assert tone_code(
        {"shadows": 0.56, "midtones": 0.32, "highlights": 0.12},
        38.0,
    )[0] == "low_key"


def test_contrast_thresholds():
    assert contrast_level(49.9) == "低"
    assert contrast_level(50.0) == "中"
    assert contrast_level(70.0) == "高"


def test_saturation_thresholds():
    assert saturation_level(0.199) == "低"
    assert saturation_level(0.20) == "中"
    assert saturation_level(0.45) == "高"


def test_white_balance_requires_spatial_coverage():
    status, text = white_balance_judgement(0.12, 0.125, -3.0, -4.0)
    assert status == "中性色不足"
    assert "暂不下确定结论" in text


def test_white_balance_valid_when_distributed():
    status, text = white_balance_judgement(0.12, 0.50, -3.0, -4.0)
    assert status == "有效"
    assert "偏绿" in text and "偏冷蓝" in text
