from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import hashlib

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from .constants import SUPPORTED_EXTENSIONS
from .errors import ImageReadError, UnsupportedImageError


@dataclass(frozen=True)
class LoadedImage:
    path: Path
    display_image: Image.Image
    rgb_image: Image.Image
    rgba_image: Image.Image | None
    valid_mask: np.ndarray
    metadata: dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_name(icc_bytes: bytes | None) -> str | None:
    if not icc_bytes:
        return None
    try:
        profile = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
        return ImageCms.getProfileName(profile).strip() or "未命名ICC"
    except Exception:
        return "无法读取的ICC"


def _convert_icc_to_srgb(
    image: Image.Image, icc_bytes: bytes | None
) -> tuple[Image.Image, bool, str]:
    if not icc_bytes:
        return image, False, "未嵌入ICC，按sRGB解释"
    try:
        source_profile = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
        target_profile = ImageCms.createProfile("sRGB")
        if "A" in image.getbands() or image.mode == "LA":
            alpha = image.convert("RGBA").getchannel("A")
            rgb = image.convert("RGB")
            converted = ImageCms.profileToProfile(
                rgb,
                source_profile,
                target_profile,
                outputMode="RGB",
                renderingIntent=ImageCms.Intent.PERCEPTUAL,
            )
            converted.putalpha(alpha)
            return converted, True, "已转换至sRGB"
        converted = ImageCms.profileToProfile(
            image.convert("RGB"),
            source_profile,
            target_profile,
            outputMode="RGB",
            renderingIntent=ImageCms.Intent.PERCEPTUAL,
        )
        return converted, True, "已转换至sRGB"
    except Exception:
        # Safe fallback: do not abort color analysis, but clearly record that the
        # embedded profile could not be applied. The original pixel values are
        # interpreted as sRGB and no creative grading is introduced.
        return image, False, "ICC读取失败，按sRGB解释"


def load_image(path: str | Path) -> LoadedImage:
    image_path = Path(path).expanduser().resolve()
    if not image_path.exists() or not image_path.is_file():
        raise ImageReadError(f"输入文件不存在：{image_path}")
    if image_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedImageError(f"不支持的图片格式：{image_path.suffix or '无扩展名'}")

    try:
        source = Image.open(image_path)
        source.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageReadError(f"图片读取失败：{image_path.name}") from exc

    source_format = source.format
    source_mode = source.mode
    source_info = dict(source.info)
    exif = source.getexif()
    exif_present = bool(exif)
    orientation_before = exif.get(274) if exif_present else None
    image = ImageOps.exif_transpose(source)

    icc_bytes = image.info.get("icc_profile") or source_info.get("icc_profile")
    icc_name = _profile_name(icc_bytes)
    icc_hash = hashlib.sha256(icc_bytes).hexdigest() if icc_bytes else None
    image, icc_applied, icc_note = _convert_icc_to_srgb(image, icc_bytes)

    has_alpha = "A" in image.getbands() or (
        source_mode == "P" and "transparency" in source_info
    )
    rgba_image = image.convert("RGBA") if has_alpha else None
    rgb_image = image.convert("RGB")

    if rgba_image is not None:
        alpha = np.asarray(rgba_image.getchannel("A"), dtype=np.uint8)
        valid_mask = alpha > 0
        opaque_share = float(np.mean(alpha == 255))
        partial_alpha_share = float(np.mean((alpha > 0) & (alpha < 255)))
    else:
        valid_mask = np.ones((rgb_image.height, rgb_image.width), dtype=bool)
        opaque_share = 1.0
        partial_alpha_share = 0.0

    valid_count = int(valid_mask.sum())
    if valid_count < 100:
        raise ImageReadError("有效可见像素过少，无法分析")

    ratio = rgb_image.width / rgb_image.height
    if ratio > 1.15:
        orientation = "landscape"
    elif ratio < 0.87:
        orientation = "portrait"
    else:
        orientation = "square"

    metadata = {
        "filename": image_path.name,
        "format": source_format,
        "source_mode": source_mode,
        "width": rgb_image.width,
        "height": rgb_image.height,
        "aspect_ratio": round(ratio, 6),
        "orientation": orientation,
        "sha256": sha256_file(image_path),
        "exif_present": exif_present,
        "exif_orientation_before": orientation_before,
        "orientation_applied": orientation_before not in {None, 1},
        "icc_present": bool(icc_bytes),
        "icc_profile_name": icc_name,
        "icc_profile_sha256": icc_hash,
        "icc_conversion_applied": icc_applied,
        "icc_note": icc_note,
        "working_space": "sRGB",
        "has_alpha": has_alpha,
        "opaque_pixel_share": round(opaque_share, 6),
        "partial_alpha_pixel_share": round(partial_alpha_share, 6),
        "valid_pixel_count": valid_count,
        "valid_pixel_share": round(valid_count / valid_mask.size, 6),
        "analysis_source": "original",
        "render_color_adjustment": False,
    }

    return LoadedImage(
        path=image_path,
        display_image=image,
        rgb_image=rgb_image,
        rgba_image=rgba_image,
        valid_mask=valid_mask,
        metadata=metadata,
    )


def checkerboard_composite(image: Image.Image, cell: int = 18) -> Image.Image:
    """Show transparent inputs without changing analysis pixels.

    This function is display-only. The analysis pipeline uses `valid_mask` and
    never samples the checkerboard background.
    """
    if "A" not in image.getbands():
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    width, height = rgba.size
    yy, xx = np.mgrid[:height, :width]
    parity = ((xx // cell) + (yy // cell)) % 2
    board = np.empty((height, width, 3), dtype=np.uint8)
    board[parity == 0] = (244, 244, 242)
    board[parity == 1] = (224, 226, 224)
    background = Image.fromarray(board, "RGB")
    background.paste(rgba, (0, 0), rgba)
    return background
