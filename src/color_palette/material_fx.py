from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


NO_EFFECT_SUMMARY = "未发现明显素材特效"
MATERIAL_FX_RULESET_VERSION = "material-fx-0.13.0"


@dataclass(frozen=True)
class _Tile:
    name: str
    ys: slice
    xs: slice
    mean_luma: float
    luma_std: float
    gradient_median: float
    laplacian_variance: float
    fine_residual: float
    broad_residual: float


def analyze_material_fx(rgb: np.ndarray, valid_mask: np.ndarray) -> dict:
    """Infer visible Material FX without changing the input pixels.

    The detector deliberately uses several ROI families. Flat regions provide
    grain/noise evidence, edge regions provide blur/RGB-shift evidence, and
    highlights provide diffusion evidence. Internal evidence stays in JSON;
    the renderer consumes only ``display_name``.
    """
    prepared_rgb, prepared_mask = _prepare(rgb, valid_mask)
    gray = cv2.cvtColor(prepared_rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    tiles = _tiles(gray, prepared_mask)
    flat_tiles = sorted(
        tiles,
        key=lambda tile: tile.gradient_median + tile.luma_std * 0.06,
    )[: min(8, len(tiles))]
    coarse_grain_tiles = sorted(
        (
            tile
            for tile in _tiles(gray, prepared_mask, grid=6)
            if 18 <= tile.mean_luma <= 246
            and tile.gradient_median <= 72
            and tile.luma_std <= 58
        ),
        key=lambda tile: tile.gradient_median + tile.luma_std * 0.06,
    )[:8]
    edge_tiles = sorted(
        tiles,
        key=lambda tile: tile.laplacian_variance,
        reverse=True,
    )[: min(8, len(tiles))]

    diagnostics = {
        "roi_strategy": {
            "flat": [tile.name for tile in flat_tiles],
            "coarse_grain": [tile.name for tile in coarse_grain_tiles],
            "edge": [tile.name for tile in edge_tiles],
            "highlight": "Luma>=235及其邻域",
            "face": "肤色ROI由独立肤色模块提供；Material FX不以平滑肤色单独判定模糊",
        },
        "candidate_count": 0,
    }
    items: list[dict] = []

    grain = _detect_grain(prepared_rgb, gray, prepared_mask, flat_tiles)
    if grain is None:
        coarse_candidate = _detect_grain(
            prepared_rgb,
            gray,
            prepared_mask,
            coarse_grain_tiles,
        )
        if coarse_candidate and coarse_candidate.get("subtype") == "coarse":
            coarse_candidate["evidence"].append(
                "较小分块补充采样确认粗尺度随机残差跨区域存在"
            )
            coarse_candidate["regions"] = [
                f"g6:{region}" for region in coarse_candidate["regions"]
            ]
            grain = coarse_candidate
    if grain:
        items.append(grain)

    rgb_shift = _detect_rgb_shift(prepared_rgb, gray, prepared_mask)
    if rgb_shift:
        items.append(rgb_shift)

    blur = _detect_blur(gray, prepared_mask, tiles, edge_tiles)
    if blur:
        items.append(blur)

    diffusion = _detect_highlight_diffusion(gray, prepared_mask)
    if diffusion:
        items.append(diffusion)

    degradation = _detect_degradation(gray, prepared_mask, grain is not None)
    if degradation:
        items.append(degradation)

    border = _detect_film_border(gray, prepared_mask)
    if border:
        items.append(border)

    film_context = grain is not None or border is not None
    scratches = _detect_scratches(gray, prepared_mask, film_context)
    if scratches:
        items.append(scratches)
    dust = _detect_dust(gray, prepared_mask, film_context)
    if dust:
        items.append(dust)

    if grain and (border or scratches or dust):
        items.append(
            _item(
                "film_scan",
                "胶片扫描质感",
                0.76,
                ["颗粒与扫描载体痕迹同时出现"],
                ["单纯数字噪声", "单独添加的边框"],
                ["flat", "border"],
            )
        )

    items = _deduplicate(items)
    diagnostics["candidate_count"] = len(items)
    labels = [item["display_name"] for item in items]
    return {
        "ruleset_version": MATERIAL_FX_RULESET_VERSION,
        "items": items,
        "summary": "\n".join(labels) if labels else NO_EFFECT_SUMMARY,
        "status": "已识别" if labels else "未发现明显",
        "diagnostics": diagnostics,
    }


def legacy_effects(material_effects: dict) -> dict:
    """Keep the V0.12 ``effects`` shape for downstream JSON consumers."""
    labels = [item["display_name"] for item in material_effects.get("items", [])]
    summary = material_effects.get("summary") or NO_EFFECT_SUMMARY
    return {
        "detected": labels,
        "not_obvious": [],
        "conclusion": summary,
        "status": material_effects.get("status", "未发现明显"),
    }


def display_names(analysis: dict) -> list[str]:
    """Return renderer-safe labels with a V0.12 fallback."""
    material_effects = analysis.get("material_effects")
    if isinstance(material_effects, dict):
        labels = [
            item.get("display_name")
            for item in material_effects.get("items", [])
            if isinstance(item, dict) and item.get("display_name")
        ]
        if labels:
            return _unique_strings(labels)

    legacy = analysis.get("effects", {})
    detected = legacy.get("detected", []) if isinstance(legacy, dict) else []
    if detected:
        return _unique_strings([str(value) for value in detected])
    return [NO_EFFECT_SUMMARY]


def _prepare(rgb: np.ndarray, valid_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Material FX分析需要RGB三通道图像")
    if valid_mask.shape != rgb.shape[:2]:
        raise ValueError("Material FX透明像素掩膜尺寸不一致")
    height, width = rgb.shape[:2]
    scale = min(1.0, 768.0 / max(height, width))
    if scale == 1.0:
        return rgb.copy(), valid_mask.astype(bool, copy=True)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    mask = cv2.resize(
        valid_mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST
    ).astype(bool)
    return resized, mask


def _tiles(gray: np.ndarray, mask: np.ndarray, grid: int = 4) -> list[_Tile]:
    gradient = _gradient(gray)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    fine = gray - cv2.GaussianBlur(gray, (0, 0), 1.0)
    broad = gray - cv2.GaussianBlur(gray, (0, 0), 3.0)
    height, width = gray.shape
    result: list[_Tile] = []
    for row in range(grid):
        y1, y2 = row * height // grid, (row + 1) * height // grid
        for column in range(grid):
            x1, x2 = column * width // grid, (column + 1) * width // grid
            ys, xs = slice(y1, y2), slice(x1, x2)
            tile_mask = mask[ys, xs]
            if tile_mask.size < 256 or float(tile_mask.mean()) < 0.75:
                continue
            pixels = gray[ys, xs][tile_mask]
            tile_gradient = gradient[ys, xs][tile_mask]
            edge_limit = max(6.0, float(np.percentile(tile_gradient, 65)))
            residual_mask = tile_mask & (gradient[ys, xs] <= edge_limit)
            if int(residual_mask.sum()) < 64:
                residual_mask = tile_mask
            result.append(
                _Tile(
                    name=f"r{row + 1}c{column + 1}",
                    ys=ys,
                    xs=xs,
                    mean_luma=float(np.mean(pixels)),
                    luma_std=float(np.std(pixels)),
                    gradient_median=float(np.median(tile_gradient)),
                    laplacian_variance=float(np.var(laplacian[ys, xs][tile_mask])),
                    fine_residual=_robust_std(fine[ys, xs][residual_mask]),
                    broad_residual=_robust_std(broad[ys, xs][residual_mask]),
                )
            )
    return result


def _detect_grain(
    rgb: np.ndarray,
    gray: np.ndarray,
    mask: np.ndarray,
    flat_tiles: list[_Tile],
) -> dict | None:
    usable = [
        tile
        for tile in flat_tiles
        if 18 <= tile.mean_luma <= 246
        and tile.gradient_median <= 72
        and tile.luma_std <= 58
    ]
    if len(usable) < 3:
        return None
    residuals = np.array([tile.fine_residual for tile in usable], dtype=float)
    broad = np.array([tile.broad_residual for tile in usable], dtype=float)
    scale_ratio = float(np.median(residuals / np.maximum(broad, 0.1)))
    coarse_candidate = scale_ratio < 0.55
    persistent = (broad >= 1.15) if coarse_candidate else (residuals >= 2.15)
    persistence = float(np.mean(persistent))
    median_residual = float(np.median(residuals))
    median_broad = float(np.median(broad))
    if persistence < 0.5 or (
        coarse_candidate and median_broad < 1.15
    ) or (not coarse_candidate and median_residual < 2.05):
        return None

    block_ratio, block_energy = _jpeg_block_score(gray, mask)
    if block_ratio >= 2.15 and block_energy >= 2.0:
        return None

    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb).astype(np.float32)
    chroma_residuals: list[float] = []
    for channel in (1, 2):
        residual = ycrcb[..., channel] - cv2.GaussianBlur(
            ycrcb[..., channel], (0, 0), 1.0
        )
        chroma_residuals.append(_robust_std(residual[mask]))
    chroma_ratio = max(chroma_residuals) / max(median_residual, 0.1)
    bright_evidence = [
        tile
        for tile in usable
        if tile.mean_luma >= 85
        and (
            (tile.broad_residual >= 1.15)
            if coarse_candidate
            else (tile.fine_residual >= 2.15)
        )
    ]
    if chroma_ratio > 1.35 and len(bright_evidence) < 2:
        return None

    subtype = "fine" if scale_ratio >= 0.64 else "coarse"
    display_name = "细颗粒" if subtype == "fine" else "粗颗粒"
    confidence = min(
        0.94,
        0.56
        + max(0.0, median_residual - 2.05) * 0.055
        + persistence * 0.22
        + min(len(bright_evidence), 3) * 0.025,
    )
    supporting_tiles = [
        tile.name
        for tile in usable
        if (
            tile.broad_residual >= 1.15
            if coarse_candidate
            else tile.fine_residual >= 2.15
        )
    ]
    return _item(
        "grain",
        display_name,
        confidence,
        [
            f"{int(persistent.sum())}/{len(usable)}个低纹理区域具有一致随机高频残差",
            "颗粒证据跨区域存在，且不依附单一物体边缘",
            f"细尺度/宽尺度残差比={scale_ratio:.3f}",
        ],
        ["暗部数字噪点", "JPEG块效应", "真实物体纹理"],
        supporting_tiles,
        subtype=subtype,
    )


def _detect_blur(
    gray: np.ndarray,
    mask: np.ndarray,
    tiles: list[_Tile],
    edge_tiles: list[_Tile],
) -> dict | None:
    candidates = [
        tile
        for tile in tiles
        if tile.luma_std >= 12
    ]
    if len(candidates) < 3:
        return None
    lap_values = np.array([tile.laplacian_variance for tile in candidates])
    sharp_p90 = float(np.percentile(lap_values, 90))
    sharp_fraction = float(np.mean(lap_values >= 120.0))
    gradient = _gradient(gray)
    valid_gradient = gradient[mask]
    if valid_gradient.size == 0:
        return None
    if float(np.percentile(valid_gradient, 95)) < 12.0:
        return None
    edge_threshold = max(12.0, float(np.percentile(valid_gradient, 88)))
    edge_mask = mask & (gradient >= edge_threshold)
    if int(edge_mask.sum()) < 96:
        return None
    laplacian = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
    acutance = float(
        np.median(laplacian[edge_mask])
        / max(np.median(gradient[edge_mask]), 0.1)
    )

    scale_ratios = np.array(
        [
            tile.fine_residual / max(tile.broad_residual, 0.1)
            for tile in candidates
        ],
        dtype=float,
    )
    median_scale_ratio = float(np.median(scale_ratios))
    retained_detail_p90 = float(np.percentile(scale_ratios, 90))
    median_broad_residual = float(
        np.median([tile.broad_residual for tile in candidates])
    )
    if (
        len(candidates) >= 6
        and median_broad_residual >= 1.50
        and median_scale_ratio <= 0.30
        and retained_detail_p90 <= 0.34
        and acutance < 0.50
    ):
        return _item(
            "gaussian_blur",
            "高斯模糊",
            min(
                0.91,
                0.72
                + max(0.0, 0.30 - median_scale_ratio) * 1.2
                + max(0.0, 0.34 - retained_detail_p90) * 0.8,
            ),
            [
                "多个结构区域的细尺度细节相对宽尺度信息一致衰减",
                f"宽尺度结构残差中位数={median_broad_residual:.3f}",
                f"细/宽尺度残差中位比={median_scale_ratio:.3f}",
                f"清晰细节保留P90={retained_detail_p90:.3f}",
            ],
            ["浅景深", "光学扩散", "低分辨率输入"],
            [tile.name for tile in edge_tiles[:4]],
        )

    # A naturally defocused background still retains at least one clearly sharp
    # subject tile. This exclusion prevents shallow DOF from becoming Blur.
    if sharp_fraction >= 0.12 or sharp_p90 >= 115 or acutance >= 0.62:
        return None
    if sharp_p90 < 32 and acutance < 0.43:
        return _item(
            "gaussian_blur",
            "高斯模糊",
            min(0.91, 0.72 + (32 - sharp_p90) / 180),
            ["多个主体边缘区域同时扩散", "未发现可保留的清晰主体区域"],
            ["浅景深", "平滑肤色", "运动模糊"],
            [tile.name for tile in edge_tiles[:4]],
        )
    if sharp_p90 < 72 and acutance < 0.53:
        return _item(
            "softness",
            "柔化",
            min(0.86, 0.66 + (72 - sharp_p90) / 240),
            ["多区域微反差与边缘清晰度共同下降"],
            ["浅景深", "平滑肤色", "低分辨率输入"],
            [tile.name for tile in edge_tiles[:4]],
        )
    if sharp_p90 < 110 and acutance < 0.58:
        return _item(
            "low_clarity",
            "低清晰度",
            min(0.8, 0.62 + (110 - sharp_p90) / 320),
            ["多个主体区域的细节与局部微反差偏低"],
            ["浅景深", "输入尺寸较小", "平滑肤色"],
            [tile.name for tile in edge_tiles[:4]],
        )
    return None


def _detect_rgb_shift(rgb: np.ndarray, gray: np.ndarray, mask: np.ndarray) -> dict | None:
    channels = [rgb[..., index].astype(np.float32) for index in range(3)]
    edges = [_normalized_edge(channel, mask) for channel in channels]
    base_rg, shift_rg, aligned_rg = _best_shift(edges[0], edges[1], mask)
    base_bg, shift_bg, aligned_bg = _best_shift(edges[2], edges[1], mask)
    separation = float(np.hypot(shift_rg[0] - shift_bg[0], shift_rg[1] - shift_bg[1]))
    improvement = min(aligned_rg - base_rg, aligned_bg - base_bg)
    aligned = min(aligned_rg, aligned_bg)
    opposite = shift_rg[0] * shift_bg[0] + shift_rg[1] * shift_bg[1] <= 0
    strong_edges = int((_gradient(gray)[mask] >= 20).sum())
    if (
        strong_edges < 120
        or separation < 1.5
        or improvement < 0.08
        or aligned < 0.58
        or not opposite
    ):
        return None
    return _item(
        "rgb_shift",
        "RGB 色彩偏移",
        min(0.94, 0.69 + improvement * 0.7 + min(separation, 4.0) * 0.025),
        [
            f"R/G边缘最佳位移={shift_rg}",
            f"B/G边缘最佳位移={shift_bg}",
            "通道边缘校正后相关性显著提高",
        ],
        ["镜头像差", "锐化光晕", "JPEG边缘异常"],
        ["edge"],
    )


def _detect_highlight_diffusion(gray: np.ndarray, mask: np.ndarray) -> dict | None:
    highlight = mask & (gray >= 235)
    share = float(highlight.sum() / max(mask.sum(), 1))
    if share < 0.004 or share > 0.35:
        return None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    dilated = cv2.dilate(highlight.astype(np.uint8), kernel).astype(bool)
    ring = dilated & ~highlight & mask
    if int(ring.sum()) < 120:
        return None
    ring_mean = float(np.mean(gray[ring]))
    global_mean = float(np.mean(gray[mask]))
    if ring_mean < max(155.0, global_mean + 28.0):
        return None
    return _item(
        "highlight_diffusion",
        "高光扩散",
        min(0.9, 0.68 + (ring_mean - max(155.0, global_mean)) / 300),
        ["高光外围存在连续柔和亮度扩散", "扩散邻域缺少硬边界"],
        ["真实强逆光", "过曝剪切", "镜头眩光"],
        ["highlight"],
    )


def _detect_degradation(gray: np.ndarray, mask: np.ndarray, grain_detected: bool) -> dict | None:
    block_ratio, block_energy = _jpeg_block_score(gray, mask)
    horizontal_equal = np.isclose(np.diff(gray, axis=1), 0, atol=0.2)
    vertical_equal = np.isclose(np.diff(gray, axis=0), 0, atol=0.2)
    repeat_share = float((horizontal_equal.mean() + vertical_equal.mean()) / 2)
    degraded = block_ratio >= 2.25 and block_energy >= 2.0
    if not degraded:
        return None
    confidence = min(0.9, 0.66 + max(0.0, block_ratio - 2.25) * 0.08 + max(0.0, repeat_share - 0.72))
    alternatives = ["JPEG输入本身的轻微压缩", "平坦色块"]
    if grain_detected:
        alternatives.append("颗粒纹理")
    return _item(
        "image_degradation",
        "画质降低",
        confidence,
        [f"8像素块边界比={block_ratio:.3f}", f"相邻像素重复占比={repeat_share:.3f}"],
        alternatives,
        ["flat", "edge"],
    )


def _detect_film_border(gray: np.ndarray, mask: np.ndarray) -> dict | None:
    height, width = gray.shape
    band = max(3, round(min(height, width) * 0.045))
    border_parts = [
        gray[:band, :][mask[:band, :]],
        gray[-band:, :][mask[-band:, :]],
        gray[:, :band][mask[:, :band]],
        gray[:, -band:][mask[:, -band:]],
    ]
    if any(part.size < 32 for part in border_parts):
        return None
    border_means = [float(np.mean(part)) for part in border_parts]
    border_stds = [float(np.std(part)) for part in border_parts]
    inner = gray[band * 2 : height - band * 2, band * 2 : width - band * 2]
    if inner.size == 0:
        return None
    inner_mean = float(np.mean(inner))
    dark_sides = sum(
        mean <= 45 and std <= 24 and inner_mean - mean >= 28
        for mean, std in zip(border_means, border_stds)
    )
    if dark_sides < 3:
        return None
    return _item(
        "film_border",
        "胶片边框",
        min(0.94, 0.72 + dark_sides * 0.045),
        [f"{dark_sides}侧存在连续低亮度窄边框"],
        ["暗角", "画面内真实黑色物体"],
        ["border"],
    )


def _detect_scratches(gray: np.ndarray, mask: np.ndarray, film_context: bool) -> dict | None:
    if not film_context:
        return None
    edges = cv2.Canny(gray.astype(np.uint8), 65, 150)
    edges[~mask] = 0
    minimum = max(gray.shape) * 0.55
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(30, round(minimum * 0.18)),
        minLineLength=round(minimum),
        maxLineGap=10,
    )
    if lines is None:
        return None
    narrow = []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if min(dx, dy) <= max(3, 0.08 * max(dx, dy)):
            narrow.append((int(x1), int(y1), int(x2), int(y2)))
    if not 1 <= len(narrow) <= 8:
        return None
    return _item(
        "scratch",
        "划痕",
        min(0.88, 0.68 + len(narrow) * 0.025),
        ["扫描语境中存在少量细长高反差线状痕迹"],
        ["建筑线条", "发丝", "画面边框"],
        ["edge"],
    )


