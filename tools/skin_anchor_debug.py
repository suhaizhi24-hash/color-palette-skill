#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import rgb2lab

from color_palette.analyzer import analyze
from color_palette.faces import (
    _base_skin_mask,
    _oriented_ellipse_mask,
    _robust_sample_masks,
)
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
    return analysis, loaded, working, lab, mask


def _detection_debug(working: Image.Image, skin: dict) -> Image.Image:
    canvas = working.copy()
    draw = ImageDraw.Draw(canvas)
    diagnostics = skin["diagnostics"]
    summary = (
        f"raw={diagnostics.get('raw_face_candidate_count', len(diagnostics['face_candidates']))} "
        f"valid={diagnostics.get('valid_face_count', skin.get('face_count', 0))} "
        f"decision={diagnostics.get('skin_output_decision', 'legacy')}"
    )
    draw.rectangle((8, 8, min(canvas.width - 8, 760), 42), fill="#FFFFFF")
    draw.text((14, 12), summary, font=_font(18), fill="#202124")
    for candidate in skin["diagnostics"]["face_candidates"]:
        x, y, width, height = candidate["box"]
        color = "#18A558" if candidate["accepted"] else "#D83A3A"
        draw.rectangle((x, y, x + width, y + height), outline=color, width=4)
        candidate_id = candidate.get("candidate_id", "candidate")
        draw.text(
            (x + 4, max(0, y - 24)),
            (f"{candidate_id} score={candidate['score']:.3f} {candidate['reason']}"),
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


def _anchor_geometry(skin: dict) -> tuple[dict, int, float]:
    x, y, width, _ = skin["face_box"]
    accepted = next(
        (
            item
            for item in skin["diagnostics"]["face_candidates"]
            if item.get("accepted") and item.get("anchor_geometry")
        ),
        None,
    )
    geometry = accepted.get("anchor_geometry", {}) if accepted else {}
    geometry.setdefault(
        "cheek_centers",
        [[x + 0.32 * width, y + 0.64 * width], [x + 0.68 * width, y + 0.64 * width]],
    )
    geometry.setdefault("forehead_center", [x + 0.50 * width, y + 0.20 * width])
    return (
        geometry,
        int(geometry.get("face_width", width)),
        float(geometry.get("orientation_degrees", 0.0)),
    )


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _anchor_debug_panel(
    working: Image.Image,
    lab: np.ndarray,
    skin_mask: np.ndarray,
    skin: dict,
    *,
    anchor_name: str,
) -> Image.Image:
    anchor = skin.get(anchor_name) or {}
    geometry, face_width, orientation = _anchor_geometry(skin)
    if anchor_name == "primary_anchor":
        side = anchor.get("side", "左侧")
        center = (
            anchor.get("center")
            or geometry["cheek_centers"][0 if side == "左侧" else 1]
        )
        rx, ry = 0.115 * face_width, 0.085 * face_width
        orientation = float(geometry.get("cheek_orientation_degrees", orientation))
        title = "苹果肌主锚点"
    else:
        center = anchor.get("center") or geometry["forehead_center"]
        rx, ry = 0.14 * face_width, 0.065 * face_width
        orientation = float(geometry.get("forehead_orientation_degrees", orientation))
        title = "额头副锚点"
    roi = _oriented_ellipse_mask(
        lab.shape[:2], center[0], center[1], rx, ry, orientation
    )
    target, accepted = _robust_sample_masks(lab, skin_mask, roi)
    rejected = roi & ~accepted

    base = np.asarray(working, dtype=np.uint8)
    overlay = base.copy()
    overlay[rejected] = (
        0.52 * base[rejected] + 0.48 * np.array([230, 55, 55], dtype=np.float32)
    ).astype(np.uint8)
    overlay[accepted] = (
        0.45 * base[accepted] + 0.55 * np.array([40, 210, 95], dtype=np.float32)
    ).astype(np.uint8)

    left, top, right, bottom = _mask_bbox(roi)
    pad = max(24, int(round(face_width * 0.16)))
    left, top = max(0, left - pad), max(0, top - pad)
    right, bottom = min(working.width, right + pad), min(working.height, bottom + pad)
    original_crop = Image.fromarray(base[top:bottom, left:right], "RGB")
    overlay_crop = Image.fromarray(overlay[top:bottom, left:right], "RGB")

    panel_size = 520
    original_crop = original_crop.resize(
        (panel_size, panel_size), Image.Resampling.LANCZOS
    )
    overlay_crop = overlay_crop.resize(
        (panel_size, panel_size), Image.Resampling.LANCZOS
    )
    canvas = Image.new("RGB", (1120, 700), "#F7F7F5")
    canvas.paste(original_crop, (30, 140))
    canvas.paste(overlay_crop, (570, 140))
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 20), title, font=_font(30), fill="#202124")
    skin_share = float(target.sum() / max(int(roi.sum()), 1))
    accepted_share = float(accepted.sum() / max(int(roi.sum()), 1))
    draw.text(
        (30, 66),
        (
            f"ROI center=({center[0]:.2f}, {center[1]:.2f})  "
            f"skin pixel share={skin_share:.3f}  accepted={accepted_share:.3f}"
        ),
        font=_font(20),
        fill="#4B5563",
    )
    draw.text((30, 110), "原图局部", font=_font(21), fill="#202124")
    draw.text(
        (570, 110),
        "绿色=最终采样像素｜红色=ROI 内拒绝像素",
        font=_font(21),
        fill="#202124",
    )

    scale_x = panel_size / max(right - left, 1)
    scale_y = panel_size / max(bottom - top, 1)
    cx = 570 + (center[0] - left) * scale_x
    cy = 140 + (center[1] - top) * scale_y
    draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill="#2563EB")
    crop = anchor.get("crop") or {}
    if crop:
        x1 = 570 + (crop["x"] - left) * scale_x
        y1 = 140 + (crop["y"] - top) * scale_y
        x2 = x1 + crop["width"] * scale_x
        y2 = y1 + crop["height"] * scale_y
        draw.rectangle((x1, y1, x2, y2), outline="#FACC15", width=4)
    draw.text(
        (570, 665),
        "蓝点=ROI center｜黄框=正式 1:1 原始像素取样截图范围",
        font=_font(18),
        fill="#4B5563",
    )
    return canvas


def generate(input_path: Path, output_dir: Path) -> dict:
    input_path = input_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    outputs = run(input_path, output_dir, face_backend="opencv")
    analysis, _, working, lab, mask = _working_image(input_path)
    after = hashlib.sha256(input_path.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("调试流程修改了输入图片")

    skin = analysis["skin"]
    detection_debug = _detection_debug(working, skin)
    mask_debug = _mask_debug(working, mask, skin)
    debug_files = {
        "face_detection_debug.png": detection_debug,
        "skin_candidate_mask.png": mask_debug,
        "primary_anchor_debug.png": _anchor_debug_panel(
            working, lab, mask, skin, anchor_name="primary_anchor"
        ),
        "secondary_anchor_debug.png": _anchor_debug_panel(
            working, lab, mask, skin, anchor_name="secondary_anchor"
        ),
        "skin_detection_debug.png": detection_debug.copy(),
        "skin_mask_debug.png": mask_debug.copy(),
        "skin_anchor_debug.png": _anchor_debug(working, skin),
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
    parser = argparse.ArgumentParser(description="生成仓库外肤色锚点本地 QA 证据")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = generate(Path(args.input), Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
