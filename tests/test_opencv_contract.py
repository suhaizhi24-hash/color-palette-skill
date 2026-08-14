from pathlib import Path
import re

import cv2


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_is_supported_opencv_4_x():
    major = int(cv2.__version__.split(".", 1)[0])
    assert major == 4, f"V0.12.0仅支持OpenCV 4.x，当前为{cv2.__version__}"
    assert callable(cv2.cvtColor)
    assert callable(cv2.CascadeClassifier)
    assert Path(cv2.data.haarcascades).is_dir()


def test_dependency_range_excludes_opencv_5_x():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'"opencv-python-headless([^\"]+)"', text)
    assert match is not None
    assert ">=4.9" in match.group(1)
    assert "<5" in match.group(1)
