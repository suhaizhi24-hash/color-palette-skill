#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import rgb2lab

from color_palette.analyzer import analyze
from color_palette.faces import _base_skin_mask
from color_palette.pipeline import run


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _working_image(input_path: Path):
    analysis, loaded, working = analyze(input_path, face_backend="opencv")
    rgb = np.asarray(working, dtype=np.uint8)
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    mask = _base_skin_mask(rgb, lab, np.ones(rgb.shape[:2], dtype=bool))
    return analysis, loaded, working, mask


def _detection_debug(working: Image.Image, skin: dict) -> Image.Image:
    canvas = working.copy()
    draw = ImageDraw.Draw(canvas)
    for candidate in skin["diagnostics"]["face_candidates"]:
        x, y, width, height = candidate["box"]
        color = "#18A558" if candidate["accepted"] else "#D83A3A"
        draw.rectangle((x, y, x + width, y + height), outline=color, width=4)
        draw.text(
            (x + 4, max(0, y - 24)),
            f"{candidate['source']} {candidate.get('angle', 0):+} {candidate['reason']}",
            font=_font(18),
            fill=color,
        )
    face_box = skin.get("face_box")
    if face_box:
        x, y, width, height = face_box
        draw.rectangle((x, y, x + width, y + height), outline="#1E66F5", width=5)
    return canvas


def _mask_debug(working: Image.Image, mask: np.ndarray, skin: dict) -> Image.Image:
    base = np.asarray(working, dtype=np.uint8).copy()
    overlay = np.zeros_like(base)
    overlay[..., 1] = 220
    blended = base.copy()
    blended[mask] = (0.55 * base[mask] + 0.45 * overlay[mask]).astype(np.uint8)
    image = Image.fromarray(blended, "RGB")
    draw = ImageDraw.Draw(image)
    face_box = skin.get("face_box")
    if face_box:
        x, y, width, height = face_box
        draw.rectangle((x, y, x + width, y + height), outline="#1E66F5", width=4)
    return image


def _anchor_debug(working: Image.Image, skin: dict) -> Image.Image:
    image = working.copy()
    draw = ImageDraw.Draw(image)
    face_box = skin.get("face_box")
    if face_box:
        x, y, width, height = face_box
        accepted = next(
            (
                item
                for item in skin["diagnostics"]["face_candidates"]
                if item.get("accepted") and item.get("anchor_geometry")
            ),
            None,
        )
        geometry = accepted.get("anchor_geometry", {}) if accepted else {}
        face_width = geometry.get("face_width", width)
        cheek_centers = geometry.get("cheek_centers") or [
            (x + 0.32 * width, y + 0.64 * height),
            (x + 0.68 * width, y + 0.64 * height),
        ]
        forehead_center = geometry.get("forehead_center") or (
            x + 0.50 * width,
            y + 0.20 * height,
        )
        for label, center, radius, color in (
            (
                "苹果肌候选",
                cheek_centers[0],
                (0.115 * face_width, 0.085 * face_width),
                "#FF8C00",
            ),
            (
                "苹果肌候选",
                cheek_centers[1],
                (0.115 * face_width, 0.085 * face_width),
                "#FF8C00",
            ),
            (
                "额头",
                forehead_center,
                (0.14 * face_width, 0.065 * face_width),
                "#8A2BE2",
            ),
        ):
            cx, cy = center
            rx, ry = radius
            draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=color, width=4)
            draw.text((cx - rx, cy + ry + 4), label, font=_font(18), fill=color)
    for key, color in (("primary_anchor", "#FF3B30"), ("secondary_anchor", "#8A2BE2")):
        anchor = skin.get(key)
        if anchor and anchor.get("center"):
            cx, cy = anchor["center"]
            draw.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=color)
    return image


def generate(input_path: Path, output_dir: Path) -> dict:
    input_path = input_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    outputs = run(input_path, output_dir, face_backend="opencv")
    analysis, _, working, mask = _working_image(input_path)
    after = hashlib.sha256(input_path.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("调试流程修改了输入图片")

    debug_files = {
        "skin_detection_debug.png": _detection_debug(working, analysis["skin"]),
        "skin_mask_debug.png": _mask_debug(working, mask, analysis["skin"]),
        "skin_anchor_debug.png": _anchor_debug(working, analysis["skin"]),
    }
    for name, image in debug_files.items():
        image.save(output_dir / name, format="PNG")

    diagnostics = {
        "development_preview": True,
        "input_filename": input_path.name,
        "input_sha256": before,
        "input_unchanged": True,
        "formal_outputs": {key: str(path) for key, path in outputs.items()},
        "skin": analysis["skin"],
    }
    diagnostics_path = output_dir / "skin_diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    skin = analysis["skin"]
    primary = skin.get("primary_anchor") or {}
    secondary = skin.get("secondary_anchor") or {}
    result_path = output_dir / "SKIN_V0151_REAL_REVIEW.md"
    result_path.write_text(
        "\n".join(
            [
                "# v0.15.1 Skin Anchor 本地人工验收",
                "",
                "- development_preview: true",
                f"- 输入 SHA-256: `{before}`",
                "- 输入未修改: PASS",
                f"- 检测后端: `{skin.get('detector')}`",
                f"- recovery_used: `{skin['diagnostics']['recovery_used']}`",
                f"- 苹果肌主锚点: `{primary.get('status_code', 'insufficient')}`",
                f"- 额头副锚点: `{secondary.get('status_code', 'insufficient')}`",
                "- 正式 PNG 不包含人脸框、锚点或内部诊断文案。",
                "- 调试 PNG 仅用于本地 QA，不得提交 Git。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return diagnostics


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="生成仓库外肤色锚点本地 QA 证据")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = generate(Path(args.input), Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
