from __future__ import annotations

from pathlib import Path
import os
import platform

from PIL import Image, ImageDraw, ImageFont

from .constants import (
    FONT_CANDIDATES_BOLD,
    FONT_CANDIDATES_REGULAR,
    REPORT_HEIGHT,
    REPORT_WIDTH,
)
from .errors import RenderError
from .io import LoadedImage, checkerboard_composite


class FontResolver:
    def __init__(self) -> None:
        regular_override = os.getenv("COLOR_PALETTE_FONT_REGULAR")
        bold_override = os.getenv("COLOR_PALETTE_FONT_BOLD")
        self.regular_path = self._resolve(FONT_CANDIDATES_REGULAR, regular_override)
        self.bold_path = self._resolve(FONT_CANDIDATES_BOLD, bold_override or regular_override)

    @staticmethod
    def _resolve(candidates: list[Path], override: str | None = None) -> Path | None:
        if override:
            candidate = Path(override).expanduser()
            if candidate.exists() and candidate.is_file():
                return candidate
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _load(path: Path | None, size: int) -> ImageFont.ImageFont:
        if path is not None:
            return ImageFont.truetype(str(path), size)
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # pragma: no cover - compatibility with older Pillow
            return ImageFont.load_default()

    def regular(self, size: int) -> ImageFont.ImageFont:
        return self._load(self.regular_path, size)

    def bold(self, size: int) -> ImageFont.ImageFont:
        return self._load(self.bold_path, size)

    def metadata(self) -> dict:
        return {
            "preferred": "PingFang SC（苹方简）",
            "runtime_regular": (
                self.regular_path.name if self.regular_path else "Pillow内置紧急回退"
            ),
            "runtime_bold": (
                self.bold_path.name if self.bold_path else "Pillow内置紧急回退"
            ),
            "fallback_active": not self.regular_path
            or "PingFang" not in self.regular_path.name,
            "emergency_fallback": self.regular_path is None or self.bold_path is None,
            "platform": platform.system(),
        }


