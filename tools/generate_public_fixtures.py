#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageCms, ImageDraw

from color_palette.argparse_zh import configure_utf8_stdio

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "public"
OUT.mkdir(parents=True, exist_ok=True)
PROVENANCE_PATH = ROOT / "examples" / "public_examples_provenance.json"
FIXED_PUBLIC_FIXTURE_PATHS = (
    "examples/synthetic_portrait.png",
    "examples/output_v013/synthetic_portrait_color_report.png",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_fixed_public_fixture(relative: str, expected_sha256: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        raise RuntimeError(f"固定公开合成样例不存在：{relative}")
    actual = sha256(path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"固定公开合成样例哈希不一致，拒绝自动登记：{relative}"
        )
    return path


def load_reviewed_provenance() -> dict[str, dict]:
    """Read the human-reviewed registry; this generator never writes it."""

    try:
        document = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("独立公开样例来源登记表无法读取") from exc
    if (
        not isinstance(document, dict)
        or document.get("review_policy") != "人工审核固定来源"
        or document.get("generated_by_tool") is not False
    ):
        raise RuntimeError("独立公开样例来源登记表未经人工固定审核")
    entries: dict[str, dict] = {}
    for item in document.get("files", []):
        if not isinstance(item, dict) or item.get("reviewed") is not True:
            raise RuntimeError("独立公开样例来源登记项缺少人工审核标记")
        relative = item.get("path")
        digest = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise RuntimeError("独立公开样例来源登记项无效")
        if relative in entries:
            raise RuntimeError(f"独立来源登记表包含重复路径：{relative}")
        entries[relative] = item
    return entries


def save_exif_orientation() -> Path:
    # Stored pixels are landscape, EXIF 6 requests a 90° clockwise display.
    image = Image.new("RGB", (240, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 80, 140), fill=(220, 40, 40))
    draw.rectangle((80, 0, 160, 140), fill=(40, 180, 80))
    draw.rectangle((160, 0, 240, 140), fill=(40, 100, 220))
    exif = Image.Exif()
    exif[274] = 6
    path = OUT / "synthetic_exif_orientation.jpg"
    image.save(path, quality=95, exif=exif)
    return path


def save_transparent() -> Path:
    array = np.zeros((240, 320, 4), dtype=np.uint8)
    array[:, :160, :3] = (255, 0, 0)  # hidden RGB must never affect analysis
    array[:, :160, 3] = 0
    array[:, 160:, :3] = (30, 95, 220)
    array[:, 160:, 3] = 255
    path = OUT / "synthetic_transparent.png"
    Image.fromarray(array, "RGBA").save(path)
    return path


def save_icc() -> Path:
    image = Image.new("RGB", (320, 240), (125, 165, 195))
    profile = bytearray(
        ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    )
    # LittleCMS writes the current time into the ICC header. Fix only that
    # standard dateTimeNumber so an identical public fixture has one stable
    # reviewed hash across runs; the profile ID remains unset by createProfile.
    profile[24:36] = struct.pack(">6H", 2024, 1, 1, 0, 0, 0)
    path = OUT / "synthetic_srgb_icc.png"
    image.save(path, icc_profile=bytes(profile))
    return path


def save_webp() -> Path:
    image = Image.new("RGB", (320, 240), (80, 145, 205))
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 50, 230, 190), fill=(225, 170, 145))
    path = OUT / "synthetic_lossless.webp"
    image.save(path, format="WEBP", lossless=True, method=6)
    return path


