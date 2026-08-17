from __future__ import annotations

from dataclasses import dataclass
import os
import numpy as np
import cv2
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
    requested = (backend or os.getenv("COLOR_PALETTE_FACE_BACKEND") or DEFAULT_FACE_BACKEND).lower()
    if requested not in FACE_BACKENDS:
        raise ValueError(
            f"不支持的人脸后端：{requested}；可选值为auto/opencv/dlib/none"
        )
    return requested


def detect_faces(rgb: np.ndarray, backend: str | None = None) -> FaceDetection:
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
        )

    # The portable default is OpenCV-only. `auto` prefers dlib when available
    # and otherwise degrades to OpenCV. An explicit unavailable dlib request
    # degrades safely instead of aborting the whole color analysis.
    use_dlib = requested in {"auto", "dlib"} and dlib is not None
    use_opencv = requested in {"auto", "opencv"} or (requested == "dlib" and dlib is None)
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
            if len(dlib_rects) <= 1 and min(height, width) >= 500 and max(height, width) <= 1200:
                dlib_rects.extend(detector(rgb, 2))
            for rect in dlib_rects:
                boxes.append([
                    max(0, int(rect.left())),
                    max(0, int(rect.top())),
                    int(rect.width()),
                    int(rect.height()),
                ])
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
            boxes.extend([[int(x), int(y), int(w), int(h)] for x, y, w, h in detections])
            if len(detections):
                detectors.append("opencv")

    boxes = _nms(boxes)
    image_area = width * height
    significant = [
        box for box in boxes
        if box[2] >= 70 and box[3] >= 70 and (box[2] * box[3]) / image_area >= 0.012
    ]
    return FaceDetection(
        boxes=significant,
        detector="+".join(sorted(set(detectors))) or (
            "opencv" if use_opencv else "unavailable"
        ),
        requested_backend=requested,
        available_backends=available,
        degraded=degraded,
        note=note,
    )


def _ellipse_mask(shape: tuple[int, int], cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    height, width = shape
    yy, xx = np.mgrid[:height, :width]
    return ((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2 <= 1


def _base_skin_mask(rgb: np.ndarray, lab: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    _, cr, cb = [ycrcb[..., index] for index in range(3)]
    red, green, blue = [rgb[..., index].astype(np.int16) for index in range(3)]
    lightness = lab[..., 0]
    return (
        valid_mask
        & (cr >= 123)
        & (cr <= 193)
        & (cb >= 68)
        & (cb <= 148)
        & (red > green - 10)
        & (red > blue - 15)
        & (lightness > 18)
        & (lightness < 97)
    )


def _robust_sample(rgb: np.ndarray, lab: np.ndarray, skin_mask: np.ndarray, roi: np.ndarray) -> dict | None:
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
    lightness_iqr = float(np.percentile(values_lab[:, 0], 75) - np.percentile(values_lab[:, 0], 25))
    valid_ratio = float(values_rgb.shape[0] / roi_count)
    ratio_quality = min(valid_ratio / 0.45, 1.0)
    uniform_quality = max(0.0, 1.0 - min(lightness_iqr / 28.0, 1.0))
    lightness = float(lab_value[0])
    light_quality = 1.0 if 40 <= lightness <= 86 else max(0.25, 1 - abs(lightness - 63) / 45)
    confidence = min(1.0, 0.45 * ratio_quality + 0.35 * uniform_quality + 0.20 * light_quality)
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
        "confidence": round(float(confidence), 3),
        "sample_count": int(values_rgb.shape[0]),
    }


def analyze_skin_anchors(
    rgb: np.ndarray,
    lab: np.ndarray,
    valid_mask: np.ndarray,
    detection: FaceDetection,
) -> dict:
    backend_meta = {
        "detector": detection.detector,
        "requested_backend": detection.requested_backend,
        "available_backends": detection.available_backends,
        "backend_degraded": detection.degraded,
        "backend_note": detection.note,
    }
    if detection.detector in {"disabled", "unavailable"}:
        return {
            "status": "未验证",
            "face_count": None,
            **backend_meta,
            "primary_anchor": None,
            "secondary_anchor": None,
        }
    if not detection.boxes:
        return {
            "status": "无人像",
            "face_count": 0,
            **backend_meta,
            "primary_anchor": None,
            "secondary_anchor": None,
        }
    if len(detection.boxes) > 1:
        return {
            "status": "多人不合并",
            "face_count": len(detection.boxes),
            **backend_meta,
            "primary_anchor": None,
            "secondary_anchor": None,
        }

    x, y, width, height = detection.boxes[0]
    skin_mask = _base_skin_mask(rgb, lab, valid_mask)
    candidates: list[dict] = []
    for side, x_factor in [("左侧", 0.31), ("右侧", 0.69)]:
        cx = x + x_factor * width
        cy = y + 0.58 * height
        roi = _ellipse_mask(rgb.shape[:2], cx, cy, 0.115 * width, 0.085 * height)
        sample = _robust_sample(rgb, lab, skin_mask, roi)
        if sample:
            sample.update({"side": side, "center": [round(cx, 2), round(cy, 2)]})
            lightness = sample["lab"]["l"]
            penalty = (0.12 if lightness > 84 else 0.0) + (0.10 if lightness < 40 else 0.0)
            sample["selection_score"] = round(max(0.0, sample["confidence"] - penalty), 3)
            candidates.append(sample)

    primary = max(candidates, key=lambda item: item["selection_score"]) if candidates else None
    if primary:
        lightness = primary["lab"]["l"]
        if primary["selection_score"] >= 0.78 and 40 <= lightness <= 84:
            primary["status"] = "有效"
        elif primary["selection_score"] >= 0.68:
            primary["status"] = "仅供参考"
        else:
            primary["status"] = "样本不足"
        primary["crop"] = _crop_spec(primary["center"], width, rgb.shape)

    forehead_center = [x + 0.50 * width, y + 0.23 * height]
    forehead_roi = _ellipse_mask(
        rgb.shape[:2],
        forehead_center[0],
        forehead_center[1],
        0.14 * width,
        0.065 * height,
    )
    secondary = _robust_sample(rgb, lab, skin_mask, forehead_roi)
    if secondary:
        secondary["center"] = [round(forehead_center[0], 2), round(forehead_center[1], 2)]
        lightness = secondary["lab"]["l"]
        secondary["status"] = (
            "有效" if secondary["confidence"] >= 0.80 and 40 <= lightness <= 92 else "样本不足"
        )
        secondary["crop"] = _crop_spec(secondary["center"], width, rgb.shape)

    return {
        "status": "单人",
        "face_count": 1,
        **backend_meta,
        "face_box": [x, y, width, height],
        "primary_anchor": primary,
        "secondary_anchor": secondary,
    }


def _crop_spec(center: list[float], face_width: int, shape: tuple[int, int, int]) -> dict:
    height, width = shape[:2]
    side = max(80, min(int(round(face_width * 0.36)), min(height, width)))
    cx, cy = center
    left = int(round(cx - side / 2))
    top = int(round(cy - side / 2))
    left = max(0, min(left, width - side))
    top = max(0, min(top, height - side))
    return {"x": left, "y": top, "width": side, "height": side, "ratio": "1:1"}
