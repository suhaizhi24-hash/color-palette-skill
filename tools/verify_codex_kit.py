#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import venv
import zipfile

from jsonschema import Draft202012Validator
from PIL import Image

from color_palette.argparse_zh import ChineseArgumentParser

try:
    from tools.audit_wheel import SECRET_PATTERNS, audit_wheel
    from tools.build_codex_kit import (
        EXPECTED_MEMBERS,
        KIT_NAME,
        KIT_ROOT_NAME,
        KIT_VERSION,
        WHEEL_NAME,
    )
except ModuleNotFoundError:  # 允许以 python tools/verify_codex_kit.py 直接运行。
    from audit_wheel import SECRET_PATTERNS, audit_wheel
    from build_codex_kit import (
        EXPECTED_MEMBERS,
        KIT_NAME,
        KIT_ROOT_NAME,
        KIT_VERSION,
        WHEEL_NAME,
    )


PATH_CASES = ("english-path", "中文路径", "path with spaces")


class KitVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def inspect_codex_kit(kit: str | Path) -> dict:
    kit_path = Path(kit).expanduser().resolve()
    if not kit_path.is_file() or kit_path.name != KIT_NAME:
        raise KitVerificationError(f"Codex Kit不存在或文件名不正确：{kit_path}")
    with zipfile.ZipFile(kit_path) as archive:
        infos = archive.infolist()
        names = tuple(info.filename for info in infos)
        if names != EXPECTED_MEMBERS:
            raise KitVerificationError(f"Codex Kit必须且只能包含固定条目：{names}")
        folded: set[str] = set()
        contents: dict[str, bytes] = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise KitVerificationError(f"Codex Kit包含不安全路径：{info.filename}")
            if info.filename.casefold() in folded:
                raise KitVerificationError(f"Codex Kit包含大小写碰撞：{info.filename}")
            folded.add(info.filename.casefold())
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if info.create_system == 3 and stat.S_ISLNK(unix_mode):
                raise KitVerificationError(f"Codex Kit包含符号链接：{info.filename}")
            if info.flag_bits & 0x1:
                raise KitVerificationError(f"Codex Kit包含加密条目：{info.filename}")
            data = archive.read(info)
            contents[info.filename] = data
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(data):
                    raise KitVerificationError(f"Codex Kit检测到{label}：{info.filename}")
        if archive.testzip() is not None:
            raise KitVerificationError("Codex Kit CRC校验失败")
    return {
        "kit": str(kit_path),
        "kit_sha256": _sha256(kit_path),
        "members": list(contents),
        "contents": contents,
    }


def _verify_output(
    output_dir: Path,
    input_path: Path,
    schema: dict,
) -> dict:
    entries = sorted(output_dir.iterdir())
    if len(entries) != 2 or not all(path.is_file() for path in entries):
        raise KitVerificationError(f"输出目录必须恰好包含两个文件：{entries}")
    expected_names = [
        "synthetic_sample_analysis.json",
        "synthetic_sample_color_report.png",
    ]
    if [path.name for path in entries] != expected_names:
        raise KitVerificationError(f"输出文件名不正确：{entries}")
    if list(output_dir.rglob("*.jpg")) or list(output_dir.rglob("*.jpeg")):
        raise KitVerificationError("Codex Kit烟雾测试生成了JPG/JPEG正式输出")

    analysis = json.loads(entries[0].read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(analysis)
    if analysis["zero_token"] is not True:
        raise KitVerificationError("分析结果不是Zero-token")
    if analysis["render_policy"]["generate_jpg"] is not False:
        raise KitVerificationError("分析结果允许生成JPG")
    if analysis["render_policy"]["render_color_adjustment"] is not False:
        raise KitVerificationError("分析结果修改了渲染色彩")
    if analysis["source"]["sha256"] != _sha256(input_path):
        raise KitVerificationError("analysis.json中的输入哈希不匹配")
    with Image.open(entries[1]) as report:
        report.load()
        if report.format != "PNG" or report.size != (1600, 1200):
            raise KitVerificationError(f"正式报告格式或尺寸错误：{report.format} {report.size}")
    return {
        "output_files": expected_names,
        "png_size": [1600, 1200],
        "jpg_jpeg_count": 0,
        "schema": "通过",
        "input_unchanged": True,
        "render_color_adjustment": False,
        "zero_token": True,
    }


def verify_codex_kit(kit: str | Path, schema_path: str | Path) -> dict:
    inspected = inspect_codex_kit(kit)
    schema_file = Path(schema_path).expanduser().resolve()
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="color-palette-codex-kit-") as temporary:
        temporary_root = Path(temporary)
        extracted_root = temporary_root / "extracted"
        extracted_root.mkdir()
        with zipfile.ZipFile(inspected["kit"]) as archive:
            archive.extractall(extracted_root)
        kit_root = extracted_root / KIT_ROOT_NAME
        wheel = kit_root / WHEEL_NAME
        sample = kit_root / "sample" / "synthetic_sample.png"
        wheel_result = audit_wheel(wheel, expected_version=KIT_VERSION)
        if wheel_result.get("status") != "通过":
            raise KitVerificationError("体验包内Wheel审计失败：" + "；".join(wheel_result["errors"]))

        venv_root = temporary_root / "clean-venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_root)
        scripts = venv_root / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        cli = scripts / ("color-palette.exe" if sys.platform == "win32" else "color-palette")
        doctor = scripts / (
            "color-palette-doctor.exe" if sys.platform == "win32" else "color-palette-doctor"
        )
        doctor_result = temporary_root / "doctor.json"
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
        _run([str(doctor), "--output", str(doctor_result)], cwd=temporary_root)
        doctor_data = json.loads(doctor_result.read_text(encoding="utf-8"))
        if doctor_data["status"] != "通过" or doctor_data["tool_version"] != KIT_VERSION:
            raise KitVerificationError(f"体验包doctor失败：{doctor_data}")

        path_results: dict[str, dict] = {}
        original_sample_hash = _sha256(sample)
        for case in PATH_CASES:
            case_root = temporary_root / case
            case_root.mkdir()
            case_sample = case_root / "synthetic_sample.png"
            shutil.copyfile(sample, case_sample)
            before = _sha256(case_sample)
            output_dir = case_root / "result"
            _run(
                [
                    str(cli),
                    str(case_sample),
                    "--output",
                    str(output_dir),
                    "--face-backend",
                    "none",
                ],
                cwd=case_root,
            )
            after = _sha256(case_sample)
            if before != original_sample_hash or after != before:
                raise KitVerificationError(f"路径测试修改了输入图片：{case}")
            path_results[case] = _verify_output(output_dir, case_sample, schema)

    return {
        "status": "通过",
        "version": KIT_VERSION,
        "kit": Path(inspected["kit"]).name,
        "kit_sha256": inspected["kit_sha256"],
        "wheel": WHEEL_NAME,
        "wheel_audit": "通过",
        "clean_virtualenv_install": True,
        "pip_check": "通过",
        "doctor": "通过",
        "path_tests": path_results,
        "private_assets": False,
        "font_files": False,
        "secret_or_token_findings": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(description="解压并在干净环境验证Codex快速体验包。")
    parser.add_argument("kit", help=f"待验证的{KIT_NAME}")
    parser.add_argument("--schema", required=True, help="analysis JSON Schema")
    parser.add_argument("--result", help="可选：保存JSON验证证据")
    args = parser.parse_args(argv)
    try:
        result = verify_codex_kit(args.kit, args.schema)
    except (
        KitVerificationError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
    ) as exc:
        result = {"status": "失败", "errors": [str(exc)]}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.result:
        result_path = Path(args.result).expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
