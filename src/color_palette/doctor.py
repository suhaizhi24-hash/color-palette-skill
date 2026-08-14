from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import cv2
import numpy as np
import PIL
from PIL import features
import skimage
import sklearn

from . import __version__
from .argparse_zh import ChineseArgumentParser
from .faces import available_face_backends
from .render import FontResolver


def collect_diagnostics() -> dict:
    checks: dict[str, dict] = {}

    # Image format and color-management capabilities supplied by Pillow.
    feature_names = ["jpg", "zlib", "webp", "littlecms2"]
    for name in feature_names:
        try:
            available = bool(features.check(name))
        except Exception:
            available = False
        checks[name] = {"available": available}

    try:
        font_meta = FontResolver().metadata()
        font_ok = True
        font_error = None
    except Exception as exc:
        font_meta = None
        font_ok = False
        font_error = str(exc)

    required_ok = all(checks[name]["available"] for name in ["jpg", "zlib", "webp", "littlecms2"])
    status = "通过" if required_ok and font_ok else "失败"
    return {
        "status": status,
        "tool_version": __version__,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "libraries": {
            "Pillow": PIL.__version__,
            "numpy": np.__version__,
            "opencv": cv2.__version__,
            "scikit-image": skimage.__version__,
            "scikit-learn": sklearn.__version__,
        },
        "pillow_features": checks,
        "face_backends": available_face_backends(),
        "face_backend_recommendation": (
            "核心默认使用OpenCV；多人或侧脸可选装dlib增强后端"
            if "dlib" not in available_face_backends()
            else "dlib增强后端可用；核心默认仍为OpenCV"
        ),
        "font": {
            "ok": font_ok,
            "metadata": font_meta,
            "error": font_error,
        },
        "zero_token": True,
        "official_output": ["analysis.json", "color_report.png"],
    }


def build_parser() -> ChineseArgumentParser:
    parser = ChineseArgumentParser(
        prog="color-palette-doctor",
        description="检查调色盘的本地格式、色彩管理、字体和人脸后端。",
    )
    parser.add_argument("--output", help="可选：保存诊断JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = collect_diagnostics()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
