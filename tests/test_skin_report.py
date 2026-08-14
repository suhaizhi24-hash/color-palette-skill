from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from color_palette.copy import official_report
from color_palette.io import LoadedImage
import color_palette.render as report_render


PHOTO_INNER_BOX = (49, 95, 558, 576)
PRIMARY_CROP_CENTER = (129, 1007)
SECONDARY_CROP_CENTER = (562, 1007)


def _anchor(
    rgb: tuple[int, int, int],
    crop: tuple[int, int, int],
    *,
    status: str = "有效",
    confidence: float = 0.95,
) -> dict:
    x, y, side = crop
    return {
        "status": status,
        "confidence": confidence,
        "rgb": list(rgb),
        "hex": "#" + "".join(f"{value:02X}" for value in rgb),
        "lab": {"l": 62.0, "a": 9.0, "b": 12.0},
        "source_crop": {
            "x": x,
            "y": y,
            "width": side,
            "height": side,
            "ratio": "1:1",
        },
    }


def _analysis(skin: dict, *, width: int = 640, height: int = 480) -> dict:
    palette = [
        {
            "role": role,
            "status": "有效",
            "rgb": [value, value, value],
            "hex": f"#{value:02X}{value:02X}{value:02X}",
            "lab": {"l": float(index * 20 + 10), "a": 0.0, "b": 0.0},
            "band_share": 0.2,
        }
        for index, (role, value) in enumerate(
            [("深黑", 25), ("阴影", 65), ("中间调", 120), ("亮部", 185), ("高光", 235)]
        )
    ]
    analysis = {
        "source": {
            "filename": "synthetic.png",
            "width": width,
            "height": height,
            "orientation": "landscape",
        },
        "analysis": {"working_width": width, "working_height": height},
        "tone": {
            "code": "mid_key",
            "clipping": {"black_class": "无", "white_class": "无"},
        },
        "contrast": {
            "level": "中",
            "description": "明暗层次清晰，整体反差保持适中。",
        },
        "saturation": {
            "level": "中",
            "description": "综合色彩关系自然稳定，主色清晰但不过分浓烈。",
        },
        "white_balance": {"judgement": "接近中性"},
        "tonal_regions": [
            {"role": "暗部", "hue": "蓝"},
            {"role": "中间调", "hue": "橙黄"},
            {"role": "高光", "hue": "中性灰"},
        ],
        "tonal_palette": palette,
        "skin": skin,
        "effects": {
            "detected": [],
            "not_obvious": [],
            "conclusion": "未识别到可稳定确认的素材特效。",
        },
        "light": {"source": "暂不判定", "quality": "暂不判定", "ratio": "中"},
    }
    analysis["official_report"] = official_report(analysis)
    return analysis


def _loaded(image: Image.Image, tmp_path: Path) -> LoadedImage:
    rgb = image.convert("RGB")
    return LoadedImage(
        path=tmp_path / "synthetic.png",
        display_image=rgb,
        rgb_image=rgb,
        rgba_image=None,
        valid_mask=np.ones((rgb.height, rgb.width), dtype=bool),
        metadata={},
    )


def _single_skin(primary: dict, secondary: dict) -> dict:
    return {
        "status": "单人",
        "face_count": 1,
        "face_box": [180, 90, 220, 260],
        "primary_anchor": primary,
        "secondary_anchor": secondary,
    }


