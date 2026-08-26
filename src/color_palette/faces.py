from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from skimage.color import rgb2lab

from .constants import DEFAULT_FACE_BACKEND, FACE_BACKENDS

try:
    import dlib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dlib = None


@dataclass(frozen=True)
class FaceDetection:
    boxes: list[list[int]]
    detector: str
    requested_backend: str
    available_backends: list[str]
    degraded: bool = False
    note: str = ""
    baseline_count: int = 0
    recovery_used: bool = False
    face_candidates: list[dict] = field(default_factory=list)
    failure_stage: str | None = None
    failure_reason: str | None = None
    face_detection_ms: float = 0.0
    recovery_detection_ms: float = 0.0
    anchor_geometry: dict | None = None


def _iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _nms(boxes: list[list[int]], threshold: float = 0.35) -> list[list[int]]:
    ordered = sorted(boxes, key=lambda box: box[2] * box[3], reverse=True)
    kept: list[list[int]] = []
    for box in ordered:
        if all(_iou(box, existing) < threshold for existing in kept):
            kept.append(box)
    return kept


def available_face_backends() -> list[str]:
    backends = ["opencv"] if _opencv_face_available() else []
    if dlib is not None:
        backends.append("dlib")
    return backends


def _opencv_face_available() -> bool:
    return bool(
        hasattr(cv2, "CascadeClassifier")
        and hasattr(cv2, "cvtColor")
        and getattr(getattr(cv2, "data", None), "haarcascades", None)
    )


def _resolve_face_backend(backend: str | None) -> str:
    requested = (
        backend or os.getenv("COLOR_PALETTE_FACE_BACKEND") or DEFAULT_FACE_BACKEND
    ).lower()
    if requested not in FACE_BACKENDS:
        raise ValueError(
            f"不支持的人脸后端：{requested}；可选值为auto/opencv/dlib/none"
        )
    return requested


