from __future__ import annotations

import sys

from . import __version__
from .argparse_zh import ChineseArgumentParser
from .constants import DEFAULT_FACE_BACKEND, FACE_BACKENDS
from .errors import ColorPaletteError
from .pipeline import run


def build_parser() -> ChineseArgumentParser:
    parser = ChineseArgumentParser(
        prog="color-palette",
        description="本地、零Token的中文照片色彩分析报告工具。",
    )
    parser.add_argument("image", help="输入图片：JPG / PNG / WebP")
    parser.add_argument("-o", "--output", default="./output", help="输出目录")
    parser.add_argument(
        "--face-backend",
        choices=sorted(FACE_BACKENDS),
        default=DEFAULT_FACE_BACKEND,
        help=(
            "肤色/人脸后端：opencv为跨平台默认；auto优先dlib；"
            "dlib不可用时安全降级；none关闭肤色分析"
        ),
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=1600,
        help="分析副本最长边，默认1600；不改变原图显示色彩",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="显示版本号并退出",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        outputs = run(
            args.image,
            args.output,
            face_backend=args.face_backend,
            max_side=args.max_side,
        )
    except ColorPaletteError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"错误：分析或渲染失败：{exc}", file=sys.stderr)
        return 3

    print("分析完成：")
    print(f"- JSON：{outputs['analysis_json']}")
    print(f"- PNG：{outputs['color_report_png']}")
    print("- JPG：未生成（官方协议仅输出 PNG）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