def save_light_effects() -> list[tuple[Path, dict]]:
    items: list[tuple[Path, dict]] = []
    width, height = 480, 320

    # Soft-light synthetic field.
    x = np.linspace(0, 1, width, dtype=np.float32)
    gradient = np.tile(x, (height, 1))
    soft = np.zeros((height, width, 3), dtype=np.uint8)
    soft[..., 0] = np.clip(90 + 110 * gradient, 0, 255)
    soft[..., 1] = np.clip(115 + 95 * gradient, 0, 255)
    soft[..., 2] = np.clip(145 + 75 * gradient, 0, 255)
    path = OUT / "synthetic_soft_light.png"
    Image.fromarray(soft, "RGB").save(path)
    items.append((path, {"光源": "合成测试光", "光质": "柔光", "光比": "低", "素材特效": []}))

    # Hard split light.
    hard = np.zeros((height, width, 3), dtype=np.uint8)
    hard[:, : width // 2] = (30, 42, 55)
    hard[:, width // 2 :] = (238, 222, 202)
    path = OUT / "synthetic_hard_light.png"
    Image.fromarray(hard, "RGB").save(path)
    items.append((path, {"光源": "合成测试光", "光质": "硬光", "光比": "高", "素材特效": []}))

    # Deterministic monochrome grain over a neutral field.
    rng = np.random.default_rng(1200)
    base = np.full((height, width, 3), 135, dtype=np.int16)
    noise = rng.normal(0, 12, (height, width, 1)).astype(np.int16)
    grain = np.clip(base + noise, 0, 255).astype(np.uint8)
    path = OUT / "synthetic_grain.png"
    Image.fromarray(grain, "RGB").save(path)
    items.append((path, {"光源": "合成测试光", "光质": "均匀", "光比": "低", "素材特效": ["细颗粒"]}))

    # Synthetic vignette with no grain.
    yy, xx = np.mgrid[:height, :width]
    cx, cy = width / 2, height / 2
    radius = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    factor = np.clip(1.0 - 0.55 * radius**1.6, 0.35, 1.0)
    vignette = np.empty((height, width, 3), dtype=np.uint8)
    for channel, value in enumerate((185, 170, 155)):
        vignette[..., channel] = np.clip(value * factor, 0, 255)
    path = OUT / "synthetic_vignette.png"
    Image.fromarray(vignette, "RGB").save(path)
    items.append((path, {"光源": "合成测试光", "光质": "均匀", "光比": "中", "素材特效": []}))
    return items


def main() -> None:
    configure_utf8_stdio()
    reviewed = load_reviewed_provenance()
    sources = [save_exif_orientation(), save_transparent(), save_icc(), save_webp()]
    sources.extend(
        require_fixed_public_fixture(relative, reviewed[relative]["sha256"])
        for relative in FIXED_PUBLIC_FIXTURE_PATHS
    )
    effects = save_light_effects()
    sources.extend(path for path, _ in effects)

    actual_paths = {
        str(path.relative_to(ROOT)).replace("\\", "/"): path
        for path in sources
    }
    if set(actual_paths) != set(reviewed):
        missing = sorted(set(reviewed) - set(actual_paths))
        unknown = sorted(set(actual_paths) - set(reviewed))
        raise RuntimeError(
            f"生成结果与独立来源登记表不一致；缺少={missing}；未知={unknown}"
        )
    for relative, path in actual_paths.items():
        if sha256(path) != reviewed[relative]["sha256"]:
            raise RuntimeError(f"生成结果哈希未通过独立来源审核：{relative}")

    manifest = {
        "version": "0.13.0",
        "privacy": "公开",
        "license": "CC0-1.0",
        "origin": "程序生成，无真人、无私人素材、无外部版权依赖",
        "files": [
            {
                "path": relative,
                "sha256": reviewed[relative]["sha256"],
                "license": reviewed[relative]["license"],
                "generated": reviewed[relative]["generated"],
            }
            for relative in sorted(actual_paths)
        ],
    }
    (ROOT / "examples" / "public_examples_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    light_effects = {
        "schema_version": "1.0.0",
        "dataset": {
            "name": "光线与素材特效合成基准",
            "version": "0.1.0",
            "privacy": "公开",
            "status": "人工标签，用于P1-C后续算法回归",
        },
        "samples": [
            {
                "id": path.stem,
                "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(path),
                "expected": labels,
            }
            for path, labels in effects
        ],
    }
    (ROOT / "examples" / "light_effect_ground_truth.example.json").write_text(
        json.dumps(light_effects, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已在{OUT}生成并登记{len(sources)}个公开合成样例")


if __name__ == "__main__":
    main()
