#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from color_palette.argparse_zh import ChineseArgumentParser


PACKAGE_ROOT = "color_palette"
DIST_INFO_PREFIX = "color_palette_skill-"
MAX_ENTRY_COUNT = 2_000
MAX_ENTRY_SIZE = 10 * 1024 * 1024
MAX_TOTAL_SIZE = 50 * 1024 * 1024

ALLOWED_PACKAGE_SUFFIXES = {".py", ".pyi"}
ALLOWED_PACKAGE_NAMES = {"py.typed"}
ALLOWED_DIST_INFO_NAMES = {
    "METADATA",
    "WHEEL",
    "RECORD",
    "entry_points.txt",
    "top_level.txt",
    "LICENSE",
    "LICENSE.txt",
    "NOTICE",
    "NOTICE.txt",
    "COPYING",
    "AUTHORS",
}
ALLOWED_LICENSE_SUFFIXES = {"", ".txt", ".md", ".rst"}
FORBIDDEN_DIRECTORY_NAMES = {
    "docs",
    "examples",
    "fixtures",
    "fonts",
    "golden_dataset",
    "ground_truth",
    "personal",
    "private",
    "samples",
    "tests",
    "tools",
    "人像验收图",
    "用户照片",
    "私人样片",
}
SENSITIVE_FILE_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "secrets",
    "secrets.json",
}
FORBIDDEN_SUFFIXES = {
    ".bmp",
    ".dll",
    ".dylib",
    ".env",
    ".exe",
    ".gif",
    ".jpeg",
    ".jpg",
    ".key",
    ".otf",
    ".p12",
    ".pem",
    ".pfx",
    ".png",
    ".pyd",
    ".so",
    ".svg",
    ".tif",
    ".tiff",
    ".ttc",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}
WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
BANNED_RUNTIME_DEPENDENCIES = {
    "anthropic",
    "google-generativeai",
    "litellm",
    "openai",
}
SECRET_PATTERNS = {
    "OpenAI格式密钥": re.compile(
        rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"
    ),
    "GitHub令牌": re.compile(
        rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"
    ),
    "AWS访问密钥": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "私钥正文": re.compile(
        rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    ),
    "Bearer令牌": re.compile(
        rb"\bBearer\s+eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
    ),
    "高置信度凭据赋值": re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret)\b"
        rb"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{20,}"
    ),
}


def _normalise_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _is_dist_info_root(value: str) -> bool:
    folded = value.casefold()
    return folded.startswith(DIST_INFO_PREFIX) and folded.endswith(".dist-info")


def _member_parts(name: str) -> tuple[list[str] | None, list[str]]:
    errors: list[str] = []
    if not name:
        return None, ["Wheel包含空路径条目"]
    if "\\" in name:
        errors.append(f"Wheel条目使用反斜杠，Windows下可能产生路径歧义：{name}")
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        errors.append(f"Wheel条目为绝对路径：{name}")

    clean_name = name[:-1] if name.endswith("/") else name
    parts = clean_name.split("/")
    if not clean_name or any(part in {"", ".", ".."} for part in parts):
        errors.append(f"Wheel条目包含空段、当前目录或父目录跳转：{name}")

    for part in parts:
        if any(ord(character) < 32 for character in part):
            errors.append(f"Wheel条目包含控制字符：{name}")
        if ":" in part:
            errors.append(f"Wheel条目包含盘符或NTFS数据流分隔符：{name}")
        if part.rstrip(" .") != part:
            errors.append(f"Wheel条目以空格或句点结尾，Windows下不安全：{name}")
        if len(part) > 255:
            errors.append(f"Wheel条目路径段过长：{name}")
        reserved_candidate = part.split(".", 1)[0].casefold()
        if reserved_candidate in WINDOWS_RESERVED_NAMES:
            errors.append(f"Wheel条目使用Windows保留名：{name}")

    return (None if errors else parts), errors


def _classify_member(parts: list[str], is_directory: bool) -> list[str]:
    errors: list[str] = []
    top_level = parts[0]
    folded_directories = {part.casefold() for part in parts[:-1]}
    forbidden_directories = folded_directories & FORBIDDEN_DIRECTORY_NAMES
    if forbidden_directories:
        errors.append(
            "Wheel包含发布外目录："
            + "/".join(parts)
            + f"（命中{sorted(forbidden_directories)}）"
        )

    if top_level == PACKAGE_ROOT:
        if is_directory:
            return errors
        name = parts[-1]
        suffix = PurePosixPath(name).suffix.casefold()
        if name.casefold() in SENSITIVE_FILE_NAMES or suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"Wheel包目录包含敏感、图片、字体或本机二进制文件：{'/'.join(parts)}")
        if suffix not in ALLOWED_PACKAGE_SUFFIXES and name not in ALLOWED_PACKAGE_NAMES:
            errors.append(f"Wheel包目录包含不允许的文件扩展或数据文件：{'/'.join(parts)}")
        return errors

    if _is_dist_info_root(top_level):
        if is_directory:
            return errors
        relative = parts[1:]
        if not relative:
            return [f"Wheel元数据根条目无文件名：{'/'.join(parts)}"]
        name = relative[-1]
        suffix = PurePosixPath(name).suffix.casefold()
        if name.casefold() in SENSITIVE_FILE_NAMES or suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"Wheel元数据包含敏感、图片、字体或二进制文件：{'/'.join(parts)}")
        if len(relative) == 1 and name in ALLOWED_DIST_INFO_NAMES:
            return errors
        if (
            len(relative) >= 2
            and relative[0].casefold() == "licenses"
            and suffix in ALLOWED_LICENSE_SUFFIXES
        ):
            return errors
        errors.append(f"Wheel元数据目录包含不允许的文件：{'/'.join(parts)}")
        return errors

    errors.append(f"Wheel包含不允许的顶层包或发布外素材：{'/'.join(parts)}")
    return errors