def detect_faces(rgb: np.ndarray, backend: str | None = None) -> FaceDetection:
    detection_started = time.perf_counter()
    height, width = rgb.shape[:2]
    requested = _resolve_face_backend(backend)
    available = available_face_backends()

    if requested == "none":
        return FaceDetection(
            boxes=[],
            detector="disabled",
            requested_backend=requested,
            available_backends=available,
            degraded=False,
            note="肤色分析已显式关闭",
            failure_stage="no_face_candidate",
            failure_reason="no_face_candidate",
            face_detection_ms=round(
                (time.perf_counter() - detection_started) * 1000, 3
            ),
        )

    # The portable default is OpenCV-only. `auto` prefers dlib when available
    # and otherwise degrades to OpenCV. An explicit unavailable dlib request
    # degrades safely instead of aborting the whole color analysis.
    use_dlib = requested in {"auto", "dlib"} and dlib is not None
    use_opencv = requested in {"auto", "opencv"} or (
        requested == "dlib" and dlib is None
    )
    degraded = requested == "dlib" and dlib is None
    if degraded:
        note = "dlib不可用，已安全降级为OpenCV"
    elif requested == "auto" and dlib is None:
        note = "auto已选择OpenCV（dlib不可用）"
    else:
        note = ""

    boxes: list[list[int]] = []
    detectors: list[str] = []

    if use_dlib:
        try:
            detector = dlib.get_frontal_face_detector()
            dlib_rects = list(detector(rgb, 1))
            if (
                len(dlib_rects) <= 1
                and min(height, width) >= 500
                and max(height, width) <= 1200
            ):
                dlib_rects.extend(detector(rgb, 2))
            for rect in dlib_rects:
                boxes.append(
                    [
                        max(0, int(rect.left())),
                        max(0, int(rect.top())),
                        int(rect.width()),
                        int(rect.height()),
                    ]
                )
            if dlib_rects:
                detectors.append("dlib")
        except Exception as exc:  # pragma: no cover - backend-specific runtime failure
            if requested == "dlib":
                degraded = True
                note = f"dlib运行失败，已安全降级为OpenCV：{type(exc).__name__}"
                use_opencv = True

    if use_opencv and not _opencv_face_available():
        use_opencv = False
        degraded = True
        note = "OpenCV人脸组件不可用，肤色分析显示样本不足"

    if use_opencv:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        cascade_paths = [
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
            cv2.data.haarcascades + "haarcascade_profileface.xml",
        ]
        for cascade_path in cascade_paths:
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                continue
            detections = cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(70, 70),
            )
            boxes.extend(
                [[int(x), int(y), int(w), int(h)] for x, y, w, h in detections]
            )
            if len(detections):
                detectors.append("opencv")

    boxes = _nms(boxes)
    image_area = width * height
    significant = [
        box
        for box in boxes
        if box[2] >= 70 and box[3] >= 70 and (box[2] * box[3]) / image_area >= 0.012
    ]
    baseline_ms = round((time.perf_counter() - detection_started) * 1000, 3)
    baseline_candidates = [
        {
            "box": box,
            "source": "baseline",
            "preprocessing": "original",
            "angle": 0,
            "accepted": True,
            "score": 1.0,
            "reason": "baseline_detector",
        }
        for box in significant
    ]

    recovery_used = False
    recovery_ms = 0.0
    failure_stage: str | None = None
    failure_reason: str | None = None
    face_candidates = baseline_candidates
    final_boxes = significant
    anchor_geometry = None
    if not final_boxes and use_opencv:
        recovery_used = True
        recovery_started = time.perf_counter()
        final_boxes, face_candidates, failure_reason, anchor_geometry = (
            _recover_opencv_faces(rgb)
        )
        recovery_ms = round((time.perf_counter() - recovery_started) * 1000, 3)
        if not final_boxes:
            failure_reason = failure_reason or "no_face_candidate"
            failure_stage = {
                "ambiguous_multiple_faces": "multiple_faces",
                "face_low_confidence": "face_low_confidence",
            }.get(failure_reason, "no_face_candidate")

    detector_name = "+".join(sorted(set(detectors))) or (
        "opencv" if use_opencv else "unavailable"
    )
    if recovery_used and final_boxes:
        detector_name += "-recovery"

    return FaceDetection(
        boxes=final_boxes,
        detector=detector_name,
        requested_backend=requested,
        available_backends=available,
        degraded=degraded,
        note=note,
        baseline_count=len(significant),
        recovery_used=recovery_used,
        face_candidates=face_candidates,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        face_detection_ms=baseline_ms,
        recovery_detection_ms=recovery_ms,
        anchor_geometry=anchor_geometry,
    )


