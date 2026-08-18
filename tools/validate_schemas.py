#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from color_palette.argparse_zh import ChineseArgumentParser


VALIDATION_TARGETS = (
    (
        "schemas/analysis.schema.json",
        "examples/output_v014/synthetic_portrait_analysis.json",
    ),
    (
        "schemas/ground_truth.schema.json",
        "examples/golden_ground_truth.example.json",
    ),
    (
        "schemas/light_effect_ground_truth.schema.json",
        "examples/light_effect_ground_truth.example.json",
    ),
)


def validate(root: Path) -> dict:
    errors: list[str] = []
    checked: list[dict[str, str]] = []
    for schema_name, document_name in VALIDATION_TARGETS:
        schema_path = root / schema_name
        document_path = root / document_name
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            document = json.loads(document_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            document_errors = sorted(
                validator.iter_errors(document),
                key=lambda error: list(error.absolute_path),
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"读取失败：{schema_name} / {document_name}：{exc}")
            continue
        except Exception as exc:
            errors.append(f"约束文件无效：{schema_name}：{type(exc).__name__}")
            continue

        checked.append({"schema": schema_name, "document": document_name})
        for error in document_errors:
            location = "/".join(map(str, error.absolute_path)) or "<root>"
            errors.append(f"{document_name} 的 {location} 不符合约束")

    return {
        "status": "通过" if not errors else "失败",
        "checked_pair_count": len(checked),
        "checked": checked,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(description="校验项目JSON约束与公开示例。")
    parser.add_argument("root", nargs="?", default=".", help="项目根目录")
    parser.add_argument("--output", help="可选：保存校验结果JSON")
    args = parser.parse_args(argv)
    result = validate(Path(args.root).resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
