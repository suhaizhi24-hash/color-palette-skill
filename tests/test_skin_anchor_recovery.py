from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from skimage.color import rgb2lab

from color_palette import faces

ROOT = Path(__file__).resolve().parents[1]
LEGACY_RENDERER_SHA256 = (
    "59782eff55932fbf7e2cb660bbe95c3606c252372aace5e8ec45bf6883b25f09"
)


def _skin_scene(*, bright: bool = False, dark_forehead: bool = False):
    rgb = np.full((400, 400, 3), [70, 125, 75], dtype=np.uint8)
    yy, xx = np.mgrid[:400, :400]
    face = ((xx - 200) / 90.0) ** 2 + ((yy - 190) / 120.0) ** 2 <= 1
    rgb[face] = [238, 203, 180] if bright else [210, 164, 138]
    rgb[80:145, 105:295] = [35, 28, 25]
    if dark_forehead:
        rgb[120:180, 145:255] = [45, 35, 32]
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    return rgb, lab, np.ones((400, 400), dtype=bool)


class _Cascade:
    mode = "empty"
    instances = 0

    def __init__(self, path):
        self.path = path
        self.instance = type(self).instances
        type(self).instances += 1
        self.calls = 0

    def empty(self):
        return False

    def detectMultiScale(self, *args, **kwargs):
        self.calls += 1
        if self.mode == "baseline" and "frontalface_default" in self.path:
            return np.array([[110, 80, 180, 180]], dtype=np.int32)
        if self.mode == "side" and "profileface" in self.path:
            return np.array([[115, 85, 170, 170]], dtype=np.int32)
        # Two baseline cascade instances are constructed before the dedicated
        # recovery cascade. Return a face only on its first rotated call.
        if self.mode == "recovery" and self.instance >= 2 and self.calls == 1:
            return np.array([[110, 80, 180, 180]], dtype=np.int32)
        if self.mode == "multiple" and "frontalface_default" in self.path:
            return np.array([[35, 80, 120, 120], [235, 75, 120, 120]], dtype=np.int32)
        return np.empty((0, 4), dtype=np.int32)


@pytest.fixture(autouse=True)
def _reset_cascade():
    _Cascade.instances = 0
    _Cascade.mode = "empty"


def test_normal_front_face_uses_baseline_only(monkeypatch):
    _Cascade.mode = "baseline"
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb, _, _ = _skin_scene()
    result = faces.detect_faces(rgb, backend="opencv")
    assert len(result.boxes) == 1
    assert result.recovery_used is False
    assert result.baseline_count == 1


def test_profile_face_baseline_does_not_force_recovery(monkeypatch):
    _Cascade.mode = "side"
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb, _, _ = _skin_scene()
    result = faces.detect_faces(rgb, backend="opencv")
    assert len(result.boxes) == 1
    assert result.recovery_used is False


def test_soft_focus_low_contrast_face_uses_recovery_only_after_zero_baseline(
    monkeypatch,
):
    _Cascade.mode = "recovery"
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb, lab, mask = _skin_scene()
    result = faces.detect_faces(rgb, backend="opencv")
    skin = faces.analyze_skin_anchors(rgb, lab, mask, result)
    assert result.baseline_count == 0
    assert result.recovery_used is True
    assert len(result.boxes) == 1
    assert skin["status"] == "单人"
    assert skin["primary_anchor"]["status_code"] == "valid"
    assert skin["diagnostics"]["recovery_used"] is True
    assert skin["diagnostics"]["failure_stage"] == "valid"


@pytest.mark.parametrize("angle", [-15, -8, 8, 15])
def test_rotated_bbox_inverse_transform_stays_inside_image(angle):
    shape = (300, 500)
    matrix = cv2.getRotationMatrix2D((250.0, 150.0), angle, 1.0)
    box = faces._inverse_rotated_box([90, 60, 180, 160], matrix, shape)
    x, y, width, height = box
    assert x >= 0 and y >= 0
    assert width > 0 and height > 0
    assert x + width <= shape[1]
    assert y + height <= shape[0]


def test_high_key_face_can_keep_primary_anchor_valid():
    rgb, lab, mask = _skin_scene(bright=True)
    detection = faces.FaceDetection(
        [[105, 75, 190, 235]], "fixture", "opencv", ["opencv"]
    )
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)
    assert skin["primary_anchor"]["status_code"] in {"valid", "low_confidence"}
    assert skin["primary_anchor"]["lab"]["l"] > 70