def render_report(analysis: dict, loaded: LoadedImage, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fonts = FontResolver()
    canvas = Image.new("RGB", (REPORT_WIDTH, REPORT_HEIGHT), "#F6F5F2")
    draw = ImageDraw.Draw(canvas)

    _header(draw, fonts, analysis)
    _top_area(canvas, draw, fonts, analysis, loaded)
    _palette(draw, fonts, analysis)
    _bottom(canvas, draw, fonts, analysis, loaded)

    try:
        canvas.save(output, format="PNG", optimize=True)
    except OSError as exc:
        raise RenderError(f"PNG报告保存失败：{output}") from exc
    return output


def _rounded(draw: ImageDraw.ImageDraw, box, fill="#FFFFFF", outline="#DADDDD", radius=18, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in str(text):
        candidate = current + character
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = character
    if current:
        lines.append(current)
    return lines


def _header(draw, fonts: FontResolver, analysis: dict) -> None:
    draw.text((42, 27), "调色盘/色彩卡片", font=fonts.bold(36), fill="#202426")
    source = analysis["source"]
    meta = f"{source['filename']} · {source['width']}×{source['height']}"
    width = draw.textbbox((0, 0), meta, font=fonts.regular(14))[2]
    draw.text((REPORT_WIDTH - 42 - width, 42), meta, font=fonts.regular(14), fill="#6C7376")


def _top_area(canvas, draw, fonts, analysis, loaded) -> None:
    top_y, top_h = 88, 495
    photo_box = (42, top_y, 565, top_y + top_h)
    _rounded(draw, photo_box)
    _paste_photo(canvas, loaded, analysis, photo_box)

    report = analysis["official_report"]
    right_x, gap = 585, 14
    card_width = (REPORT_WIDTH - 42 - right_x - gap) // 2
    card_height = (top_h - gap) // 2
    _analysis_card(draw, fonts, (right_x, top_y, right_x + card_width, top_y + card_height), "影调结构", report["影调结构"])
    _analysis_card(draw, fonts, (right_x + card_width + gap, top_y, REPORT_WIDTH - 42, top_y + card_height), "明暗关系", report["明暗关系"])
    _analysis_card(draw, fonts, (right_x, top_y + card_height + gap, right_x + card_width, top_y + top_h), "色彩浓度", report["色彩浓度"])
    _analysis_card(draw, fonts, (right_x + card_width + gap, top_y + card_height + gap, REPORT_WIDTH - 42, top_y + top_h), "白平衡&色相", report["白平衡&色相"])


def _paste_photo(canvas, loaded, analysis, box) -> None:
    source = checkerboard_composite(loaded.display_image)
    x1, y1, x2, y2 = box
    inner_width, inner_height = x2 - x1 - 14, y2 - y1 - 14
    orientation = analysis["source"]["orientation"]
    if orientation == "landscape":
        resized = _cover_crop(source, (inner_width, inner_height), analysis)
        canvas.paste(resized, (x1 + 7, y1 + 7))
    else:
        ratio = min(inner_width / source.width, inner_height / source.height)
        size = (max(1, int(source.width * ratio)), max(1, int(source.height * ratio)))
        resized = source.resize(size, Image.Resampling.LANCZOS)
        px = x1 + 7 + (inner_width - size[0]) // 2
        py = y1 + 7 + (inner_height - size[1]) // 2
        canvas.paste(resized, (px, py))


def _cover_crop(image: Image.Image, size: tuple[int, int], analysis: dict) -> Image.Image:
    width, height = size
    ratio = max(width / image.width, height / image.height)
    resized_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
    resized = image.resize(resized_size, Image.Resampling.LANCZOS)
    focus_x, focus_y = resized.width / 2, resized.height / 2
    skin = analysis.get("skin", {})
    face_box = skin.get("face_box")
    if face_box:
        x, y, w, h = face_box
        analysis_width = analysis["analysis"]["working_width"]
        analysis_height = analysis["analysis"]["working_height"]
        source_x = (x + w / 2) / analysis_width * image.width
        source_y = (y + h / 2) / analysis_height * image.height
        focus_x = source_x * ratio
        focus_y = source_y * ratio
    left = int(round(focus_x - width / 2))
    top = int(round(focus_y - height / 2))
    left = max(0, min(left, resized.width - width))
    top = max(0, min(top, resized.height - height))
    return resized.crop((left, top, left + width, top + height))


def _analysis_card(draw, fonts, box, title: str, items: list[str]) -> None:
    _rounded(draw, box)
    x1, y1, x2, _ = box
    draw.text((x1 + 18, y1 + 14), title, font=fonts.bold(22), fill="#202426")
    y = y1 + 60
    for index, text in enumerate(items):
        draw.ellipse((x1 + 20, y + 9, x1 + 27, y + 16), fill="#74817B")
        font = fonts.bold(16) if index == 0 else fonts.regular(16)
        for line in _wrap(draw, text, font, x2 - x1 - 66)[:3]:
            draw.text((x1 + 39, y), line, font=font, fill="#3F474A")
            y += 28
        y += 16


def _palette(draw, fonts, analysis) -> None:
    palette_y, palette_bottom = 598, 824
    _rounded(draw, (42, palette_y, REPORT_WIDTH - 42, palette_bottom))
    draw.text((58, palette_y + 14), "影调色卡", font=fonts.bold(21), fill="#202426")
    draw.text((158, palette_y + 19), "基于 L* 亮度区间提取真实像素", font=fonts.regular(13), fill="#73797B")

    palette = analysis["official_report"]["影调色卡"]
    start_x, gap, top = 58, 24, palette_y + 52
    bottom = palette_bottom - 14
    card_width = (REPORT_WIDTH - 116 - 4 * gap) // 5
    for index, item in enumerate(palette):
        x = start_x + index * (card_width + gap)
        _rounded(draw, (x, top, x + card_width, bottom), fill="#FBFBFA", outline="#E3E6E6", radius=12)
        rgb = tuple(item["rgb"])
        draw.rounded_rectangle((x + 10, top + 10, x + card_width - 10, top + 65), radius=9, fill=rgb)
        lightness = item["lab"]["l"]
        title_color = "#FFFFFF" if lightness < 52 else "#222222"
        draw.text((x + 20, top + 26), item["role"], font=fonts.bold(16), fill=title_color)
        draw.text((x + 14, top + 80), f"RGB {rgb[0]}, {rgb[1]}, {rgb[2]}", font=fonts.regular(12), fill="#495155")
        draw.text((x + 14, top + 107), f"HEX {item['hex']}  ·  L* {lightness:.1f}", font=fonts.regular(12), fill="#495155")
        draw.text((x + 14, top + 134), f"区间占比 {item['band_share'] * 100:.1f}%", font=fonts.regular(12), fill="#687073")


def _bottom(canvas, draw, fonts, analysis, loaded) -> None:
    bottom_y, bottom_bottom = 840, 1158
    skin_box = (42, bottom_y, 930, bottom_bottom)
    combined_box = (944, bottom_y, REPORT_WIDTH - 42, bottom_bottom)
    _rounded(draw, skin_box)
    _rounded(draw, combined_box)
    _skin_module(canvas, draw, fonts, analysis, loaded, skin_box)
    _effects_light(draw, fonts, analysis, combined_box)


def _skin_module(canvas, draw, fonts, analysis, loaded, box) -> None:
    x1, y1, _, y2 = box
    draw.text((x1 + 18, y1 + 15), "肤色锚点", font=fonts.bold(21), fill="#202426")
    skin = analysis["skin"]
    if skin["status"] != "单人":
        message = analysis["official_report"]["肤色锚点"][0]
        y = y1 + 88
        for line in _wrap(draw, message, fonts.regular(17), 790)[:4]:
            draw.text((x1 + 24, y), line, font=fonts.regular(17), fill="#4B5355")
            y += 31
        return

    entries = [
        ("① 苹果肌主锚点", skin.get("primary_anchor")),
        ("② 额头副锚点", skin.get("secondary_anchor")),
    ]
    crop_size = (138, 138)
    column_width = 415
    for index, (label, anchor) in enumerate(entries):
        column_x = x1 + 18 + index * (column_width + 18)
        if index == 1:
            draw.line((column_x - 12, y1 + 56, column_x - 12, y2 - 18), fill="#E0E3E3", width=1)
        draw.text((column_x, y1 + 60), label, font=fonts.bold(17), fill="#303638")
        crop_y = y1 + 98
        if anchor and anchor.get("status") == "有效" and anchor.get("source_crop"):
            crop = _source_crop(loaded, anchor["source_crop"])
            crop = _rounded_crop(crop, crop_size)
            canvas.paste(crop, (column_x, crop_y))
            text_x = column_x + crop_size[0] + 16
            draw.text((text_x, crop_y + 1), f"RGB {', '.join(map(str, anchor['rgb']))}", font=fonts.regular(14), fill="#465052")
            draw.text((text_x, crop_y + 29), f"HEX {anchor['hex']}", font=fonts.regular(14), fill="#465052")
            draw.text((text_x, crop_y + 57), f"L* {anchor['lab']['l']:.1f}", font=fonts.regular(14), fill="#465052")
            draw.text((text_x, crop_y + 83), f"a* {anchor['lab']['a']:.1f}", font=fonts.regular(14), fill="#465052")
            draw.text((text_x, crop_y + 109), f"b* {anchor['lab']['b']:.1f}", font=fonts.regular(14), fill="#465052")
        else:
            _rounded(draw, (column_x, crop_y, column_x + crop_size[0], crop_y + crop_size[1]), fill="#F0F1EF")
            draw.text((column_x + 27, crop_y + 56), "样本不足", font=fonts.bold(16), fill="#8A8F91")


def _source_crop(loaded: LoadedImage, spec: dict) -> Image.Image:
    image = checkerboard_composite(loaded.display_image)
    x, y = int(spec["x"]), int(spec["y"])
    width, height = int(spec["width"]), int(spec["height"])
    x = max(0, min(x, image.width - 1))
    y = max(0, min(y, image.height - 1))
    width = max(1, min(width, image.width - x))
    height = max(1, min(height, image.height - y))
    return image.crop((x, y, x + width, y + height))


def _rounded_crop(image: Image.Image, size: tuple[int, int], radius: int = 14) -> Image.Image:
    resized = image.resize(size, Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    output = Image.new("RGB", size, "#F1F1EF")
    output.paste(resized, (0, 0), mask)
    return output


def _effects_light(draw, fonts, analysis, box) -> None:
    x1, y1, x2, y2 = box
    report = analysis["official_report"]["素材特效&光线构成"]
    draw.text((x1 + 18, y1 + 15), "素材特效&光线构成", font=fonts.bold(21), fill="#202426")
    divider_x = x1 + 319
    draw.line((divider_x, y1 + 54, divider_x, y2 - 18), fill="#E0E3E3", width=1)

    draw.text((x1 + 21, y1 + 57), "素材特效", font=fonts.bold(17), fill="#4F6E59")
    y = y1 + 98
    labels = report["素材特效"].get("标签") or [report["素材特效"]["结论"]]
    for label in labels[:5]:
        for line in _wrap(draw, label, fonts.regular(15), 270)[:2]:
            draw.text((x1 + 26, y), line, font=fonts.regular(15), fill="#4B5355")
            y += 27

    draw.text((divider_x + 19, y1 + 57), "光线构成", font=fonts.bold(17), fill="#625746")
    y = y1 + 105
    for key in ["光源", "光质", "光比"]:
        draw.text((divider_x + 21, y), f"{key}：{report['光线构成'][key]}", font=fonts.regular(16), fill="#4B5355")
        y += 45
