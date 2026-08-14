from __future__ import annotations

from pathlib import Path
import sys

from .argparse_zh import ChineseArgumentParser
from .constants import DEFAULT_FACE_BACKEND, FACE_BACKENDS
from .ground_truth import (
    GroundTruthError,
    load_ground_truth,
    validate_dataset,
    write_validation_report,
)


def build_parser() -> ChineseArgumentParser:
    parser = ChineseArgumentParser(
        prog="color-palette-golden",
        description="用本地图片验证调色盘 Golden Dataset，不上传图片、不调用大模型。",
    )
    parser.add_argument("images", help="待验证的图片文件或目录")
    parser.add_argument("--ground-truth", required=True, help="Ground Truth JSON 路径")
    parser.add_argument(
        "--output",
        default="./golden_validation_report.json",
        help="验证报告 JSON 路径",
    )
    parser.add_argument(
        "--include-advisory",
        action="store_true",
        help="同时运行较慢、跨平台敏感的人脸/肤色建议字段验证",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=1600,
        help="回归分析最长边，默认1600",
    )
    parser.add_argument(
        "--face-backend",
        choices=sorted(FACE_BACKENDS),
        default=DEFAULT_FACE_BACKEND,
        help="建议字段的人脸后端；核心色彩字段不受影响",
    )
    parser.add_argument(
        "--strict-missing",
        action="store_true",
        help="Ground Truth 中有样本未提供时判定为失败",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ground_truth = load_ground_truth(args.ground_truth)
        report = validate_dataset(
            args.images,
            ground_truth,
            strict_missing=args.strict_missing,
            include_advisory=args.include_advisory,
            max_side=args.max_side,
            face_backend=args.face_backend,
        )
        output = write_validation_report(report, args.output)
    except GroundTruthError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"错误：Golden Dataset 验证失败：{exc}", file=sys.stderr)
        return 3

    summary = report["summary"]
    print(f"Golden Dataset 验证：{report['status']}")
    print(f"- 匹配样本：{summary['matched_sample_count']}/{summary['ground_truth_sample_count']}")
    print(f"- 必须字段失败：{summary['required_failure_count']}")
    print(f"- 建议字段验证：{'开启' if report['include_advisory'] else '关闭'}")
    print(f"- 人脸后端：{report.get('face_backend') or '默认'}")
    print(f"- 建议字段差异：{summary['advisory_mismatch_count']}")
    print(f"- 未知图片：{summary['unknown_image_count']}")
    print(f"- 缺少样本：{summary['missing_sample_count']}")
    print(f"- 报告：{output}")
    return 0 if report["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
