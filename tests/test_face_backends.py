import numpy as np

import color_palette.faces as faces


class EmptyCascade:
    def __init__(self, *args, **kwargs): pass
    def empty(self): return False
    def detectMultiScale(self, *args, **kwargs): return np.empty((0, 4), dtype=np.int32)


def test_none_backend_is_explicitly_disabled():
    rgb = np.zeros((300, 300, 3), dtype=np.uint8)
    result = faces.detect_faces(rgb, backend="none")
    assert result.detector == "disabled"
    assert result.requested_backend == "none"
    assert result.boxes == []


def test_explicit_dlib_missing_degrades_to_opencv(monkeypatch):
    monkeypatch.setattr(faces, "dlib", None)
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", EmptyCascade, raising=False)
    rgb = np.zeros((300, 300, 3), dtype=np.uint8)
    result = faces.detect_faces(rgb, backend="dlib")
    assert result.requested_backend == "dlib"
    assert result.degraded is True
    assert result.detector == "opencv"
    assert "降级" in result.note


def test_auto_without_dlib_selects_opencv(monkeypatch):
    monkeypatch.setattr(faces, "dlib", None)
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", EmptyCascade, raising=False)
    rgb = np.zeros((300, 300, 3), dtype=np.uint8)
    result = faces.detect_faces(rgb, backend="auto")
    assert result.requested_backend == "auto"
    assert result.detector == "opencv"
    assert result.degraded is False
    assert "选择OpenCV" in result.note


def test_default_backend_is_opencv(monkeypatch):
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", EmptyCascade, raising=False)
    rgb = np.zeros((300, 300, 3), dtype=np.uint8)
    result = faces.detect_faces(rgb)
    assert result.requested_backend == "opencv"
    assert result.detector == "opencv"


def test_explicit_opencv_does_not_call_dlib(monkeypatch):
    class ExplodingDlib:
        @staticmethod
        def get_frontal_face_detector():
            raise AssertionError("explicit opencv must not call dlib")

    monkeypatch.setattr(faces, "dlib", ExplodingDlib())
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", EmptyCascade, raising=False)
    rgb = np.zeros((300, 300, 3), dtype=np.uint8)
    result = faces.detect_faces(rgb, backend="opencv")
    assert result.requested_backend == "opencv"
    assert result.detector == "opencv"


def test_missing_opencv_face_component_does_not_abort(monkeypatch):
    monkeypatch.delattr(faces.cv2, "CascadeClassifier", raising=False)
    monkeypatch.setattr(faces, "dlib", None)
    rgb = np.zeros((300, 300, 3), dtype=np.uint8)
    detection = faces.detect_faces(rgb, backend="opencv")
    result = faces.analyze_skin_anchors(
        rgb,
        np.zeros((300, 300, 3), dtype=np.float32),
        np.ones((300, 300), dtype=bool),
        detection,
    )
    assert detection.detector == "unavailable"
    assert detection.degraded is True
    assert result["status"] == "未验证"
