import numpy as np

import color_palette.faces as faces


class FakeRect:
    def __init__(self, x, y, w, h):
        self._x, self._y, self._w, self._h = x, y, w, h

    def left(self): return self._x
    def top(self): return self._y
    def width(self): return self._w
    def height(self): return self._h


class FakeDetector:
    def __call__(self, rgb, upsample):
        if upsample == 1:
            return [FakeRect(80, 120, 150, 150)]
        return [
            FakeRect(80, 120, 150, 150),
            FakeRect(350, 90, 140, 140),
        ]


class FakeDlib:
    @staticmethod
    def get_frontal_face_detector():
        return FakeDetector()


def test_dlib_second_pass_recovers_second_face(monkeypatch):
    monkeypatch.setattr(faces, "dlib", FakeDlib())
    # Prevent OpenCV from contributing detections in this unit test.
    class EmptyCascade:
        def __init__(self, *args, **kwargs): pass
        def empty(self): return False
        def detectMultiScale(self, *args, **kwargs): return np.empty((0, 4), dtype=np.int32)
    monkeypatch.setattr(faces.cv2, "CascadeClassifier", EmptyCascade, raising=False)
    rgb = np.zeros((600, 600, 3), dtype=np.uint8)
    result = faces.detect_faces(rgb, backend="dlib")
    assert len(result.boxes) == 2
    assert result.detector == "dlib"
