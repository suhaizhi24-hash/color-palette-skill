#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import zipfile

from color_palette.argparse_zh import ChineseArgumentParser

try:
    from tools.audit_wheel import SECRET_PATTERNS, audit_wheel, resolve_wheel
except ModuleNotFoundError:  # 允许以 python tools/build_codex_kit.py 直接运行。
    from audit_wheel import SECRET_PATTERNS, audit_wheel, resolve_wheel


ROOT = Path(__file__).resolve().parents[1]
KIT_VERSION = "0.15.0"
KIT_ROOT_NAME = f"color-palette-codex-kit-v{KIT_VERSION}"
WHEEL_NAME = f"color_palette_skill-{KIT_VERSION}-py3-none-any.whl"
KIT_NAME = f"color-palette-codex-kit-v{KIT_VERSION}.zip"
SAMPLE_RELATIVE_PATH = "examples/synthetic_portrait.png"
EXPECTED_MEMBERS = (
    f"{KIT_ROOT_NAME}/START_HERE.md",
    f"{KIT_ROOT_NAME}/CODEX_PROMPT.txt",
    f"{KIT_ROOT_NAME}/{WHEEL_NAME}",
    f"{KIT_ROOT_NAME}/sample/synthetic_sample.png",
)
ZIP_TIMESTAMP = (2024, 1, 1, 0, 0, 0)


class KitBuildError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KitBuildError(f"无法读取公开样例登记：{path}：{exc}") from exc


def _registered_file(document: dict, relative_path: str) -> dict:
    matches = [item for item in document.get("files", []) if item.get("path") == relative_path]
    if len(matches) != 1:
        raise KitBuildError(f"公开样例必须在登记中唯一出现：{relative_path}")
    return matches[0]


def _reviewed_sample(root: Path) -> bytes:
    sample_path = root / SAMPLE_RELATIVE_PATH
    try:
        sample = sample_path.read_bytes()
    except OSError as exc:
        raise KitBuildError(f"公开合成样片不存在：{sample_path}") from exc

    digest = _sha256(sample)
    provenance = _load_json(root / "examples/public_examples_provenance.json")
    manifest = _load_json(root / "examples/public_examples_manifest.json")
    provenance_item = _registered_file(provenance, SAMPLE_RELATIVE_PATH)
    manifest_item = _registered_file(manifest, SAMPLE_RELATIVE_PATH)
    if provenance.get("privacy") != "公开" or manifest.get("privacy") != "公开":
        raise KitBuildError("公开样例登记没有明确标记为公开")
    if provenance_item.get("reviewed") is not True:
        raise KitBuildError("Codex Kit 样片尚未经过独立人工来源审核")
    if provenance_item.get("generated") is not True or manifest_item.get("generated") is not True:
        raise KitBuildError("Codex Kit 只允许使用程序生成的公开样片")
    if provenance_item.get("license") != "CC0-1.0" or manifest_item.get("license") != "CC0-1.0":
        raise KitBuildError("Codex Kit 样片必须登记为 CC0-1.0")
    if provenance_item.get("sha256") != digest or manifest_item.get("sha256") != digest:
        raise KitBuildError("Codex Kit 样片哈希与独立来源登记不一致")
    return sample


def _text_bytes(path: Path) -> bytes:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise KitBuildError(f"无法读取体验文档：{path}：{exc}") from exc
    if not text.strip():
        raise KitBuildError(f"体验文档为空：{path}")
    return text.replace("\r\n", "\n").encode("utf-8")


def _check_member_secrets(members: dict[str, bytes]) -> None:
    for name, data in members.items():
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(data):
                raise KitBuildError(f"Codex Kit 条目检测到{label}：{name}")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def build_codex_kit(
    wheel_candidate: str | Path,
    output: str | Path,
    *,
    root: Path = ROOT,
) -> dict:
    wheel = resolve_wheel(wheel_candidate).resolve()
    if wheel.name != WHEEL_NAME:
        raise KitBuildError(f"Wheel文件名不正确：期望{WHEEL_NAME}，实际{wheel.name}")
    wheel_result = audit_wheel(wheel, expected_version=KIT_VERSION)
    if wheel_result.get("status") != "通过":
        raise KitBuildError("Wheel审计失败：" + "；".join(wheel_result.get("errors", [])))

    members = {
        EXPECTED_MEMBERS[0]: _text_bytes(root / "START_HERE.md"),
        EXPECTED_MEMBERS[1]: _text_bytes(root / "CODEX_PROMPT.txt"),
        EXPECTED_MEMBERS[2]: wheel.read_bytes(),
        EXPECTED_MEMBERS[3]: _reviewed_sample(root),
    }
    _check_member_secrets(members)

    output_path = Path(output).expanduser().resolve()
    if output_path.name != KIT_NAME:
        raise KitBuildError(f"Kit文件名不正确：期望{KIT_NAME}，实际{output_path.name}")
    if output_path.exists():
        raise KitBuildError(f"为避免覆盖旧体验包，输出文件必须尚不存在：{output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w") as archive:
        for name in EXPECTED_MEMBERS:
            archive.writestr(_zip_info(name), members[name])

    with zipfile.ZipFile(output_path) as archive:
        names = tuple(info.filename for info in archive.infolist())
        if names != EXPECTED_MEMBERS:
            raise KitBuildError(f"Codex Kit结构不正确：{names}")
        if archive.testzip() is not None:
            raise KitBuildError("Codex Kit CRC校验失败")

    result = {
        "status": "通过",
        "version": KIT_VERSION,
        "kit": str(output_path),
        "kit_sha256": _sha256(output_path.read_bytes()),
        "kit_size": output_path.stat().st_size,
        "wheel": wheel.name,
        "wheel_sha256": _sha256(members[EXPECTED_MEMBERS[2]]),
        "sample_source": SAMPLE_RELATIVE_PATH,
        "sample_sha256": _sha256(members[EXPECTED_MEMBERS[3]]),
        "members": list(EXPECTED_MEMBERS),
        "private_assets": False,
        "font_files": False,
        "secret_or_token_findings": 0,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(description="构建固定结构、可审计的Codex快速体验包。")
    parser.add_argument("wheel", help="0.15.0 Wheel文件，或只包含该Wheel的目录")
    parser.add_argument(
        "--output",
        default=str(ROOT / "dist" / KIT_NAME),
        help=f"输出ZIP，文件名必须为{KIT_NAME}",
    )
    parser.add_argument("--result", help="可选：保存JSON构建证据")
    args = parser.parse_args(argv)
    try:
        result = build_codex_kit(args.wheel, args.output)
    except (KitBuildError, ValueError, OSError, zipfile.BadZipFile) as exc:
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