def _detect_dust(gray: np.ndarray, mask: np.ndarray, film_context: bool) -> dict | None:
    if not film_context:
        return None
    residual = np.abs(gray - cv2.medianBlur(gray.astype(np.uint8), 7).astype(np.float32))
    threshold = max(14.0, float(np.median(residual[mask]) + 5 * _robust_std(residual[mask])))
    candidates = ((residual >= threshold) & mask).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(candidates, 8)
    blobs = 0
    for index in range(1, count):
        _, _, width, height, area = stats[index]
        if 2 <= area <= 42 and max(width, height) <= 10:
            blobs += 1
    if not 8 <= blobs <= 80:
        return None
    return _item(
        "dust",
        "灰尘",
        min(0.88, 0.67 + blobs / 500),
        [f"扫描语境中检测到{blobs}个孤立小斑点"],
        ["真实物体纹理", "坏点", "压缩噪点"],
        ["flat"],
    )


def _jpeg_block_score(gray: np.ndarray, mask: np.ndarray) -> tuple[float, float]:
    if min(gray.shape) < 32:
        return 1.0, 0.0
    vertical = np.abs(np.diff(gray, axis=1))
    horizontal = np.abs(np.diff(gray, axis=0))
    vertical_mask = mask[:, 1:] & mask[:, :-1]
    horizontal_mask = mask[1:, :] & mask[:-1, :]
    v_positions = np.arange(1, gray.shape[1])
    h_positions = np.arange(1, gray.shape[0])
    v_boundary = (v_positions % 8) == 0
    h_boundary = (h_positions % 8) == 0

    boundary_values = np.concatenate(
        [
            vertical[:, v_boundary][vertical_mask[:, v_boundary]],
            horizontal[h_boundary, :][horizontal_mask[h_boundary, :]],
        ]
    )
    normal_values = np.concatenate(
        [
            vertical[:, ~v_boundary][vertical_mask[:, ~v_boundary]],
            horizontal[~h_boundary, :][horizontal_mask[~h_boundary, :]],
        ]
    )
    if boundary_values.size < 32 or normal_values.size < 32:
        return 1.0, 0.0
    boundary = float(np.mean(boundary_values))
    normal = float(np.mean(normal_values))
    return boundary / max(normal, 0.1), boundary