def _recover_opencv_faces(
    rgb: np.ndarray,
) -> tuple[list[list[int]], list[dict], str | None, dict | None]:
    """Run a conservative second pass only after the normal detector found no face.

    The pass is intentionally deterministic and local.  Rotation is applied to
    detector input only; accepted boxes are mapped back to the unrotated working
    image before any skin sampling happens.
    """

    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    variants = [
        ("original", gray, [-15, -8, 8, 15]),
        (
            "clahe",
            cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray),
            [0, -15, -8, 8, 15],
        ),
        ("equalized", cv2.equalizeHist(gray), [0, -15, -8, 8, 15]),
    ]
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if cascade.empty():
        return [], [], "face_low_confidence", None

    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    skin_mask = _base_skin_mask(rgb, lab, np.ones((height, width), dtype=bool))
    if int(skin_mask.sum()) < 80:
        return [], [], "no_face_candidate", None
    min_side = max(48, int(round(min(height, width) * 0.045)))
    records: list[dict] = []
    accepted: list[dict] = []

    for preprocessing, prepared, angles in variants:
        stage_accepted: list[dict] = []
        for angle in angles:
            matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
            rotated = cv2.warpAffine(
                prepared,
                matrix,
                (width, height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT_101,
            )
            detections = cascade.detectMultiScale(
                rotated,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(min_side, min_side),
            )
            for raw_box in detections:
                mapped = _inverse_rotated_box(
                    [int(value) for value in raw_box], matrix, (height, width)
                )
                record = _validate_recovery_candidate(
                    mapped,
                    skin_mask=skin_mask,
                    lab=lab,
                    image_shape=(height, width),
                )
                record.update(
                    {
                        "source": "recovery",
                        "preprocessing": preprocessing,
                        "angle": angle,
                        "anchor_geometry": _recovery_anchor_geometry(
                            [int(value) for value in raw_box],
                            matrix,
                            (height, width),
                            angle,
                        ),
                    }
                )
                records.append(record)
                if record["accepted"]:
                    stage_accepted.append(record)
        accepted.extend(stage_accepted)
        # A strict original-gray rotated candidate is preferable to collecting
        # weaker enhanced-image false positives. All rotations in this stage
        # have still been checked, so ambiguity remains fail-closed.
        if stage_accepted:
            break

    clusters = _cluster_recovery_candidates(accepted)
    if not clusters:
        return (
            [],
            records[:24],
            "face_low_confidence" if records else "no_face_candidate",
            None,
        )

    chosen, reason = _select_recovery_cluster(clusters)
    if chosen is None:
        return [], records[:24], reason, None
    return [chosen["box"]], records[:24], None, chosen["anchor_geometry"]


def _recovery_anchor_geometry(
    raw_box: list[int],
    matrix: np.ndarray,
    shape: tuple[int, int],
    detection_angle: float,
) -> dict:
    """Map canonical upright face sampling points back to the working image."""

    height, width = shape
    x, y, box_width, box_height = raw_box
    inverse = cv2.invertAffineTransform(matrix)

    def mapped(x_factor: float, y_factor: float) -> list[float]:
        point = (
            np.array([x + x_factor * box_width, y + y_factor * box_height, 1.0])
            @ inverse.T
        )
        return [
            round(float(np.clip(point[0], 0, width - 1)), 2),
            round(float(np.clip(point[1], 0, height - 1)), 2),
        ]

    return {
        "cheek_centers": [mapped(0.32, 0.64), mapped(0.68, 0.64)],
        "forehead_center": mapped(0.50, 0.20),
        "face_width": int(box_width),
        "face_height": int(box_height),
        "orientation_degrees": round(float(-detection_angle), 2),
    }


def _inverse_rotated_box(
    box: list[int], matrix: np.ndarray, shape: tuple[int, int]
) -> list[int]:
    """Map an axis-aligned rotated-image box back inside the source bounds."""

    height, width = shape
    x, y, box_width, box_height = box
    corners = np.array(
        [
            [x, y, 1.0],
            [x + box_width, y, 1.0],
            [x + box_width, y + box_height, 1.0],
            [x, y + box_height, 1.0],
        ],
        dtype=np.float64,
    )
    inverse = cv2.invertAffineTransform(matrix)
    mapped = corners @ inverse.T
    left, top = np.floor(mapped.min(axis=0)).astype(int)
    right, bottom = np.ceil(mapped.max(axis=0)).astype(int)
    left = max(0, min(int(left), width - 1))
    top = max(0, min(int(top), height - 1))
    right = max(left + 1, min(int(right), width))
    bottom = max(top + 1, min(int(bottom), height))
    return [left, top, right - left, bottom - top]


def _validate_recovery_candidate(
    box: list[int],
    *,
    skin_mask: np.ndarray,
    lab: np.ndarray,
    image_shape: tuple[int, int],
) -> dict:
    height, width = image_shape
    x, y, box_width, box_height = box
    area_share = box_width * box_height / max(height * width, 1)
    core = _ellipse_mask(
        image_shape,
        x + 0.50 * box_width,
        y + 0.54 * box_height,
        0.34 * box_width,
        0.39 * box_height,
    )
    skin_count = int((core & skin_mask).sum())
    core_count = int(core.sum())
    skin_share = skin_count / max(core_count, 1)
    core_l = lab[..., 0][core]
    median_l = float(np.median(core_l)) if core_l.size else 0.0
    aspect = box_width / max(box_height, 1)

    reason = "valid"
    accepted = True
    if area_share < 0.008 or box_width < 48 or box_height < 48:
        reason, accepted = "face_too_small", False
    elif not 0.68 <= aspect <= 1.48:
        reason, accepted = "primary_roi_invalid", False
    elif skin_count < 80 or skin_share < 0.18:
        reason, accepted = "skin_pixel_share_low", False
    elif not 24 <= median_l <= 94:
        reason, accepted = "luminance_out_of_range", False

    area_quality = min(area_share / 0.06, 1.0)
    skin_quality = min(skin_share / 0.58, 1.0)
    luminance_quality = max(0.0, 1.0 - abs(median_l - 62.0) / 55.0)
    score = 0.55 * skin_quality + 0.25 * area_quality + 0.20 * luminance_quality
    return {
        "box": box,
        "accepted": accepted,
        "score": round(float(score), 3),
        "reason": reason,
        "area_share": round(float(area_share), 6),
        "skin_pixel_share": round(float(skin_share), 4),
        "median_l": round(median_l, 2),
    }


def _cluster_recovery_candidates(candidates: list[dict]) -> list[dict]:
    clusters: list[dict] = []
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        matching = next(
            (
                cluster
                for cluster in clusters
                if _iou(candidate["box"], cluster["box"]) >= 0.25
            ),
            None,
        )
        if matching is None:
            clusters.append(
                {
                    "box": candidate["box"],
                    "score": candidate["score"],
                    "support": 1,
                    "area": candidate["box"][2] * candidate["box"][3],
                    "anchor_geometry": candidate["anchor_geometry"],
                }
            )
        else:
            matching["support"] += 1
            if candidate["score"] > matching["score"]:
                matching["box"] = candidate["box"]
                matching["score"] = candidate["score"]
                matching["area"] = candidate["box"][2] * candidate["box"][3]
                matching["anchor_geometry"] = candidate["anchor_geometry"]
    for cluster in clusters:
        cluster["rank_score"] = round(
            cluster["score"] + min(0.15, 0.04 * (cluster["support"] - 1)), 3
        )
    return clusters


def _select_recovery_cluster(clusters: list[dict]) -> tuple[dict | None, str | None]:
    ranked = sorted(clusters, key=lambda item: item["rank_score"], reverse=True)
    if not ranked:
        return None, "no_face_candidate"
    if len(ranked) > 1:
        first, second = ranked[:2]
        comparable_area = 0.45 <= second["area"] / max(first["area"], 1) <= 2.2
        comparable_score = second["rank_score"] >= first["rank_score"] - 0.12
        if comparable_area and comparable_score:
            return None, "ambiguous_multiple_faces"
    return ranked[0], None


def _ellipse_mask(
    shape: tuple[int, int], cx: float, cy: float, rx: float, ry: float
) -> np.ndarray:
    height, width = shape
    yy, xx = np.mgrid[:height, :width]
    return ((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2 <= 1


def _oriented_ellipse_mask(
    shape: tuple[int, int],
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    angle_degrees: float,
) -> np.ndarray:
    if abs(angle_degrees) < 1e-6:
        return _ellipse_mask(shape, cx, cy, rx, ry)
    height, width = shape
    yy, xx = np.mgrid[:height, :width]
    dx, dy = xx - cx, yy - cy
    radians = np.deg2rad(angle_degrees)
    cosine, sine = np.cos(radians), np.sin(radians)
    local_x = cosine * dx + sine * dy
    local_y = -sine * dx + cosine * dy
    return (local_x / max(rx, 1)) ** 2 + (local_y / max(ry, 1)) ** 2 <= 1


def _base_skin_mask(
    rgb: np.ndarray, lab: np.ndarray, valid_mask: np.ndarray
) -> np.ndarray:
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    _, cr, cb = [ycrcb[..., index] for index in range(3)]
    red, green, blue = [rgb[..., index].astype(np.int16) for index in range(3)]
    lightness = lab[..., 0]
    chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
    candidates = (
        valid_mask
        & (cr >= 123)
        & (cr <= 193)
        & (cb >= 68)
        & (cb <= 148)
        & (red > green - 10)
        & (red > blue - 15)
        & (lightness > 18)
        & (lightness < 97)
        & (lab[..., 1] > -4)
        & (lab[..., 1] < 38)
        & (lab[..., 2] > -12)
        & (lab[..., 2] < 45)
        & (chroma < 52)
    )
    # Remove isolated single-pixel color noise while retaining softly focused
    # facial regions. This operates on the working image only and never changes
    # source pixels.
    kernel = np.ones((3, 3), dtype=np.uint8)
    continuous = cv2.morphologyEx(candidates.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    continuous = cv2.morphologyEx(continuous, cv2.MORPH_CLOSE, kernel)
    return continuous.astype(bool) & valid_mask


def skin_candidate_mask(
    rgb: np.ndarray, lab: np.ndarray, valid_mask: np.ndarray
) -> np.ndarray:
    """Expose the existing conservative skin candidates for quantitative ROI use.

    This wrapper deliberately keeps the formal skin-anchor algorithm unchanged.
    Quantitative subject/background measurements may further restrict this mask,
    but must never broaden it or replace insufficient samples with a full face box.
    """

    return _base_skin_mask(rgb, lab, valid_mask)


def _robust_sample(
    rgb: np.ndarray, lab: np.ndarray, skin_mask: np.ndarray, roi: np.ndarray
) -> dict | None:
    target = roi & skin_mask
    roi_count = int(roi.sum())
    if target.sum() < 30 or roi_count <= 0:
        return None
    values_rgb = rgb[target].astype(np.float32)
    values_lab = lab[target]
    median_lab = np.median(values_lab, axis=0)
    mad = np.median(np.abs(values_lab - median_lab), axis=0) + 1e-3
    keep = np.all(np.abs(values_lab - median_lab) <= 3.0 * mad, axis=1)
    values_rgb = values_rgb[keep]
    values_lab = values_lab[keep]
    if values_rgb.shape[0] < 20:
        return None
    rgb_median = np.median(values_rgb, axis=0)
    lab_value = rgb2lab((rgb_median / 255.0).reshape(1, 1, 3))[0, 0]
    rgb_values = [int(round(value)) for value in rgb_median]
    lightness_iqr = float(
        np.percentile(values_lab[:, 0], 75) - np.percentile(values_lab[:, 0], 25)
    )
    lightness_mad = float(
        np.median(np.abs(values_lab[:, 0] - np.median(values_lab[:, 0])))
    )
    valid_ratio = float(values_rgb.shape[0] / roi_count)
    shadow_contamination = float(np.mean(values_lab[:, 0] < 30))
    highlight_contamination = float(np.mean(values_lab[:, 0] > 90))
    ab_dispersion = float(
        np.median(
            np.sqrt(
                (values_lab[:, 1] - np.median(values_lab[:, 1])) ** 2
                + (values_lab[:, 2] - np.median(values_lab[:, 2])) ** 2
            )
        )
    )
    ratio_quality = min(valid_ratio / 0.45, 1.0)
    uniform_quality = max(0.0, 1.0 - min(lightness_iqr / 28.0, 1.0))
    lightness = float(lab_value[0])
    light_quality = (
        1.0 if 40 <= lightness <= 86 else max(0.25, 1 - abs(lightness - 63) / 45)
    )
    confidence = min(
        1.0, 0.45 * ratio_quality + 0.35 * uniform_quality + 0.20 * light_quality
    )
    return {
        "rgb": rgb_values,
        "hex": "#" + "".join(f"{value:02X}" for value in rgb_values),
        "lab": {
            "l": round(float(lab_value[0]), 2),
            "a": round(float(lab_value[1]), 2),
            "b": round(float(lab_value[2]), 2),
        },
        "valid_ratio": round(valid_ratio, 3),
        "lightness_iqr": round(lightness_iqr, 2),
        "lightness_mad": round(lightness_mad, 2),
        "shadow_contamination": round(shadow_contamination, 4),
        "highlight_contamination": round(highlight_contamination, 4),
        "ab_dispersion": round(ab_dispersion, 2),
        "confidence": round(float(confidence), 3),
        "sample_count": int(values_rgb.shape[0]),
    }


def analyze_skin_anchors(
    rgb: np.ndarray,
    lab: np.ndarray,
    valid_mask: np.ndarray,
    detection: FaceDetection,
) -> dict:
    anchor_started = time.perf_counter()
    backend_meta = {
        "detector": detection.detector,
        "requested_backend": detection.requested_backend,
        "available_backends": detection.available_backends,
        "backend_degraded": detection.degraded,
        "backend_note": detection.note,
    }
    detection_diagnostics = {
        "face_candidates": detection.face_candidates,
        "backend": detection.detector,
        "recovery_used": detection.recovery_used,
        "failure_stage": detection.failure_stage,
        "failure_reason": detection.failure_reason,
        "primary_anchor_reason": None,
        "secondary_anchor_reason": None,
        "performance": {
            "face_detection_ms": detection.face_detection_ms,
            "recovery_detection_ms": detection.recovery_detection_ms,
            "skin_anchor_ms": 0.0,
        },
    }

    def finish(
        result: dict, *, stage: str | None = None, reason: str | None = None
    ) -> dict:
        diagnostics = dict(detection_diagnostics)
        if stage is not None:
            diagnostics["failure_stage"] = stage
        if reason is not None:
            diagnostics["failure_reason"] = reason
        diagnostics["performance"] = dict(diagnostics["performance"])
        diagnostics["performance"]["skin_anchor_ms"] = round(
            (time.perf_counter() - anchor_started) * 1000, 3
        )
        result["diagnostics"] = diagnostics
        return result

    if detection.detector in {"disabled", "unavailable"}:
        return finish(
            {
                "status": "未验证",
                "face_count": None,
                **backend_meta,
                "primary_anchor": None,
                "secondary_anchor": None,
            },
            stage="no_face_candidate",
            reason=detection.failure_reason or "no_face_candidate",
        )
    if not detection.boxes:
        return finish(
            {
                "status": "无人像",
                "face_count": 0,
                **backend_meta,
                "primary_anchor": None,
                "secondary_anchor": None,
            },
            stage=detection.failure_stage or "no_face_candidate",
            reason=detection.failure_reason or "no_face_candidate",
        )
    if len(detection.boxes) > 1:
        return finish(
            {
                "status": "多人不合并",
                "face_count": len(detection.boxes),
                **backend_meta,
                "primary_anchor": None,
                "secondary_anchor": None,
            },
            stage="multiple_faces",
            reason="multiple_faces",
        )

    x, y, width, height = detection.boxes[0]
    geometry = detection.anchor_geometry or {}
    anchor_face_width = int(geometry.get("face_width", width))
    orientation = float(geometry.get("orientation_degrees", 0.0))
    cheek_centers = geometry.get("cheek_centers") or [
        [x + 0.32 * width, y + 0.64 * height],
        [x + 0.68 * width, y + 0.64 * height],
    ]
    skin_mask = _base_skin_mask(rgb, lab, valid_mask)
    candidates: list[dict] = []
    for side, center in zip(("左侧", "右侧"), cheek_centers, strict=True):
        cx, cy = center
        roi = _oriented_ellipse_mask(
            rgb.shape[:2],
            cx,
            cy,
            0.115 * anchor_face_width,
            0.085 * anchor_face_width,
            orientation,
        )
        sample = _robust_sample(rgb, lab, skin_mask, roi)
        if sample:
            sample.update({"side": side, "center": [round(cx, 2), round(cy, 2)]})
            lightness = sample["lab"]["l"]
            penalty = (
                (0.12 if lightness > 88 else 0.0)
                + (0.10 if lightness < 36 else 0.0)
                + 0.18 * sample["highlight_contamination"]
                + 0.18 * sample["shadow_contamination"]
                + min(sample["ab_dispersion"] / 100.0, 0.12)
            )
            stability = max(0.0, 1.0 - sample["lightness_mad"] / 18.0)
            sample["selection_score"] = round(
                max(0.0, 0.82 * sample["confidence"] + 0.18 * stability - penalty),
                3,
            )
            candidates.append(sample)

    primary = (
        max(candidates, key=lambda item: item["selection_score"])
        if candidates
        else None
    )
    if primary:
        lightness = primary["lab"]["l"]
        if primary["selection_score"] >= 0.72 and 36 <= lightness <= 88:
            primary["status"], primary["status_code"] = "有效", "valid"
            primary_reason = "valid"
        elif primary["selection_score"] >= 0.58:
            primary["status"], primary["status_code"] = "仅供参考", "low_confidence"
            primary_reason = "high_variance"
        else:
            primary["status"], primary["status_code"] = "样本不足", "insufficient"
            primary_reason = "primary_roi_invalid"
        primary["crop"] = _crop_spec(
            primary["center"], anchor_face_width, rgb.shape, factor=0.24
        )
    else:
        primary_reason = "skin_pixel_share_low"

    forehead_center = geometry.get("forehead_center") or [
        x + 0.50 * width,
        y + 0.20 * height,
    ]
    forehead_roi = _oriented_ellipse_mask(
        rgb.shape[:2],
        forehead_center[0],
        forehead_center[1],
        0.14 * anchor_face_width,
        0.065 * anchor_face_width,
        orientation,
    )
    secondary = _robust_sample(rgb, lab, skin_mask, forehead_roi)
    if secondary:
        secondary["center"] = [
            round(forehead_center[0], 2),
            round(forehead_center[1], 2),
        ]
        lightness = secondary["lab"]["l"]
        if secondary["confidence"] >= 0.74 and 36 <= lightness <= 92:
            secondary["status"], secondary["status_code"] = "有效", "valid"
            secondary_reason = "valid"
        elif secondary["confidence"] >= 0.58:
            secondary["status"], secondary["status_code"] = "仅供参考", "low_confidence"
            secondary_reason = "high_variance"
        else:
            secondary["status"], secondary["status_code"] = "样本不足", "insufficient"
            secondary_reason = "secondary_anchor_invalid"
        secondary["crop"] = _crop_spec(
            secondary["center"], anchor_face_width, rgb.shape, factor=0.20
        )
    else:
        secondary_reason = "secondary_anchor_invalid"

    result = {
        "status": "单人",
        "face_count": 1,
        **backend_meta,
        "face_box": [x, y, width, height],
        "primary_anchor": primary,
        "secondary_anchor": secondary,
    }
    detection_diagnostics["primary_anchor_reason"] = primary_reason
    detection_diagnostics["secondary_anchor_reason"] = secondary_reason
    if primary and primary.get("status_code") == "valid":
        return finish(result, stage="valid", reason="valid")
    return finish(result, stage="primary_roi_invalid", reason=primary_reason)


def _crop_spec(
    center: list[float],
    face_width: int,
    shape: tuple[int, int, int],
    *,
    factor: float = 0.24,
) -> dict:
    height, width = shape[:2]
    side = max(64, min(int(round(face_width * factor)), min(height, width)))
    cx, cy = center
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    left = max(0, min(left, width - side))
    top = max(0, min(top, height - side))
    return {"x": left, "y": top, "width": side, "height": side, "ratio": "1:1"}