def test_backlit_forehead_failure_does_not_invalidate_primary_cheek():
    rgb, lab, mask = _skin_scene(dark_forehead=True)
    detection = faces.FaceDetection(
        [[105, 75, 190, 235]], "fixture", "opencv", ["opencv"]
    )
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)
    assert skin["primary_anchor"]["status_code"] == "valid"
    assert skin["status"] == "单人"
    if skin["secondary_anchor"] is not None:
        assert skin["secondary_anchor"]["status_code"] in {
            "valid",
            "low_confidence",
            "insufficient",
        }


def test_primary_anchor_remains_valid_when_forehead_is_insufficient():
    rgb, lab, mask = _skin_scene()
    rgb[105:155, 160:240] = [35, 130, 45]
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    detection = faces.FaceDetection(
        [[105, 75, 190, 235]], "fixture", "opencv", ["opencv"]
    )
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)
    assert skin["primary_anchor"]["status_code"] == "valid"
    assert skin["status"] == "单人"
    assert skin["secondary_anchor"] is None or skin["secondary_anchor"][
        "status_code"
    ] in {"low_confidence", "insufficient"}


def test_multiple_faces_remain_unmerged_and_skip_recovery(monkeypatch):
    _Cascade.mode = "multiple"
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb, lab, mask = _skin_scene()
    detection = faces.detect_faces(rgb, backend="opencv")
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)
    assert len(detection.boxes) == 2
    assert detection.recovery_used is False
    assert skin["status"] == "多人不合并"
    assert skin["diagnostics"]["failure_stage"] == "multiple_faces"


def test_no_face_scene_fails_closed_without_skin_pixels(monkeypatch):
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb = np.full((300, 300, 3), [20, 145, 35], dtype=np.uint8)
    result = faces.detect_faces(rgb, backend="opencv")
    assert result.boxes == []
    assert result.recovery_used is True
    assert result.failure_reason == "no_face_candidate"


def test_false_positive_non_skin_candidate_is_rejected():
    rgb = np.full((300, 300, 3), [25, 130, 45], dtype=np.uint8)
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    skin = faces._base_skin_mask(rgb, lab, np.ones((300, 300), dtype=bool))
    candidate = faces._validate_recovery_candidate(
        [60, 50, 170, 170], skin_mask=skin, lab=lab, image_shape=(300, 300)
    )
    assert candidate["accepted"] is False
    assert candidate["reason"] == "skin_pixel_share_low"


def test_comparable_recovery_candidates_fail_closed_as_ambiguous():
    chosen, reason = faces._select_recovery_cluster(
        [
            {"box": [20, 30, 120, 120], "area": 14_400, "rank_score": 0.91},
            {"box": [240, 35, 115, 115], "area": 13_225, "rank_score": 0.86},
        ]
    )
    assert chosen is None
    assert reason == "ambiguous_multiple_faces"


def test_ambiguous_recovery_reports_multiple_faces_stage(monkeypatch):
    monkeypatch.setattr(
        faces,
        "_recover_opencv_faces",
        lambda _rgb: ([], [], "ambiguous_multiple_faces", None),
    )
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb, lab, mask = _skin_scene()
    detection = faces.detect_faces(rgb, backend="opencv")
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)
    assert detection.failure_stage == "multiple_faces"
    assert skin["diagnostics"]["failure_stage"] == "multiple_faces"
    assert skin["diagnostics"]["failure_reason"] == "ambiguous_multiple_faces"


def test_anchor_diagnostics_report_required_performance_fields():
    rgb, lab, mask = _skin_scene()
    detection = faces.FaceDetection(
        [[105, 75, 190, 235]],
        "fixture",
        "opencv",
        ["opencv"],
        face_detection_ms=1.25,
        recovery_detection_ms=0.0,
    )
    diagnostics = faces.analyze_skin_anchors(rgb, lab, mask, detection)["diagnostics"]
    assert set(diagnostics["performance"]) == {
        "face_detection_ms",
        "recovery_detection_ms",
        "skin_anchor_ms",
    }


def test_recovery_geometry_maps_anchor_points_inside_image():
    shape = (300, 500)
    matrix = cv2.getRotationMatrix2D((250.0, 150.0), -15, 1.0)
    geometry = faces._recovery_anchor_geometry([90, 60, 180, 160], matrix, shape, -15)
    points = geometry["cheek_centers"] + [geometry["forehead_center"]]
    assert all(0 <= x < shape[1] and 0 <= y < shape[0] for x, y in points)
    assert geometry["orientation_degrees"] == 15.0


def test_legacy_renderer_source_text_is_unchanged_across_line_endings():
    source = (ROOT / "src/color_palette/render.py").read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert digest == LEGACY_RENDERER_SHA256
