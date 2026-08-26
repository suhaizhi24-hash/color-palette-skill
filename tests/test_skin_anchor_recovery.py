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


def _two_face_scene():
    rgb = np.full((400, 400, 3), [70, 125, 75], dtype=np.uint8)
    yy, xx = np.mgrid[:400, :400]
    for center_x, center_y in ((95, 140), (295, 135)):
        face = ((xx - center_x) / 52.0) ** 2 + ((yy - center_y) / 68.0) ** 2 <= 1
        rgb[face] = [210, 164, 138]
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    return rgb, lab, np.ones((400, 400), dtype=bool)


def _single_subject_false_pattern_scene():
    rgb = np.full((600, 600, 3), [115, 165, 95], dtype=np.uint8)
    yy, xx = np.mgrid[:600, :600]
    face = ((xx - 300) / 70.0) ** 2 + ((yy - 245) / 88.0) ** 2 <= 1
    rgb[face] = [218, 174, 146]
    rgb[120:180, 225:375] = [42, 32, 28]
    # High-key blurred decoration: its pale color can resemble skin, but it has
    # neither face structure nor separation from its surroundings.
    rgb[320:540, 340:560] = [238, 226, 216]
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    return rgb, lab, np.ones((600, 600), dtype=bool)


def _anchor_quality_scene(
    *,
    left: tuple[int, int, int] = (210, 164, 138),
    right: tuple[int, int, int] = (210, 164, 138),
    forehead: tuple[int, int, int] = (210, 164, 138),
):
    """Synthetic face patches exercise anchor semantics, not photo Ground Truth."""

    rgb = np.full((400, 400, 3), [70, 125, 75], dtype=np.uint8)
    yy, xx = np.mgrid[:400, :400]
    face = ((xx - 200) / 90.0) ** 2 + ((yy - 190) / 120.0) ** 2 <= 1
    rgb[face] = [210, 164, 138]
    rgb[80:105, 110:290] = [35, 28, 25]
    cv2.ellipse(rgb, (166, 225), (25, 18), 0, 0, 360, left, -1)
    cv2.ellipse(rgb, (234, 225), (25, 18), 0, 0, 360, right, -1)
    cv2.ellipse(rgb, (200, 122), (28, 13), 0, 0, 360, forehead, -1)
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    detection = faces.FaceDetection(
        [[105, 75, 190, 235]], "fixture", "opencv", ["opencv"]
    )
    return faces.analyze_skin_anchors(
        rgb, lab, np.ones((400, 400), dtype=bool), detection
    )


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
        if self.mode == "false_patterns" and "frontalface_default" in self.path:
            return np.array(
                [[210, 150, 180, 180], [35, 65, 150, 150], [375, 350, 140, 140]],
                dtype=np.int32,
            )
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
    rgb, lab, mask = _two_face_scene()
    detection = faces.detect_faces(rgb, backend="opencv")
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)
    assert len(detection.boxes) == 2
    assert detection.recovery_used is False
    assert skin["status"] == "多人不合并"
    assert skin["diagnostics"]["failure_stage"] == "multiple_faces"
    assert skin["diagnostics"]["valid_face_count"] == 2
    assert skin["diagnostics"]["skin_output_decision"] == (
        "blocked_multiple_meaningful_faces"
    )


def test_single_subject_false_face_patterns_do_not_trigger_multi_face_block(
    monkeypatch,
):
    """Model ornate styling/high-key bokeh without committing a private photo."""

    _Cascade.mode = "false_patterns"
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", _Cascade)
    rgb, lab, mask = _single_subject_false_pattern_scene()
    detection = faces.detect_faces(rgb, backend="opencv")
    skin = faces.analyze_skin_anchors(rgb, lab, mask, detection)

    assert detection.raw_face_candidate_count == 3
    assert detection.valid_face_count == 1
    assert skin["status"] == "单人"
    assert skin["diagnostics"]["skin_output_decision"] == "single_face_allowed"
    assert skin["diagnostics"]["multi_face_block_reason"] is None
    reasons = {
        reason
        for rejected in skin["diagnostics"]["candidate_rejections"]
        for reason in rejected["reasons"]
    }
    assert "skin_pixel_share_low" in reasons
    assert "face_like_highlight_pattern" in reasons


