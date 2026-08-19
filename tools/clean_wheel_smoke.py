#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from color_palette.argparse_zh import ChineseArgumentParser


VERIFY_CODE = r"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

import color_palette
import cv2
from jsonschema import Draft202012Validator
from PIL import Image

venv_root = Path(sys.argv[1]).resolve()
input_path = Path(sys.argv[2]).resolve()
output_dir = Path(sys.argv[3]).resolve()
schema_path = Path(sys.argv[4]).resolve()
result_path = Path(sys.argv[5]).resolve()
wheel_name = sys.argv[6]
wheel_sha256 = sys.argv[7]
doctor_path = Path(sys.argv[8]).resolve()

package_path = Path(color_palette.__file__).resolve()
assert package_path == venv_root or venv_root in package_path.parents, package_path
distribution = importlib.metadata.distribution("color-palette-skill")
assert distribution.version == "0.14.0"

entries = sorted(output_dir.iterdir())
assert len(entries) == 2 and all(path.is_file() for path in entries), entries
files = entries
assert sorted(path.suffix.casefold() for path in files) == [".json", ".png"], files
assert [path.name for path in files] == [
    f"{input_path.stem}_analysis.json",
    f"{input_path.stem}_color_report.png",
]
analysis_path = next(output_dir.glob("*_analysis.json"))
report_path = next(output_dir.glob("*_color_report.png"))
assert not list(output_dir.rglob("*.jpg"))
assert not list(output_dir.rglob("*.jpeg"))

analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
schema = json.loads(schema_path.read_text(encoding="utf-8"))
Draft202012Validator(schema).validate(analysis)
assert analysis["schema_version"] == "0.14.0"
assert analysis["official_language"] == "zh-CN"
assert analysis["zero_token"] is True
assert analysis["render_policy"]["generate_jpg"] is False
assert analysis["render_policy"]["render_color_adjustment"] is False
assert analysis["source"]["render_color_adjustment"] is False
assert analysis["material_effects"]["ruleset_version"] == "material-fx-0.13.0"
assert analysis["lighting"]["ruleset_version"] == "lighting-0.14.0"
assert analysis["lighting"]["source"]["code"] in {
    "natural", "studio", "flash", "mixed", "self_luminous", "unknown"
}
assert analysis["lighting"]["quality"]["code"] in {
    "hard", "soft", "not_applicable", "unknown"
}
assert analysis["lighting"]["ratio"]["code"] in {
    "low", "medium", "high", "not_applicable", "unknown"
}
visible_lighting = analysis["official_report"]["素材特效&光线构成"]["光线构成"]
assert set(visible_lighting) == {"光源", "光质", "光比"}
assert not any(
    marker in json.dumps(analysis["official_report"], ensure_ascii=False)
    for marker in ("confidence", "evidence", "subject_roi", "delta_ev")
)
assert analysis["source"]["sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
assert analysis["official_report"]["官方模块"] == [
    "影调结构",
    "明暗关系",
    "色彩浓度",
    "白平衡&色相",
    "影调色卡",
    "肤色锚点",
    "素材特效&光线构成",
]
assert int(cv2.__version__.split(".", 1)[0]) == 4

with Image.open(report_path) as report:
    report.load()
    assert report.format == "PNG"
    assert report.size == (1600, 1200)

requirements = list(distribution.requires or [])
banned = ("openai", "anthropic", "google-generativeai", "litellm")
assert not any(
    requirement.casefold().split(";", 1)[0].strip().startswith(banned)
    for requirement in requirements
)
doctor = json.loads(doctor_path.read_text(encoding="utf-8"))
assert doctor["status"] == "通过"
assert doctor["tool_version"] == "0.14.0"
assert doctor["zero_token"] is True

result = {
    "status": "通过",
    "wheel": wheel_name,
    "wheel_sha256": wheel_sha256,
    "installed_version": distribution.version,
    "opencv_version": cv2.__version__,
    "installed_package_path": str(package_path),
    "installed_from_clean_venv": True,
    "runtime_requirements": requirements,
    "paid_model_runtime_dependency": False,
    "cli_help": "通过",
    "doctor_status": doctor["status"],
    "doctor_font_status": doctor["font"]["status"],
    "output_files": [path.name for path in files],
    "report_format": "PNG",
    "report_size": [1600, 1200],
    "jpg_jpeg_count": 0,
    "json_schema": "通过",
    "input_unchanged": True,
    "render_color_adjustment": False,
    "lighting_ruleset": analysis["lighting"]["ruleset_version"],
    "lighting": visible_lighting,
}
result_path.parent.mkdir(parents=True, exist_ok=True)
result_path.write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(result, ensure_ascii=False, indent=2))
"""


def _wheel(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_file() and path.suffix == ".whl":
        return path
    wheels = sorted(path.glob("*.whl")) if path.is_dir() else []
    if len(wheels) != 1:
        raise RuntimeError(f"需要且只能找到一个Wheel，实际为{len(wheels)}个：{path}")
    return wheels[0]


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(description="在干净虚拟环境安装Wheel并执行PNG+JSON回归。")
    parser.add_argument("wheel", help="Wheel文件或只包含一个Wheel的目录")
    parser.add_argument("--input", required=True, help="公开合成输入图片")
    parser.add_argument("--schema", required=True, help="analysis JSON Schema")
    parser.add_argument("--output", required=True, help="必须尚不存在的烟雾测试输出目录")
    parser.add_argument("--result", required=True, help="保存机器可读验证结果")
    args = parser.parse_args(argv)

    wheel = _wheel(Path(args.wheel))
    input_path = Path(args.input).expanduser().resolve()
    schema_path = Path(args.schema).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    result_path = Path(args.result).expanduser().resolve()
    if not input_path.is_file() or not schema_path.is_file():
        raise RuntimeError("公开输入图片或Schema不存在")
    if output_dir.exists():
        raise RuntimeError(f"为避免掩盖旧产物，输出目录必须尚不存在：{output_dir}")
    if result_path.exists():
        raise RuntimeError(f"为避免掩盖旧证据，结果文件必须尚不存在：{result_path}")

    input_before = hashlib.sha256(input_path.read_bytes()).hexdigest()
    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="color-palette-wheel-") as temporary:
        temporary_root = Path(temporary)
        venv_root = temporary_root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_root)
        python = (
            venv_root / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else venv_root / "bin" / "python"
        )
        cli = (
            venv_root / "Scripts" / "color-palette.exe"
            if sys.platform == "win32"
            else venv_root / "bin" / "color-palette"
        )
        doctor_cli = (
            venv_root / "Scripts" / "color-palette-doctor.exe"
            if sys.platform == "win32"
            else venv_root / "bin" / "color-palette-doctor"
        )
        doctor_path = temporary_root / "doctor.json"
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
                "jsonschema>=4.21",
            ],
            cwd=temporary_root,
        )
        _run([str(python), "-m", "pip", "check"], cwd=temporary_root)
        _run([str(cli), "--help"], cwd=temporary_root)
        _run([str(doctor_cli), "--output", str(doctor_path)], cwd=temporary_root)
        _run(
            [
                str(cli),
                str(input_path),
                "--output",
                str(output_dir),
                "--face-backend",
                "none",
            ],
            cwd=temporary_root,
        )
        if hashlib.sha256(input_path.read_bytes()).hexdigest() != input_before:
            raise RuntimeError("CLI修改了输入图片")
        _run(
            [
                str(python),
                "-c",
                VERIFY_CODE,
                str(venv_root),
                str(input_path),
                str(output_dir),
                str(schema_path),
                str(result_path),
                wheel.name,
                wheel_digest,
                str(doctor_path),
            ],
            cwd=temporary_root,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
