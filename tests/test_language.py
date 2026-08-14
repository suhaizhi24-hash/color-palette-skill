import pytest

from color_palette.copy import official_report
from color_palette.cli import build_parser as build_main_parser
from color_palette.doctor import build_parser as build_doctor_parser
from color_palette.golden_cli import build_parser as build_golden_parser


def _visible_text(value):
    if isinstance(value, dict):
        return " ".join(_visible_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_visible_text(item) for item in value)
    return str(value)


def test_required_phrases():
    analysis = {
        "tone": {"code": "mid_key", "clipping": {"black_class": "无", "white_class": "无"}},
        "contrast": {"level": "高", "description": "x"},
        "saturation": {"level": "高", "description": "y"},
        "white_balance": {"judgement": "接近中性"},
        "tonal_regions": [{"role": "暗部", "hue": "蓝"}, {"role": "中间调", "hue": "橙黄"}, {"role": "高光", "hue": "中性灰"}],
        "tonal_palette": [],
        "skin": {"status": "无人像", "face_count": 0},
        "effects": {"detected": [], "not_obvious": [], "conclusion": "未识别到可稳定确认的素材特效。"},
        "light": {"source": "暂不判定", "quality": "暂不判定", "ratio": "高"},
    }
    report = official_report(analysis)
    assert report["明暗关系"][0] == "明暗关系大，对比度高。"
    assert report["色彩浓度"][0] == "色彩饱和度高。"
    assert "样本不足" in report["肤色锚点"][0]
    visible = _visible_text(report)
    for forbidden in ["依据", "数据依据", "内部状态", "Schema", "研发说明", "算法降级说明"]:
        assert forbidden not in visible


@pytest.mark.parametrize(
    ("contrast", "expected"),
    [
        ("低", "明暗关系小，对比度低。"),
        ("中", "明暗关系中等，对比度中。"),
        ("高", "明暗关系大，对比度高。"),
    ],
)
def test_all_official_contrast_phrases(contrast, expected):
    analysis = _minimal_analysis(contrast=contrast, saturation="中")
    assert official_report(analysis)["明暗关系"][0] == expected


@pytest.mark.parametrize("saturation", ["低", "中", "高"])
def test_all_official_saturation_phrases(saturation):
    analysis = _minimal_analysis(contrast="中", saturation=saturation)
    assert official_report(analysis)["色彩浓度"][0] == f"色彩饱和度{saturation}。"


def _minimal_analysis(*, contrast: str, saturation: str) -> dict:
    return {
        "tone": {
            "code": "mid_key",
            "clipping": {"black_class": "无", "white_class": "无"},
        },
        "contrast": {"level": contrast, "description": "明暗描述。"},
        "saturation": {"level": saturation, "description": "色彩描述。"},
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


def test_cli_help_uses_chinese_headings():
    for parser in [build_main_parser(), build_doctor_parser(), build_golden_parser()]:
        help_text = parser.format_help()
        assert "用法：" in help_text
        assert "选项：" in help_text
        assert "usage:" not in help_text
        assert "options:" not in help_text
        assert "show this help message and exit" not in help_text
    assert "show program's version number and exit" not in build_main_parser().format_help()
    assert "显示版本号并退出" in build_main_parser().format_help()
