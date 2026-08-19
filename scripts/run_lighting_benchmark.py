#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from color_palette.analyzer import analyze
from color_palette.argparse_zh import ChineseArgumentParser
from color_palette.constants import SUPPORTED_EXTENSIONS


EXIT_PENDING = 2
ALLOWED_CODES = {
    "source": {"natural", "studio", "flash", "mixed", "self_luminous", "unknown"},
    "quality": {"hard", "soft", "not_applicable", "unknown"},
    "ratio": {"low", "medium", "high", "not_applicable", "unknown"},
}


def load_manifest(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "0.14.0":
        raise ValueError("Lighting Benchmark schema_version必须为0.14.0")
    anchors = document.get("anchors")
    if not isinstance(anchors, list) or [item.get("id") for item in anchors] != list("ABCDEF"):
        raise ValueError("Lighting Benchmark必须按A-F登记六个Anchor")
    for anchor in anchors:
        if anchor.get("status") != "pending_external_asset":
            raise ValueError(f"Anchor {anchor.get('id')} 缺少pending_external_asset状态")
        expected = anchor.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"Anchor {anchor.get('id')} 缺少expected")
        for dimension, allowed in ALLOWED_CODES.items():
            if expected.get(dimension) not in allowed:
                raise ValueError(f"Anchor {anchor.get('id')} 的{dimension}枚举无效")
        stem = anchor.get("match_stem")
        if stem != anchor["id"] or Path(stem).name != stem:
            raise ValueError(f"Anchor {anchor.get('id')} 的match_stem不安全")
    return document


def find_asset(input_dir: Path, stem: str) -> Path | None:
    candidates = [
        path
        for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.casefold() in SUPPORTED_EXTENSIONS
        and (
            path.stem.casefold() == stem.casefold()
            or path.stem.casefold().startswith(stem.casefold() + "_")
            or path.stem.casefold().startswith(stem.casefold() + "-")
        )
    ]
    if len(candidates) > 1:
        raise ValueError(f"Anchor {stem} 匹配到多张图片，请只保留一张")
    return candidates[0] if candidates else None


def run(manifest: dict, input_dir: Path) -> dict:
    results: list[dict] = []
    for anchor in manifest["anchors"]:
        asset = find_asset(input_dir, anchor["match_stem"])
        if asset is None:
            results.append(
                {
                    "id": anchor["id"],
                    "expected": anchor["expected"],
                    "actual": None,
                    "status": "pending_external_asset",
                }
            )
            continue
        sha256_before = _sha256(asset)
        analysis, _, _ = analyze(asset, face_backend="opencv")
        sha256_after = _sha256(asset)
        if sha256_after != sha256_before:
            raise RuntimeError(f"Anchor {anchor['id']} 的输入图片在分析过程中发生变化")
        if analysis.get("source", {}).get("sha256") != sha256_before:
            raise RuntimeError(f"Anchor {anchor['id']} 的分析来源哈希与本地输入不一致")
        lighting = analysis["lighting"]
        actual = {
            "source": lighting["source"]["code"],
            "quality": lighting["quality"]["code"],
            "ratio": lighting["ratio"]["code"],
        }
        status = "PASS" if actual == anchor["expected"] else "FAIL"
        item = {
            "id": anchor["id"],
            "sha256": sha256_before,
            "expected": anchor["expected"],
            "actual": actual,
            "status": status,
        }
        if status == "FAIL":
            classifiers = lighting.get("debug", {}).get("classifiers")
            if not isinstance(classifiers, dict):
                raise RuntimeError(f"Anchor {anchor['id']} 缺少分类器诊断信息")
            item["diagnostics"] = {
                "roi_type": lighting["subject_roi"]["type"],
                "source_classifier": classifiers["source"],
                "quality_classifier": classifiers["quality"],
                "ratio_classifier": classifiers["ratio"],
            }
        results.append(item)
    passed = sum(item["status"] == "PASS" for item in results)
    failed = sum(item["status"] == "FAIL" for item in results)
    pending = sum(item["status"] == "pending_external_asset" for item in results)
    return {
        "status": "PASS" if failed == 0 and pending == 0 else ("FAIL" if failed else "PENDING"),
        "passed": passed,
        "failed": failed,
        "pending": pending,
        "results": results,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_private_output(path: Path) -> None:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return
    raise ValueError("真实图片Benchmark结果必须保存在公开仓库之外")


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="使用仓库外的本地真实图片执行V0.14 Light Analysis A-F Benchmark。"
    )
    parser.add_argument(
        "--manifest",
        default="tests/lighting/lighting_benchmark.json",
        help="A-F Ground Truth登记文件",
    )
    parser.add_argument("--input-dir", help="包含A-F真实图片的本地目录")
    parser.add_argument("--manifest-only", action="store_true", help="只校验登记文件，不读取图片")
    parser.add_argument(
        "--output",
        help="可选：保存不含照片与路径的结果JSON；真实图片结果必须位于仓库外",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest).expanduser().resolve())
    if args.manifest_only:
        result = {"status": "PASS", "registered": 6, "real_assets_executed": 0}
        exit_code = 0
    else:
        if not args.input_dir:
            parser.error("执行真实图片Benchmark时必须提供--input-dir")
        input_dir = Path(args.input_dir).expanduser().resolve()
        if not input_dir.is_dir():
            raise ValueError(f"真实图片目录不存在：{input_dir}")
        result = run(manifest, input_dir)
        exit_code = 0 if result["status"] == "PASS" else (1 if result["status"] == "FAIL" else EXIT_PENDING)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        if not args.manifest_only:
            _validate_private_output(output)
        output.write_text(text + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
