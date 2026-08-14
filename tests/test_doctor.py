import json

import pytest
from PIL import Image, ImageDraw

from color_palette.doctor import collect_diagnostics
from color_palette.constants import FONT_CANDIDATES_BOLD, FONT_CANDIDATES_REGULAR
from color_palette.render import FontResolver
from color_palette.pipeline import run


def test_doctor_reports_zero_token_and_output_contract():
    result = collect_diagnostics()
    assert result["zero_token"] is True
    assert result["official_output"] == ["analysis.json", "color_report.png"]
    assert "opencv" in result["face_backends"]
    assert result["font"]["cjk_available"] is result["font"]["ok"]
    assert result["font"]["status"] in {
        "可用",
        "紧急回退（未找到可用中文字体）",
    }


def test_missing_fonts_do_not_block_report(monkeypatch):
    monkeypatch.setattr(
        FontResolver,
        "_resolve",
        staticmethod(lambda candidates, override=None: None),
    )
    resolver = FontResolver()
    assert resolver.regular(16) is not None
    assert resolver.bold(16) is not None
    assert resolver.metadata()["emergency_fallback"] is True


def test_doctor_reports_missing_cjk_font_without_blocking(monkeypatch):
    monkeypatch.setattr(
        FontResolver,
        "_resolve",
        staticmethod(lambda candidates, override=None: None),
    )
    result = collect_diagnostics()
    assert result["font"]["ok"] is False
    assert result["font"]["cjk_available"] is False
    assert result["font"]["emergency_fallback"] is True
    assert result["font"]["status"] == "紧急回退（未找到可用中文字体）"
    assert result["status"] == "通过"


@pytest.mark.parametrize(
    "candidates",
    [FONT_CANDIDATES_REGULAR, FONT_CANDIDATES_BOLD],
)
def test_official_font_fallbacks_precede_os_last_resorts(candidates):
    names = [path.name.casefold() for path in candidates]
    first_noto = next(index for index, name in enumerate(names) if "noto" in name)
    first_source_han = next(
        index for index, name in enumerate(names) if "sourcehansans" in name
    )
    first_os_last_resort = next(
        index
        for index, name in enumerate(names)
        if any(token in name for token in ("hiragino", "stheiti", "msyh", "simhei"))
    )
    assert first_noto < first_os_last_resort
    assert first_source_han < first_os_last_resort


def test_missing_fonts_still_write_png_and_json(monkeypatch, gradient_jpg, tmp_path):
    monkeypatch.setattr(
        FontResolver,
        "_resolve",
        staticmethod(lambda candidates, override=None: None),
    )
    outputs = run(gradient_jpg, tmp_path / "fallback", face_backend="none")
    assert outputs["analysis_json"].exists()
    assert outputs["color_report_png"].exists()
    data = json.loads(outputs["analysis_json"].read_text(encoding="utf-8"))
    assert data["font_policy"]["emergency_fallback"] is True
    with Image.open(outputs["color_report_png"]) as report:
        assert report.size == (1600, 1200)
        assert report.format == "PNG"


def test_available_cjk_font_renders_distinct_chinese_glyphs():
    resolver = FontResolver()
    if resolver.regular_path is None:
        pytest.skip("系统没有可用的 CJK 字体；紧急回退由独立测试覆盖")

    font = resolver.regular(40)

    def glyph_signature(character: str) -> bytes:
        canvas = Image.new("L", (72, 72), 0)
        ImageDraw.Draw(canvas).text((4, 4), character, font=font, fill=255)
        return canvas.tobytes()

    signatures = [glyph_signature(character) for character in "调色盘肤锚"]
    assert all(any(signature) for signature in signatures)
    # 缺失字形通常会回退为同一个 tofu 方框；不同签名证明实际使用了中文字形。
    assert len(set(signatures)) == len(signatures)
