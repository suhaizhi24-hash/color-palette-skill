from __future__ import annotations

from pathlib import Path

REPORT_WIDTH = 1600
REPORT_HEIGHT = 1200
REPORT_RATIO = "4:3"
OFFICIAL_LANGUAGE = "zh-CN"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
OFFICIAL_MODULES = [
    "影调结构",
    "明暗关系",
    "色彩浓度",
    "白平衡&色相",
    "影调色卡",
    "肤色锚点",
    "素材特效&光线构成",
]

# Cross-platform CJK font candidates. Font files are never bundled in the
# repository; each operating system resolves its own legally installed font.
FONT_CANDIDATES_REGULAR = [
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/LanguageSupport/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/PingFang.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf"),
]
FONT_CANDIDATES_BOLD = [
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/LanguageSupport/PingFang.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/Library/Fonts/PingFang.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf"),
    Path("/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Bold.otf"),
]

FACE_BACKENDS = {"auto", "opencv", "dlib", "none"}
DEFAULT_FACE_BACKEND = "opencv"