def _best_shift(reference: np.ndarray, target: np.ndarray, mask: np.ndarray):
    base = _cosine(reference[mask], target[mask])
    best_score = base
    best_shift = (0, 0)
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            if dx == 0 and dy == 0:
                continue
            shifted = np.roll(reference, (dy, dx), axis=(0, 1))
            shifted_mask = mask.copy()
            if dy > 0:
                shifted_mask[:dy, :] = False
            elif dy < 0:
                shifted_mask[dy:, :] = False
            if dx > 0:
                shifted_mask[:, :dx] = False
            elif dx < 0:
                shifted_mask[:, dx:] = False
            score = _cosine(shifted[shifted_mask], target[shifted_mask])
            if score > best_score:
                best_score = score
                best_shift = (dx, dy)
    return base, best_shift, best_score


def _normalized_edge(channel: np.ndarray, mask: np.ndarray) -> np.ndarray:
    edge = _gradient(channel)
    values = edge[mask]
    scale = float(np.percentile(values, 95)) if values.size else 1.0
    return np.clip(edge / max(scale, 0.1), 0, 1)


def _gradient(gray: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def _robust_std(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=np.float32)
    if values.size == 0:
        return 0.0
    median = float(np.median(values))
    return float(np.median(np.abs(values - median)) * 1.4826)


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    left = left.astype(np.float64, copy=False)
    right = right.astype(np.float64, copy=False)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / denominator) if denominator else 0.0


def _item(
    effect_type: str,
    display_name: str,
    confidence: float,
    evidence: list[str],
    alternatives: list[str],
    regions: list[str],
    *,
    subtype: str | None = None,
) -> dict:
    item = {
        "type": effect_type,
        "display_name": display_name,
        "confidence": round(float(confidence), 4),
        "evidence": evidence,
        "alternatives": alternatives,
        "regions": regions,
    }
    if subtype:
        item["subtype"] = subtype
    return item


def _deduplicate(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in items:
        name = item["display_name"]
        if name not in seen:
            seen.add(name)
            result.append(item)
    return result


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