def _verify_record(
    record_name: str,
    record_bytes: bytes,
    contents: dict[str, bytes],
) -> list[str]:
    errors: list[str] = []
    try:
        rows = list(csv.reader(io.StringIO(record_bytes.decode("utf-8"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        return [f"Wheel RECORD无法读取：{exc}"]

    listed: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3 or not row[0]:
            errors.append(f"Wheel RECORD包含无效行：{row!r}")
            continue
        name, digest, size = row
        if name in listed:
            errors.append(f"Wheel RECORD重复登记条目：{name}")
            continue
        listed[name] = (digest, size)

    actual_names = set(contents)
    listed_names = set(listed)
    for name in sorted(actual_names - listed_names):
        errors.append(f"Wheel文件未登记到RECORD：{name}")
    for name in sorted(listed_names - actual_names):
        errors.append(f"Wheel RECORD登记了不存在的文件：{name}")

    for name in sorted(actual_names & listed_names):
        digest, size = listed[name]
        data = contents[name]
        if name == record_name:
            if digest or size:
                errors.append("Wheel RECORD自身的哈希与大小字段必须留空")
            continue
        expected_digest = (
            base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        if digest != f"sha256={expected_digest}":
            errors.append(f"Wheel RECORD哈希不匹配：{name}")
        if size != str(len(data)):
            errors.append(f"Wheel RECORD大小不匹配：{name}")
    return errors


def _inspect_metadata(
    metadata_bytes: bytes,
    expected_version: str | None,
) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    message = BytesParser(policy=policy.default).parsebytes(metadata_bytes)
    project_name = str(message.get("Name", ""))
    version = str(message.get("Version", ""))
    if _normalise_distribution_name(project_name) != "color-palette-skill":
        errors.append(f"Wheel项目名不正确：{project_name or '<缺失>'}")
    if expected_version is not None and version != expected_version:
        errors.append(
            f"Wheel版本不正确：期望{expected_version}，实际{version or '<缺失>'}"
        )

    dependencies: list[str] = []
    optional_dependencies: list[str] = []
    for requirement in message.get_all("Requires-Dist", []):
        requirement_text = str(requirement)
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement_text)
        if not match:
            errors.append(f"Wheel包含无法解析的运行依赖：{requirement}")
            continue
        dependency = _normalise_distribution_name(match.group(1))
        if re.search(r";.*\bextra\s*==", requirement_text, flags=re.IGNORECASE):
            optional_dependencies.append(dependency)
        else:
            dependencies.append(dependency)
        if dependency in BANNED_RUNTIME_DEPENDENCIES:
            errors.append(f"Wheel包含禁止的付费大模型运行依赖：{dependency}")
    return (
        errors,
        sorted(set(dependencies)),
        sorted(set(optional_dependencies)),
    )


def audit_wheel(wheel_path: str | Path, *, expected_version: str | None = None) -> dict:
    path = Path(wheel_path)
    errors: list[str] = []
    contents: dict[str, bytes] = {}
    package_file_count = 0
    dist_info_file_count = 0
    dependencies: list[str] = []
    optional_dependencies: list[str] = []

    if not path.is_file() or path.suffix.casefold() != ".whl":
        return {
            "status": "失败",
            "wheel": str(path),
            "errors": [f"Wheel文件不存在或扩展名不正确：{path}"],
        }
    if not path.name.casefold().endswith("-py3-none-any.whl"):
        errors.append(f"Wheel不是预期的跨平台纯Python标签：{path.name}")

    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRY_COUNT:
                errors.append(f"Wheel条目数超过限制：{len(infos)} > {MAX_ENTRY_COUNT}")

            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_TOTAL_SIZE:
                errors.append(f"Wheel解压后总大小超过限制：{total_size} > {MAX_TOTAL_SIZE}")

            normalised_names: set[str] = set()
            dist_info_roots: set[str] = set()
            for info in infos[:MAX_ENTRY_COUNT]:
                parts, path_errors = _member_parts(info.filename)
                errors.extend(path_errors)
                if parts is None:
                    continue

                normalised = "/".join(parts).casefold()
                if normalised in normalised_names:
                    errors.append(f"Wheel包含重复或Windows大小写碰撞条目：{info.filename}")
                normalised_names.add(normalised)

                if info.flag_bits & 0x1:
                    errors.append(f"Wheel包含加密条目：{info.filename}")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    errors.append(f"Wheel包含不允许的压缩算法：{info.filename}")
                if info.file_size > MAX_ENTRY_SIZE:
                    errors.append(
                        f"Wheel单个条目解压大小超过限制：{info.filename} ({info.file_size})"
                    )

                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                if info.create_system == 3 and stat.S_ISLNK(unix_mode):
                    errors.append(f"Wheel包含符号链接：{info.filename}")
                elif info.create_system == 3 and file_type not in {
                    0,
                    stat.S_IFDIR,
                    stat.S_IFREG,
                }:
                    errors.append(f"Wheel包含特殊文件：{info.filename}")

                errors.extend(_classify_member(parts, info.is_dir()))
                if _is_dist_info_root(parts[0]):
                    dist_info_roots.add(parts[0])
                if info.is_dir():
                    continue
                if info.file_size > MAX_ENTRY_SIZE:
                    # 已记录失败；不要解压潜在的压缩炸弹条目。
                    continue

                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    errors.append(f"Wheel条目读取或CRC校验失败：{info.filename}：{exc}")
                    continue
                contents[info.filename] = data
                if parts[0] == PACKAGE_ROOT:
                    package_file_count += 1
                elif _is_dist_info_root(parts[0]):
                    dist_info_file_count += 1
                for label, pattern in SECRET_PATTERNS.items():
                    if pattern.search(data):
                        errors.append(f"Wheel条目检测到{label}：{info.filename}")

            if len(dist_info_roots) != 1:
                errors.append(
                    f"Wheel必须且只能包含一个.dist-info目录，实际为：{sorted(dist_info_roots)}"
                )

            metadata_names = [
                name for name in contents if name.endswith(".dist-info/METADATA")
            ]
            wheel_names = [name for name in contents if name.endswith(".dist-info/WHEEL")]
            record_names = [name for name in contents if name.endswith(".dist-info/RECORD")]
            if len(metadata_names) != 1:
                errors.append(f"Wheel必须且只能包含一个METADATA，实际为{len(metadata_names)}")
            else:
                metadata_errors, dependencies, optional_dependencies = _inspect_metadata(
                    contents[metadata_names[0]], expected_version
                )
                errors.extend(metadata_errors)
            if len(wheel_names) != 1:
                errors.append(f"Wheel必须且只能包含一个WHEEL元数据，实际为{len(wheel_names)}")
            else:
                wheel_metadata = BytesParser(policy=policy.default).parsebytes(
                    contents[wheel_names[0]]
                )
                if str(wheel_metadata.get("Root-Is-Purelib", "")).casefold() != "true":
                    errors.append("Wheel不是Root-Is-Purelib: true的纯Python包")
            if len(record_names) != 1:
                errors.append(f"Wheel必须且只能包含一个RECORD，实际为{len(record_names)}")
            else:
                errors.extend(
                    _verify_record(record_names[0], contents[record_names[0]], contents)
                )
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"Wheel无法作为ZIP读取：{exc}")

    paid_dependency = bool(
        (set(dependencies) | set(optional_dependencies))
        & BANNED_RUNTIME_DEPENDENCIES
    )
    return {
        "status": "通过" if not errors else "失败",
        "wheel": str(path),
        "entry_count": len(contents),
        "package_file_count": package_file_count,
        "dist_info_file_count": dist_info_file_count,
        "runtime_dependencies": dependencies,
        "optional_dependencies": optional_dependencies,
        "paid_model_runtime_dependency": paid_dependency,
        "errors": errors,
    }


def resolve_wheel(candidate: str | Path) -> Path:
    path = Path(candidate)
    if path.is_dir():
        wheels = sorted(path.glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError(
                f"目录中必须且只能有一个Wheel，实际找到{len(wheels)}个：{path}"
            )
        return wheels[0]
    return path


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="审计构建Wheel的路径安全、发布边界、敏感内容和运行依赖。"
    )
    parser.add_argument("wheel", help="Wheel文件，或只包含一个.whl的目录")
    parser.add_argument("--expected-version", help="可选：要求的项目版本")
    parser.add_argument("--output", help="可选：保存JSON审计结果")
    args = parser.parse_args(argv)

    try:
        wheel = resolve_wheel(args.wheel)
        result = audit_wheel(wheel, expected_version=args.expected_version)
    except ValueError as exc:
        result = {"status": "失败", "wheel": str(args.wheel), "errors": [str(exc)]}

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