def test_single_person_report_renders_two_one_to_one_source_crops(monkeypatch, tmp_path):
    primary_rgb = (214, 86, 72)
    secondary_rgb = (72, 158, 102)
    image = Image.new("RGB", (640, 480), (48, 62, 78))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 79, 79), fill=primary_rgb)
    draw.rectangle((120, 30, 169, 79), fill=secondary_rgb)
    primary = _anchor(primary_rgb, (20, 20, 60))
    secondary = _anchor(secondary_rgb, (120, 30, 50))
    analysis = _analysis(_single_skin(primary, secondary))

    source_crop_sizes: list[tuple[int, int]] = []
    display_sizes: list[tuple[int, int]] = []
    original_source_crop = report_render._source_crop
    original_rounded_crop = report_render._rounded_crop

    def traced_source_crop(loaded, spec):
        crop = original_source_crop(loaded, spec)
        source_crop_sizes.append(crop.size)
        return crop

    def traced_rounded_crop(crop, size, radius=14):
        display_sizes.append(size)
        return original_rounded_crop(crop, size, radius)

    monkeypatch.setattr(report_render, "_source_crop", traced_source_crop)
    monkeypatch.setattr(report_render, "_rounded_crop", traced_rounded_crop)

    output = report_render.render_report(
        analysis,
        _loaded(image, tmp_path),
        tmp_path / "single_color_report.png",
    )

    assert source_crop_sizes == [(60, 60), (50, 50)]
    assert all(width == height for width, height in source_crop_sizes)
    assert display_sizes == [(138, 138), (138, 138)]
    with Image.open(output) as report:
        assert report.size == (1600, 1200)
        assert report.getpixel(PRIMARY_CROP_CENTER) == primary_rgb
        assert report.getpixel(SECONDARY_CROP_CENTER) == secondary_rgb


def test_multi_person_report_never_renders_a_merged_skin_crop(monkeypatch, tmp_path):
    skin = {
        "status": "多人不合并",
        "face_count": 2,
        "primary_anchor": _anchor((210, 150, 130), (20, 20, 60)),
        "secondary_anchor": _anchor((205, 145, 125), (120, 30, 50)),
    }
    analysis = _analysis(skin)
    drawn_text: list[str] = []
    original_text = ImageDraw.ImageDraw.text

    def traced_text(draw, xy, text, *args, **kwargs):
        drawn_text.append(str(text))
        return original_text(draw, xy, text, *args, **kwargs)

    def reject_crop(*args, **kwargs):
        raise AssertionError("多人报告不得读取或渲染合并肤色截图")

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", traced_text)
    monkeypatch.setattr(report_render, "_source_crop", reject_crop)
    report_render.render_report(
        analysis,
        _loaded(Image.new("RGB", (640, 480), (80, 90, 100)), tmp_path),
        tmp_path / "multiple_color_report.png",
    )

    visible_text = "".join(drawn_text)
    assert "多人物肤色不合并" in visible_text
    assert "苹果肌主锚点" not in visible_text
    assert "额头副锚点" not in visible_text


def test_low_confidence_skin_is_rendered_as_insufficient_sample(monkeypatch, tmp_path):
    primary = _anchor(
        (210, 150, 130),
        (20, 20, 60),
        status="仅供参考",
        confidence=0.69,
    )
    secondary = _anchor(
        (205, 145, 125),
        (120, 30, 50),
        status="样本不足",
        confidence=0.62,
    )
    analysis = _analysis(_single_skin(primary, secondary))
    drawn_text: list[str] = []
    original_text = ImageDraw.ImageDraw.text

    def traced_text(draw, xy, text, *args, **kwargs):
        drawn_text.append(str(text))
        return original_text(draw, xy, text, *args, **kwargs)

    def reject_crop(*args, **kwargs):
        raise AssertionError("低置信度锚点不得渲染数值或像素截图")

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", traced_text)
    monkeypatch.setattr(report_render, "_source_crop", reject_crop)
    report_render.render_report(
        analysis,
        _loaded(Image.new("RGB", (640, 480), (80, 90, 100)), tmp_path),
        tmp_path / "insufficient_color_report.png",
    )

    assert drawn_text.count("样本不足") == 2
    assert all("样本不足" in line for line in analysis["official_report"]["肤色锚点"])


def test_original_photo_region_has_no_anchor_or_face_overlays(tmp_path):
    source_color = (37, 113, 151)
    primary = _anchor(source_color, (20, 20, 60))
    secondary = _anchor(source_color, (120, 30, 50))
    analysis = _analysis(_single_skin(primary, secondary))
    output = report_render.render_report(
        analysis,
        _loaded(Image.new("RGB", (640, 480), source_color), tmp_path),
        tmp_path / "clean_original_color_report.png",
    )

    with Image.open(output) as report:
        displayed_photo = report.crop(PHOTO_INNER_BOX)
        assert displayed_photo.size == (509, 481)
        assert displayed_photo.getcolors(maxcolors=2) == [
            (displayed_photo.width * displayed_photo.height, source_color)
        ]