def test_face_candidate_dedup_merges_iou_and_near_center_detections():
    records = [
        {
            "box": [100, 80, 180, 180],
            "detector_source": "opencv_frontal",
            "detector_confidence": 0.7,
        },
        {
            "box": [112, 92, 165, 165],
            "detector_source": "opencv_profile",
            "detector_confidence": 0.8,
        },
        {
            "box": [330, 90, 150, 150],
            "detector_source": "opencv_frontal",
            "detector_confidence": 0.75,
        },
    ]

    merged = faces._merge_face_candidate_records(records)

    assert len(merged) == 2
    assert merged[0]["duplicate_count"] == 2
    assert set(merged[0]["detector_sources"]) == {
        "opencv_frontal",
        "opencv_profile",
    }


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


def test_hard_light_face_keeps_real_cheek_difference_explainable():
    skin = _anchor_quality_scene(
        left=(150, 105, 85),
        right=(225, 180, 150),
        forehead=(220, 175, 145),
    )

    coherence = skin["diagnostics"]["anchor_coherence"]
    assert coherence["primary_secondary_delta_e00"] > 14
    assert coherence["status"] == "illumination_difference"
    assert skin["primary_anchor"]["status_code"] == "valid"


def test_cheek_shadow_contamination_does_not_win_primary_anchor():
    skin = _anchor_quality_scene(
        left=(210, 164, 138),
        right=(60, 45, 38),
        forehead=(215, 170, 145),
    )

    candidates = {
        item["side"]: item for item in skin["diagnostics"]["cheek_candidates"]
    }
    assert "shadow_span" in candidates["右侧"]["contamination_flags"]
    assert skin["primary_anchor"]["side"] == "左侧"


def test_warm_object_contamination_near_cheek_does_not_replace_stable_skin():
    skin = _anchor_quality_scene(
        left=(210, 164, 138),
        right=(215, 150, 65),
        forehead=(215, 170, 145),
    )

    assert skin["primary_anchor"]["side"] == "左侧"
    assert skin["primary_anchor"]["status_code"] == "valid"


def test_left_cheek_invalid_right_cheek_valid_uses_right_cheek():
    skin = _anchor_quality_scene(
        left=(40, 150, 60),
        right=(210, 164, 138),
        forehead=(215, 170, 145),
    )

    assert skin["primary_anchor"]["side"] == "右侧"
    assert skin["primary_anchor"]["status_code"] == "valid"


def test_large_primary_secondary_delta_can_be_valid_illumination_difference():
    skin = _anchor_quality_scene(
        left=(150, 115, 95),
        right=(160, 123, 102),
        forehead=(225, 190, 165),
    )

    coherence = skin["diagnostics"]["anchor_coherence"]
    assert coherence["primary_secondary_delta_e00"] > 14
    assert coherence["chromatic_divergence"] is False
    assert coherence["status"] == "illumination_difference"
    assert coherence["reason"] == "large_delta_explained_by_illumination"


def test_large_delta_with_warm_contamination_downgrades_primary_anchor():
    skin = _anchor_quality_scene(
        left=(40, 150, 60),
        right=(210, 120, 75),
        forehead=(215, 170, 145),
    )

    coherence = skin["diagnostics"]["anchor_coherence"]
    assert coherence["status"] == "contamination_suspected"
    assert "high_chroma" in coherence["contamination_evidence"]
    assert skin["primary_anchor"]["status_code"] == "low_confidence"
    assert skin["primary_anchor"]["confidence"] <= 0.69


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
