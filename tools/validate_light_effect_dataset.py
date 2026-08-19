#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from jsonschema import Draft202012Validator
from color_palette.argparse_zh import ChineseArgumentParser
from color_palette.io import load_image
from color_palette.material_fx import analyze_material_fx


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path, dataset_path: Path, schema_path: Path) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(dataset), key=lambda e: list(e.path))
    issues = [
        f"{'/'.join(map(str, error.absolute_path)) or '<root>'}：不符合JSON约束"
        for error in errors
    ]
    checked = 0
    material_fx_checked = 0
    for sample in dataset.get("samples", []):
        image_path = root / sample["file"]
        checked += 1
        if not image_path.exists():
            issues.append(f"样本不存在：{sample['file']}")
        elif sha256(image_path) != sample["sha256"]:
            issues.append(f"样本哈希不一致：{sample['file']}")
        else:
            loaded = load_image(image_path)
            rgb = np.asarray(loaded.rgb_image, dtype=np.uint8)
            result = analyze_material_fx(rgb, loaded.valid_mask)
            actual = [item["display_name"] for item in result["items"]]
            expected = sample["expected"]["素材特效"]
            material_fx_checked += 1
            if actual != expected:
                issues.append(
                    f"Material FX不一致：{sample['file']}；"
                    f"期望={expected}；实际={actual}"
                )
    return {
        "status": "通过" if not issues else "失败",
        "checked_sample_count": checked,
        "material_fx_checked_sample_count": material_fx_checked,
        "issues": issues,
        "note": "公开合成样例继续执行Material FX算法回归；V0.14 Light规则由tests/lighting独立验证，真实A-F图片在仓库外验收。",
    }


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(description="验证光线与素材特效公开Golden Dataset。")
    parser.add_argument("--root", default=".")
    parser.add_argument("--dataset", default="examples/light_effect_ground_truth.example.json")
    parser.add_argument("--schema", default="schemas/light_effect_ground_truth.schema.json")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = validate(root, root / args.dataset, root / args.schema)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
