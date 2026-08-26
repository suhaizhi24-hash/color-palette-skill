from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

from .constants import DEFAULT_FACE_BACKEND, FACE_BACKENDS

try:
    import dlib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    dlib = None


ANCHOR_COHERENCE_LARGE_DE00 = 14.0
ANCHOR_COHERENCE_LARGE_DELTA_L = 15.0
ANCHOR_COHERENCE_LARGE_DELTA_A = 8.0
ANCHOR_COHERENCE_LARGE_DELTA_B = 12.0
ANCHOR_COHERENCE_LARGE_DELTA_C = 14.0
CHEEK_VALID_SCORE = 0.72
CHEEK_LOW_CONFIDENCE_SCORE = 0.58


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
    raw_face_candidate_count: int | None = None
    valid_face_count: int | None = None
    primary_face_id: str | None = None
    primary_face_score: float | None = None
    candidate_scores: list[dict] = field(default_factory=list)
    candidate_rejections: list[dict] = field(default_factory=list)
    valid_faces: list[dict] = field(default_factory=list)
    multi_face_block_reason: str | None = None
    skin_output_decision: str | None = None


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


def _center_distance_ratio(a: list[int], b: list[int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    distance = float(
        np.hypot((ax + aw / 2.0) - (bx + bw / 2.0), (ay + ah / 2.0) - (by + bh / 2.0))
    )
    reference = max(1.0, min(np.hypot(aw, ah), np.hypot(bw, bh)))
    return distance / reference


def _merge_face_candidate_records(records: list[dict]) -> list[dict]:
    """Merge duplicate detector boxes without merging neighbouring people."""

    merged: list[dict] = []
    for record in sorted(
        records, key=lambda item: item["box"][2] * item["box"][3], reverse=True
    ):
        match = next(
            (
                existing
                for existing in merged
                if _iou(record["box"], existing["box"]) >= 0.35
                or _center_distance_ratio(record["box"], existing["box"]) <= 0.18
            ),
            None,
        )
        if match is None:
            copied = dict(record)
            copied["detector_sources"] = [record["detector_source"]]
            copied["duplicate_count"] = 1
            merged.append(copied)
            continue
        match["duplicate_count"] += 1
        if record["detector_source"] not in match["detector_sources"]:
            match["detector_sources"].append(record["detector_source"])
        match["detector_confidence"] = max(
            match["detector_confidence"], record["detector_confidence"]
        )
    return merged


def _opencv_detections(
    cascade: cv2.CascadeClassifier,
    gray: np.ndarray,
    *,
    scale_factor: float,
    min_neighbors: int,
    min_size: tuple[int, int],
) -> list[tuple[list[int], float]]:
    """Return Haar boxes with a normalized confidence when OpenCV exposes it."""

    if hasattr(cascade, "detectMultiScale3"):
        try:
            boxes, _, weights = cascade.detectMultiScale3(
                gray,
                scaleFactor=scale_factor,
                minNeighbors=min_neighbors,
                minSize=min_size,
                outputRejectLevels=True,
            )
            return [
                (
                    [int(x), int(y), int(width), int(height)],
                    round(float(0.5 + 0.5 * np.tanh(float(weight) / 3.0)), 4),
                )
                for (x, y, width, height), weight in zip(boxes, weights, strict=True)
            ]
        except (AttributeError, TypeError, cv2.error):
            pass
    boxes = cascade.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=min_size,
    )
    return [
        ([int(x), int(y), int(width), int(height)], 0.75)
        for x, y, width, height in boxes
    ]


def _eye_landmark_support(gray: np.ndarray, box: list[int]) -> tuple[int, float]:
    x, y, width, height = box
    upper = gray[y : y + max(1, int(round(0.64 * height))), x : x + width]
    if upper.size == 0:
        return 0, 0.0
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    if cascade.empty():
        return 0, 0.0
    eyes = cascade.detectMultiScale(
        upper,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(max(12, width // 12), max(12, height // 12)),
    )
    plausible = []
    for eye_x, eye_y, eye_width, eye_height in eyes:
        center_y = eye_y + eye_height / 2.0
        if center_y <= 0.58 * height:
            plausible.append((eye_x + eye_width / 2.0, center_y))
    count = min(len(plausible), 2)
    if count >= 2:
        xs = sorted(point[0] for point in plausible)
        separation = (xs[-1] - xs[0]) / max(width, 1)
        completeness = 1.0 if 0.18 <= separation <= 0.72 else 0.72
    elif count == 1:
        completeness = 0.55
    else:
        completeness = 0.0
    return count, completeness


def _baseline_anchor_geometry(gray: np.ndarray, box: list[int]) -> dict | None:
    """Derive sampling geometry from two plausible eyes after face selection.

    This geometry is intentionally downstream of face candidate filtering: it
    can improve cheek placement, but it cannot turn a raw candidate into a
    valid person or change single/multi-person protection.
    """

    x, y, width, height = box
    upper = gray[y : y + max(1, int(round(0.64 * height))), x : x + width]
    if upper.size == 0:
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    if cascade.empty():
        return None
    eyes = cascade.detectMultiScale(
        upper,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(max(12, width // 12), max(12, height // 12)),
    )
    points = [
        np.array([x + ex + eye_width / 2.0, y + ey + eye_height / 2.0])
        for ex, ey, eye_width, eye_height in eyes
        if ey + eye_height / 2.0 <= 0.58 * height
    ]
    if len(points) < 2:
        return None
    pairs = sorted(
        (
            (left, right)
            for index, left in enumerate(points)
            for right in points[index + 1 :]
        ),
        key=lambda pair: abs(float(pair[1][0] - pair[0][0])),
        reverse=True,
    )
    eye_a, eye_b = pairs[0]
    if eye_a[0] > eye_b[0]:
        eye_a, eye_b = eye_b, eye_a
    vector = eye_b - eye_a
    distance = float(np.linalg.norm(vector))
    if not 0.18 * width <= distance <= 0.72 * width:
        return None
    unit_x = vector / max(distance, 1e-6)
    angle = float(np.degrees(np.arctan2(unit_x[1], unit_x[0])))
    if abs(angle) > 35.0:
        return None
    unit_down = np.array([-unit_x[1], unit_x[0]])
    if unit_down[1] < 0:
        unit_down *= -1
    cheek_a = eye_a + 0.58 * distance * unit_down + 0.04 * distance * unit_x
    cheek_b = eye_b + 0.58 * distance * unit_down - 0.04 * distance * unit_x
    forehead = np.array([x + 0.50 * width, y + 0.20 * height])
    image_height, image_width = gray.shape[:2]

    def clipped(point: np.ndarray) -> list[float]:
        return [
            round(float(np.clip(point[0], 0, image_width - 1)), 2),
            round(float(np.clip(point[1], 0, image_height - 1)), 2),
        ]

    return {
        "cheek_centers": [clipped(cheek_a), clipped(cheek_b)],
        "forehead_center": clipped(forehead),
        "eye_centers": [clipped(eye_a), clipped(eye_b)],
        "face_width": int(width),
        "face_height": int(height),
        "orientation_degrees": round(angle, 2),
        "cheek_orientation_degrees": round(angle, 2),
        "forehead_orientation_degrees": 0.0,
        "geometry_source": "eye_landmarks",
    }


def _face_quality_record(
    record: dict,
    *,
    rgb: np.ndarray,
    gray: np.ndarray,
    lab: np.ndarray,
    skin_mask: np.ndarray,
) -> dict:
    """Score a detector candidate using independent, explainable evidence."""

    height, width = rgb.shape[:2]
    x, y, box_width, box_height = record["box"]
    image_area = max(height * width, 1)
    area_share = box_width * box_height / image_area
    core = _ellipse_mask(
        (height, width),
        x + 0.50 * box_width,
        y + 0.53 * box_height,
        0.34 * box_width,
        0.40 * box_height,
    )
    core_count = int(core.sum())
    skin_share = float((core & skin_mask).sum() / max(core_count, 1))
    core_l = lab[..., 0][core]
    median_l = float(np.median(core_l)) if core_l.size else 0.0

    crop = gray[y : y + box_height, x : x + box_width]
    sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
    eye_count, landmark_completeness = _eye_landmark_support(gray, record["box"])

    center_x = (x + box_width / 2.0) / max(width, 1)
    center_y = (y + box_height / 2.0) / max(height, 1)
    center_distance = np.hypot(center_x - 0.5, center_y - 0.45)
    center_proximity = max(0.0, 1.0 - float(center_distance) / 0.72)
    edge_margin = min(x, y, width - (x + box_width), height - (y + box_height))
    edge_margin_ratio = edge_margin / max(min(box_width, box_height), 1)

    ring = (
        _ellipse_mask(
            (height, width),
            x + 0.50 * box_width,
            y + 0.53 * box_height,
            0.48 * box_width,
            0.56 * box_height,
        )
        & ~core
    )
    if core.any() and ring.any():
        core_lab = np.median(lab[core], axis=0)
        ring_lab = np.median(lab[ring], axis=0)
        background_separation = float(np.linalg.norm(core_lab - ring_lab))
    else:
        background_separation = 0.0

    aspect = box_width / max(box_height, 1)
    aspect_quality = max(0.0, 1.0 - abs(aspect - 1.0) / 0.48)
    frontalness = min(1.0, 0.55 * aspect_quality + 0.45 * landmark_completeness)
    detector_confidence = float(record.get("detector_confidence", 0.75))
    area_quality = min(area_share / 0.04, 1.0)
    sharpness_score = min(np.log1p(sharpness) / np.log1p(500.0), 1.0)
    skin_support = min(skin_share / 0.55, 1.0)
    separation_score = min(background_separation / 15.0, 1.0)
    score = (
        0.10 * detector_confidence
        + 0.12 * area_quality
        + 0.08 * center_proximity
        + 0.25 * landmark_completeness
        + 0.10 * sharpness_score
        + 0.25 * skin_support
        + 0.05 * frontalness
        + 0.05 * separation_score
    )

    rejection_reasons: list[str] = []
    if area_share < 0.008 or box_width < 70 or box_height < 70:
        rejection_reasons.append("bbox_too_small")
    if edge_margin_ratio < -0.02:
        rejection_reasons.append("extreme_edge")
    if not 0.68 <= aspect <= 1.48:
        rejection_reasons.append("pose_or_aspect_invalid")
    if skin_share < 0.18:
        rejection_reasons.append("skin_pixel_share_low")
    if skin_share < 0.28:
        rejection_reasons.append("accessory_or_hair_contamination_high")
    if (
        eye_count == 0
        and background_separation < 8.0
        and (skin_share < 0.45 or median_l > 88.0 or sharpness_score < 0.35)
    ):
        rejection_reasons.append("landmarks_missing")
    if sharpness_score < 0.35 and background_separation < 8.0 and eye_count == 0:
        rejection_reasons.append("background_blur_pattern")
    if median_l > 90.0 and background_separation < 8.0 and eye_count == 0:
        rejection_reasons.append("face_like_highlight_pattern")
    if not 18.0 <= median_l <= 95.0:
        rejection_reasons.append("luminance_out_of_range")
    if score < 0.56:
        rejection_reasons.append("face_quality_score_low")

    candidate = {
        **record,
        "accepted": not rejection_reasons,
        "score": round(float(score), 4),
        "reason": "valid" if not rejection_reasons else rejection_reasons[0],
        "rejection_reasons": rejection_reasons,
        "area_share": round(float(area_share), 6),
        "center_proximity": round(float(center_proximity), 4),
        "landmark_completeness": round(float(landmark_completeness), 4),
        "eye_landmark_count": eye_count,
        "sharpness": round(float(sharpness), 4),
        "sharpness_score": round(float(sharpness_score), 4),
        "skin_pixel_share": round(float(skin_share), 4),
        "median_l": round(float(median_l), 2),
        "frontalness": round(float(frontalness), 4),
        "background_separation": round(float(background_separation), 4),
        "edge_margin_ratio": round(float(edge_margin_ratio), 4),
        "score_components": {
            "detector_confidence": round(detector_confidence, 4),
            "bbox_area": round(float(area_quality), 4),
            "image_center_proximity": round(float(center_proximity), 4),
            "landmark_completeness": round(float(landmark_completeness), 4),
            "sharpness": round(float(sharpness_score), 4),
            "skin_pixel_share": round(float(skin_support), 4),
            "frontalness": round(float(frontalness), 4),
            "background_separation": round(float(separation_score), 4),
        },
    }
    return candidate


def _select_valid_faces(candidates: list[dict]) -> tuple[list[dict], dict | None]:
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    accepted = [candidate for candidate in ranked if candidate["accepted"]]
    primary = accepted[0] if accepted else None
    if primary is None:
        return [], None

    valid: list[dict] = [primary]
    primary_area = primary["box"][2] * primary["box"][3]
    for candidate in accepted[1:]:
        candidate_area = candidate["box"][2] * candidate["box"][3]
        area_ratio = candidate_area / max(primary_area, 1)
        score_gap = primary["score"] - candidate["score"]
        meaningful = (
            candidate["landmark_completeness"] >= 0.55
            and candidate["skin_pixel_share"] >= 0.28
            and candidate["score"] >= 0.62
        )
        if area_ratio < 0.30 and score_gap >= 0.16 and not meaningful:
            candidate["accepted"] = False
            candidate["reason"] = "area_too_small_vs_primary"
            candidate["rejection_reasons"].append("area_too_small_vs_primary")
            continue
        valid.append(candidate)
    return valid, primary


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

    raw_records: list[dict] = []
    detectors: list[str] = []
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

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
                raw_records.append(
                    {
                        "box": [
                            max(0, int(rect.left())),
                            max(0, int(rect.top())),
                            int(rect.width()),
                            int(rect.height()),
                        ],
                        "detector_source": "dlib",
                        "detector_confidence": 0.85,
                    }
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
        cascade_paths = [
            (
                "opencv_frontal",
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
            ),
            (
                "opencv_profile",
                cv2.data.haarcascades + "haarcascade_profileface.xml",
            ),
        ]
        for detector_source, cascade_path in cascade_paths:
            cascade = cv2.CascadeClassifier(cascade_path)
            if cascade.empty():
                continue
            detections = _opencv_detections(
                cascade,
                gray,
                scale_factor=1.1,
                min_neighbors=5,
                min_size=(70, 70),
            )
            raw_records.extend(
                {
                    "box": box,
                    "detector_source": detector_source,
                    "detector_confidence": confidence,
                }
                for box, confidence in detections
            )
            if detections:
                detectors.append("opencv")

    image_area = width * height
    merged_records = _merge_face_candidate_records(raw_records)
    significant_records = [
        record
        for record in merged_records
        if record["box"][2] >= 70
        and record["box"][3] >= 70
        and (record["box"][2] * record["box"][3]) / image_area >= 0.012
    ]
    for index, record in enumerate(significant_records, start=1):
        record["candidate_id"] = f"face_candidate_{index}"

    if significant_records:
        lab = rgb2lab(rgb.astype(np.float32) / 255.0)
        skin_mask = _base_skin_mask(rgb, lab, np.ones((height, width), dtype=bool))
        baseline_candidates = [
            _face_quality_record(
                record,
                rgb=rgb,
                gray=gray,
                lab=lab,
                skin_mask=skin_mask,
            )
            for record in significant_records
        ]
        valid_records, primary_record = _select_valid_faces(baseline_candidates)
    else:
        baseline_candidates = []
        valid_records, primary_record = [], None

    baseline_ms = round((time.perf_counter() - detection_started) * 1000, 3)
    for candidate in baseline_candidates:
        candidate.update(
            {"source": "baseline", "preprocessing": "original", "angle": 0}
        )

    recovery_used = False
    recovery_ms = 0.0
    failure_stage: str | None = None
    failure_reason: str | None = None
    face_candidates = baseline_candidates
    final_boxes = [candidate["box"] for candidate in valid_records]
    anchor_geometry = None
    if significant_records and not final_boxes:
        failure_stage = "face_low_confidence"
        failure_reason = "no_valid_face_candidate"
    if not significant_records and use_opencv:
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

        for index, candidate in enumerate(face_candidates, start=1):
            candidate.setdefault("candidate_id", f"recovery_candidate_{index}")
        if final_boxes:
            primary_record = next(
                (
                    candidate
                    for candidate in sorted(
                        face_candidates, key=lambda item: item["score"], reverse=True
                    )
                    if candidate.get("accepted")
                    and _iou(candidate["box"], final_boxes[0]) >= 0.25
                ),
                None,
            )
            valid_records = [primary_record] if primary_record else []

    if anchor_geometry is None and len(final_boxes) == 1:
        anchor_geometry = _baseline_anchor_geometry(gray, final_boxes[0])
        if anchor_geometry is not None and primary_record is not None:
            primary_record["anchor_geometry"] = anchor_geometry

    if len(final_boxes) >= 2:
        failure_stage = "multiple_faces"
        failure_reason = "multiple_meaningful_faces"

    primary_face_id = primary_record.get("candidate_id") if primary_record else None
    primary_face_score = primary_record.get("score") if primary_record else None
    candidate_scores = [
        {
            "candidate_id": candidate.get("candidate_id"),
            "box": candidate["box"],
            "score": candidate["score"],
            "accepted": candidate["accepted"],
            "score_components": candidate.get("score_components", {}),
        }
        for candidate in face_candidates
    ]
    candidate_rejections = [
        {
            "candidate_id": candidate.get("candidate_id"),
            "box": candidate["box"],
            "reasons": candidate.get("rejection_reasons", [candidate["reason"]]),
        }
        for candidate in face_candidates
        if not candidate["accepted"]
    ]
    valid_faces = [
        {
            "candidate_id": candidate.get("candidate_id"),
            "box": candidate["box"],
            "score": candidate["score"],
        }
        for candidate in valid_records
        if candidate is not None and candidate.get("accepted", True)
    ]
    if len(final_boxes) == 1:
        skin_output_decision = "single_face_allowed"
        multi_face_block_reason = None
    elif len(final_boxes) >= 2:
        skin_output_decision = "blocked_multiple_meaningful_faces"
        multi_face_block_reason = "valid_face_count_gte_2"
    elif failure_reason == "ambiguous_multiple_faces":
        skin_output_decision = "blocked_ambiguous_recovery_faces"
        multi_face_block_reason = "ambiguous_recovery_candidates"
    else:
        skin_output_decision = "insufficient_no_valid_face"
        multi_face_block_reason = None

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
        baseline_count=len(significant_records),
        recovery_used=recovery_used,
        face_candidates=face_candidates,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        face_detection_ms=baseline_ms,
        recovery_detection_ms=recovery_ms,
        anchor_geometry=anchor_geometry,
        raw_face_candidate_count=len(face_candidates),
        valid_face_count=len(final_boxes),
        primary_face_id=primary_face_id,
        primary_face_score=primary_face_score,
        candidate_scores=candidate_scores,
        candidate_rejections=candidate_rejections,
        valid_faces=valid_faces,
        multi_face_block_reason=multi_face_block_reason,
        skin_output_decision=skin_output_decision,
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
    target, accepted = _robust_sample_masks(lab, skin_mask, roi)
    roi_count = int(roi.sum())
    if target.sum() < 30 or roi_count <= 0 or accepted.sum() < 20:
        return None
    values_rgb = rgb[accepted].astype(np.float32)
    values_lab = lab[accepted]
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
    skin_pixel_share = float(target.sum() / roi_count)
    shadow_contamination = float(np.mean(values_lab[:, 0] < 30))
    highlight_contamination = float(np.mean(values_lab[:, 0] > 90))
    lightness_p25, lightness_median, lightness_p75 = np.percentile(
        values_lab[:, 0], [25, 50, 75]
    )
    a_median = float(np.median(values_lab[:, 1]))
    b_median = float(np.median(values_lab[:, 2]))
    chroma_median = float(
        np.median(np.sqrt(values_lab[:, 1] ** 2 + values_lab[:, 2] ** 2))
    )
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
        "skin_pixel_share": round(skin_pixel_share, 4),
        "rejected_pixel_share": round(float(1.0 - valid_ratio), 4),
        "lightness_p25": round(float(lightness_p25), 2),
        "lightness_median": round(float(lightness_median), 2),
        "lightness_p75": round(float(lightness_p75), 2),
        "a_median": round(a_median, 2),
        "b_median": round(b_median, 2),
        "chroma_median": round(chroma_median, 2),
        "lightness_iqr": round(lightness_iqr, 2),
        "lightness_mad": round(lightness_mad, 2),
        "shadow_contamination": round(shadow_contamination, 4),
        "highlight_contamination": round(highlight_contamination, 4),
        "ab_dispersion": round(ab_dispersion, 2),
        "confidence": round(float(confidence), 3),
        "sample_count": int(values_rgb.shape[0]),
    }


def _robust_sample_masks(
    lab: np.ndarray, skin_mask: np.ndarray, roi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return the pre-filter skin candidates and the robust accepted pixels."""

    target = roi & skin_mask
    accepted = np.zeros_like(target, dtype=bool)
    if int(target.sum()) < 30:
        return target, accepted
    values_lab = lab[target]
    median_lab = np.median(values_lab, axis=0)
    mad = np.median(np.abs(values_lab - median_lab), axis=0) + 1e-3
    keep = np.all(np.abs(values_lab - median_lab) <= 3.0 * mad, axis=1)
    accepted[target] = keep
    return target, accepted


def _mask_bbox_xywh(mask: np.ndarray) -> list[int]:
    ys, xs = np.where(mask)
    if xs.size == 0:
        return [0, 0, 0, 0]
    left, top = int(xs.min()), int(ys.min())
    return [left, top, int(xs.max()) - left + 1, int(ys.max()) - top + 1]


def _cheek_candidate(
    rgb: np.ndarray,
    lab: np.ndarray,
    skin_mask: np.ndarray,
    roi: np.ndarray,
    *,
    side: str,
    center: list[float],
) -> dict | None:
    sample = _robust_sample(rgb, lab, skin_mask, roi)
    if sample is None:
        return None
    _target, accepted = _robust_sample_masks(lab, skin_mask, roi)
    roi_count = max(int(roi.sum()), 1)
    rejected = roi & ~accepted
    lightness = lab[..., 0]
    chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
    hair_contamination = float((rejected & (lightness < 28)).sum() / roi_count)
    lip_contamination = float(
        (roi & (lab[..., 1] > 18) & (lab[..., 2] < 25) & (chroma > 28)).sum()
        / roi_count
    )
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 160) > 0
    local_edge_density = float(edges[roi].mean()) if roi.any() else 0.0

    stability = max(0.0, 1.0 - sample["lightness_mad"] / 18.0)
    skin_support = min(sample["skin_pixel_share"] / 0.55, 1.0)
    midtone_distance = abs(sample["lightness_median"] - 66.0)
    midtone_quality = max(0.0, 1.0 - max(0.0, midtone_distance - 18.0) / 28.0)
    hair_penalty = min(hair_contamination / 0.12, 1.0)
    lip_penalty = min(lip_contamination / 0.06, 1.0)
    edge_penalty = min(max(local_edge_density - 0.08, 0.0) / 0.18, 1.0)
    shadow_span_penalty = min(max(42.0 - sample["lightness_p25"], 0.0) / 20.0, 1.0)
    high_chroma_penalty = min(max(sample["chroma_median"] - 42.0, 0.0) / 18.0, 1.0)
    candidate_score = (
        0.55 * sample["confidence"]
        + 0.17 * stability
        + 0.14 * skin_support
        + 0.14 * midtone_quality
        - 0.18 * hair_penalty
        - 0.12 * lip_penalty
        - 0.08 * edge_penalty
        - 0.10 * shadow_span_penalty
        - 0.06 * high_chroma_penalty
        - 0.08 * sample["highlight_contamination"]
    )
    flags: list[str] = []
    if hair_contamination >= 0.06:
        flags.append("hair_contamination")
    if lip_contamination >= 0.04:
        flags.append("lip_contamination")
    if sample["lightness_p25"] < 42.0:
        flags.append("shadow_span")
    if sample["highlight_contamination"] >= 0.08:
        flags.append("highlight_hotspot")
    if local_edge_density >= 0.18:
        flags.append("high_local_edge_density")
    if sample["chroma_median"] >= 48.0:
        flags.append("high_chroma")

    sample.update(
        {
            "side": side,
            "center": [round(center[0], 2), round(center[1], 2)],
            "roi_bbox": _mask_bbox_xywh(roi),
            "accepted_skin_pixel_share": round(float(accepted.sum() / roi_count), 4),
            "rejected_pixel_share": round(float(rejected.sum() / roi_count), 4),
            "hair_contamination": round(hair_contamination, 4),
            "lip_contamination": round(lip_contamination, 4),
            "local_edge_density": round(local_edge_density, 4),
            "candidate_score": round(float(max(0.0, candidate_score)), 3),
            "contamination_flags": flags,
        }
    )
    return sample


def _anchor_deltas(primary: dict | None, secondary: dict | None) -> dict:
    empty = {
        "primary_secondary_delta_l": None,
        "primary_secondary_delta_a": None,
        "primary_secondary_delta_b": None,
        "primary_secondary_delta_e00": None,
    }
    if not primary or not secondary:
        return empty
    primary_lab = np.array(
        [primary["lab"]["l"], primary["lab"]["a"], primary["lab"]["b"]],
        dtype=np.float64,
    )
    secondary_lab = np.array(
        [secondary["lab"]["l"], secondary["lab"]["a"], secondary["lab"]["b"]],
        dtype=np.float64,
    )
    delta = primary_lab - secondary_lab
    delta_e = float(deltaE_ciede2000(primary_lab, secondary_lab))
    return {
        "primary_secondary_delta_l": round(float(delta[0]), 2),
        "primary_secondary_delta_a": round(float(delta[1]), 2),
        "primary_secondary_delta_b": round(float(delta[2]), 2),
        "primary_secondary_delta_e00": round(delta_e, 2),
    }


def _coherence_evidence(primary: dict | None, secondary: dict | None) -> dict:
    deltas = _anchor_deltas(primary, secondary)
    if not primary or not secondary:
        return {
            **deltas,
            "status": "insufficient",
            "reason": "anchor_missing",
            "large_delta": False,
            "chromatic_divergence": False,
            "contamination_evidence": [],
        }
    delta_l = abs(deltas["primary_secondary_delta_l"])
    delta_a = abs(deltas["primary_secondary_delta_a"])
    delta_b = abs(deltas["primary_secondary_delta_b"])
    delta_e = deltas["primary_secondary_delta_e00"]
    primary_c = float(np.hypot(primary["lab"]["a"], primary["lab"]["b"]))
    secondary_c = float(np.hypot(secondary["lab"]["a"], secondary["lab"]["b"]))
    delta_c = primary_c - secondary_c
    large_delta = (
        delta_e >= ANCHOR_COHERENCE_LARGE_DE00
        or delta_l >= ANCHOR_COHERENCE_LARGE_DELTA_L
    )
    chromatic_divergence = (
        delta_a >= ANCHOR_COHERENCE_LARGE_DELTA_A
        or delta_b >= ANCHOR_COHERENCE_LARGE_DELTA_B
        or delta_c >= ANCHOR_COHERENCE_LARGE_DELTA_C
    )
    contamination_evidence = list(primary.get("contamination_flags", []))
    physical_contamination = any(
        flag
        in {
            "hair_contamination",
            "lip_contamination",
            "highlight_hotspot",
            "high_local_edge_density",
            "high_chroma",
        }
        for flag in contamination_evidence
    )
    if not large_delta:
        status, reason = "coherent", "within_expected_range"
    elif chromatic_divergence and physical_contamination:
        status, reason = "contamination_suspected", "large_delta_with_contamination"
    else:
        status, reason = (
            "illumination_difference",
            "large_delta_explained_by_illumination",
        )
    return {
        **deltas,
        "primary_secondary_delta_c": round(delta_c, 2),
        "status": status,
        "reason": reason,
        "large_delta": bool(large_delta),
        "chromatic_divergence": bool(chromatic_divergence),
        "contamination_evidence": contamination_evidence,
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
    raw_candidate_count = (
        detection.raw_face_candidate_count
        if detection.raw_face_candidate_count is not None
        else len(detection.face_candidates) or len(detection.boxes)
    )
    valid_face_count = (
        detection.valid_face_count
        if detection.valid_face_count is not None
        else len(detection.boxes)
    )
    if detection.skin_output_decision is not None:
        skin_output_decision = detection.skin_output_decision
    elif valid_face_count == 1:
        skin_output_decision = "single_face_allowed"
    elif valid_face_count >= 2:
        skin_output_decision = "blocked_multiple_meaningful_faces"
    else:
        skin_output_decision = "insufficient_no_valid_face"
    detection_diagnostics = {
        "face_candidates": detection.face_candidates,
        "raw_face_candidates": detection.face_candidates,
        "valid_faces": detection.valid_faces
        or [
            {
                "candidate_id": f"face_candidate_{index}",
                "box": box,
                "score": 1.0,
            }
            for index, box in enumerate(detection.boxes, start=1)
        ],
        "raw_face_candidate_count": raw_candidate_count,
        "valid_face_count": valid_face_count,
        "primary_face_id": detection.primary_face_id,
        "primary_face_score": detection.primary_face_score,
        "candidate_scores": detection.candidate_scores,
        "candidate_rejections": detection.candidate_rejections,
        "multi_face_block_reason": detection.multi_face_block_reason,
        "skin_output_decision": skin_output_decision,
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
    if valid_face_count > 1:
        return finish(
            {
                "status": "多人不合并",
                "face_count": valid_face_count,
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
    cheek_orientation = float(geometry.get("cheek_orientation_degrees", orientation))
    forehead_orientation = float(
        geometry.get("forehead_orientation_degrees", orientation)
    )
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
            cheek_orientation,
        )
        sample = _cheek_candidate(
            rgb,
            lab,
            skin_mask,
            roi,
            side=side,
            center=[float(cx), float(cy)],
        )
        if sample:
            sample["selection_score"] = sample["candidate_score"]
            candidates.append(sample)

    primary = (
        max(candidates, key=lambda item: item["candidate_score"])
        if candidates
        else None
    )
    if primary:
        lightness = primary["lab"]["l"]
        if primary["candidate_score"] >= CHEEK_VALID_SCORE and 36 <= lightness <= 88:
            primary["status"], primary["status_code"] = "有效", "valid"
            primary_reason = "valid"
        elif primary["candidate_score"] >= CHEEK_LOW_CONFIDENCE_SCORE:
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
        forehead_orientation,
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

    initial_primary_side = primary.get("side") if primary else None
    coherence = _coherence_evidence(primary, secondary)
    reselected = False
    if primary and secondary and coherence["status"] == "contamination_suspected":
        alternatives = sorted(
            (candidate for candidate in candidates if candidate is not primary),
            key=lambda item: item["candidate_score"],
            reverse=True,
        )
        for alternative in alternatives:
            alternative_coherence = _coherence_evidence(alternative, secondary)
            current_delta = coherence["primary_secondary_delta_e00"]
            alternative_delta = alternative_coherence["primary_secondary_delta_e00"]
            if (
                alternative["candidate_score"] >= CHEEK_LOW_CONFIDENCE_SCORE
                and alternative_delta is not None
                and current_delta is not None
                and alternative_delta + 3.0 < current_delta
                and alternative_coherence["status"] != "contamination_suspected"
            ):
                primary = alternative
                coherence = alternative_coherence
                reselected = True
                break

    if primary:
        lightness = primary["lab"]["l"]
        if primary["candidate_score"] >= CHEEK_VALID_SCORE and 36 <= lightness <= 88:
            primary["status"], primary["status_code"] = "有效", "valid"
            primary_reason = "valid"
        elif primary["candidate_score"] >= CHEEK_LOW_CONFIDENCE_SCORE:
            primary["status"], primary["status_code"] = "仅供参考", "low_confidence"
            primary_reason = "high_variance"
        else:
            primary["status"], primary["status_code"] = "样本不足", "insufficient"
            primary_reason = "primary_roi_invalid"
        if coherence["status"] == "contamination_suspected":
            if primary["status_code"] == "valid":
                primary["status"], primary["status_code"] = (
                    "仅供参考",
                    "low_confidence",
                )
            primary["confidence"] = round(min(primary["confidence"], 0.69), 3)
            primary_reason = "cross_anchor_contamination"
        primary["crop"] = _crop_spec(
            primary["center"], anchor_face_width, rgb.shape, factor=0.24
        )

    coherence.update(
        {
            "reselected": reselected,
            "initial_primary_side": initial_primary_side,
            "final_primary_side": primary.get("side") if primary else None,
        }
    )

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
    detection_diagnostics["cheek_candidates"] = candidates
    detection_diagnostics.update(_anchor_deltas(primary, secondary))
    detection_diagnostics["anchor_coherence"] = coherence
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
