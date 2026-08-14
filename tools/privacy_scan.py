#!/usr/bin/env python3
from __future__ import annotations

import codecs
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from PIL import ExifTags, Image
from color_palette.argparse_zh import ChineseArgumentParser


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".avif",
    ".dng",
    ".raw",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".orf",
    ".rw2",
    ".raf",
}
FONT_EXTENSIONS = {
    ".ttf",
    ".otf",
    ".ttc",
    ".woff",
    ".woff2",
    ".eot",
    ".dfont",
    ".pfa",
    ".pfb",
    ".fon",
    ".fnt",
}
SENSITIVE_EXTENSIONS = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".ppk",
    ".jks",
    ".keystore",
    ".kdbx",
}
ARCHIVE_EXTENSIONS = {
    ".whl",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".zst",
    ".7z",
    ".rar",
}
PRIVATE_PARTS = {
    "private",
    "personal",
    "私人样片",
    "用户照片",
    "人像验收图",
    "golden_dataset_private",
    "ground_truth_private",
}
BUILD_PARTS = {
    "build",
    "dist",
    "wheelhouse",
    "archive",
    "archives",
    "__pycache__",
    ".pytest_cache",
}

# Every JSON document allowed in the public release is explicit. Adding another
# JSON file is a review event, not something the scanner should silently accept.
PUBLIC_JSON_ALLOWLIST = frozenset(
    {
        "config/output_policy.json",
        "examples/golden_ground_truth.example.json",
        "examples/light_effect_ground_truth.example.json",
        "examples/output_v012/synthetic_portrait_analysis.json",
        "examples/public_examples_manifest.json",
        "examples/public_examples_provenance.json",
        "release_manifest.json",
        "schemas/analysis.schema.json",
        "schemas/ground_truth.schema.json",
        "schemas/light_effect_ground_truth.schema.json",
    }
)
PUBLIC_GROUND_TRUTH_JSONS = frozenset(
    {
        "examples/golden_ground_truth.example.json",
        "examples/light_effect_ground_truth.example.json",
    }
)
PUBLIC_ANALYSIS_JSONS = frozenset(
    {"examples/output_v012/synthetic_portrait_analysis.json"}
)
PUBLIC_IMAGE_LICENSE = "CC0-1.0"
PUBLIC_RELEASE_VERSION = "0.12.0"
PUBLIC_MANIFEST_ORIGIN = "程序生成，无真人、无私人素材、无外部版权依赖"

SECRET_PATTERNS = {
    "OpenAI格式密钥": re.compile(
        r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}\b"
    ),
    "Anthropic格式密钥": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    "GitHub令牌": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "GitHub精细权限令牌": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "GitLab令牌": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "Slack令牌": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "Stripe正式密钥": re.compile(r"\b[rs]k_live_[A-Za-z0-9]{16,}\b"),
    "Google API密钥": re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    "Hugging Face令牌": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    "npm令牌": re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    "PyPI令牌": re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"),
    "AWS访问密钥": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "私钥正文": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    ),
    # Character class keeps the scanner's own source from containing a complete
    # credential marker while still matching the real marker in candidate data.
    "PGP私钥正文": re.compile(r"-----BEGIN PGP PRIVATE KEY B[L]OCK-----"),
    "Bearer令牌": re.compile(
        r"\bBearer\s+eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
    ),
}

# Public examples may keep only the EXIF orientation needed by the deterministic
# orientation fixture. All other EXIF fields are unnecessary release metadata.
ALLOWED_EXIF_TAGS = {274}
ALLOWED_IMAGE_INFO_KEYS = {
    "background",
    "chromaticity",
    "dpi",
    "duration",
    "exif",
    "gamma",
    "icc_profile",
    "interlace",
    "jfif",
    "jfif_density",
    "jfif_unit",
    "jfif_version",
    "loop",
    "srgb",
    "transparency",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fallback_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        retained_dirs: list[str] = []
        for name in dirnames:
            path = directory_path / name
            if name == ".git":
                continue
            if path.is_symlink():
                candidates.append(path)
            else:
                retained_dirs.append(name)
        dirnames[:] = retained_dirs
        candidates.extend(directory_path / name for name in filenames)
    return sorted(set(candidates), key=lambda path: path.as_posix())


def candidate_files(root: Path) -> list[Path]:
    """Return the exact Git release candidates, including force-added files.

    A nested temporary directory may live below another Git checkout during
    tests. In that case it must use the filesystem fallback instead of querying
    the parent repository's index.
    """

    root = root.resolve()
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        git_root = Path(os.fsdecode(top_level.stdout).strip()).resolve()
        if git_root != root:
            raise ValueError("扫描根目录不是Git工作区根目录")
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError, ValueError):
        return _fallback_candidates(root)

    candidates = [
        root / os.fsdecode(name)
        for name in result.stdout.split(b"\0")
        if name
    ]
    return sorted(set(candidates), key=lambda path: path.as_posix())


def find_secret_labels(path: Path) -> set[str]:
    labels: set[str] = set()
    tail = b""
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                combined = tail + chunk
                text = combined.decode("utf-8", errors="ignore")
                for label, pattern in SECRET_PATTERNS.items():
                    if pattern.search(text):
                        labels.add(label)
                tail = combined[-512:]
    except OSError:
        labels.add("不可读取文件")
    return labels


def _read_header(path: Path, size: int = 512) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _has_image_signature(header: bytes) -> bool:
    if header.startswith(
        (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM", b"8BPS")
    ):
        return True
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return True
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return True
    if header.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n"):
        return True
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        return brand in {
            b"avif",
            b"avis",
            b"heic",
            b"heix",
            b"hevc",
            b"hevx",
            b"mif1",
            b"msf1",
        }
    return False


def _has_font_signature(header: bytes) -> bool:
    return header.startswith(
        (b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"wOFF", b"wOF2")
    )


def _has_archive_signature(header: bytes) -> bool:
    return header.startswith(
        (
            b"PK\x03\x04",
            b"PK\x05\x06",
            b"PK\x07\x08",
            b"\x1f\x8b",
            b"BZh",
            b"\xfd7zXZ\x00",
            b"7z\xbc\xaf'\x1c",
            b"Rar!\x1a\x07",
            b"(\xb5/\xfd",
        )
    )


def _is_probably_binary(header: bytes) -> bool:
    if not header:
        return False
    if b"\x00" in header:
        return True
    try:
        # final=False accepts a multibyte UTF-8 character cut by the fixed-size
        # sample boundary, while still rejecting invalid bytes in the sample.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        decoder.decode(header, final=False)
    except UnicodeDecodeError:
        return True
    return False


def _safe_manifest_path(root: Path, value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, "路径不是非空字符串"
    if "\\" in value or "\x00" in value or re.match(r"^[A-Za-z]:", value):
        return None, "路径格式不安全"
    relative = PurePosixPath(value)
    normalized = relative.as_posix()
    if relative.is_absolute() or ".." in relative.parts or normalized != value:
        return None, "路径越界或未规范化"
    if not relative.parts or relative.parts[0] != "examples":
        return None, "路径不在examples目录"
    resolved_root = root.resolve()
    resolved_path = (resolved_root / Path(*relative.parts)).resolve(strict=False)
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        return None, "解析后路径越界"
    return normalized, None


def _load_json(path: Path, description: str, errors: list[str]) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        errors.append(f"{description}无法读取：{path.name}")
        return None


def _load_manifest(root: Path, errors: list[str]) -> tuple[dict, dict[str, dict]]:
    manifest_path = root / "examples" / "public_examples_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        errors.append("缺少可读取的公开示例清单")
        return {}, {}
    manifest = _load_json(manifest_path, "公开示例清单", errors)
    if not isinstance(manifest, dict):
        if manifest is not None:
            errors.append("公开示例清单顶层必须是对象")
        return {}, {}
    if manifest.get("version") != PUBLIC_RELEASE_VERSION:
        errors.append(f"公开示例清单version必须为{PUBLIC_RELEASE_VERSION}")
    if manifest.get("privacy") != "公开":
        errors.append("公开示例清单privacy必须为公开")
    if manifest.get("license") != PUBLIC_IMAGE_LICENSE:
        errors.append(f"公开示例清单许可必须为{PUBLIC_IMAGE_LICENSE}")
    if manifest.get("origin") != PUBLIC_MANIFEST_ORIGIN:
        errors.append("公开示例清单origin不是允许的程序生成来源声明")

    items = manifest.get("files")
    if not isinstance(items, list):
        errors.append("公开示例清单files必须是数组")
        return manifest, {}

    allowed: dict[str, dict] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"公开示例清单第{index + 1}项不是对象")
            continue
        relative, path_error = _safe_manifest_path(root, item.get("path"))
        display_path = item.get("path", f"第{index + 1}项")
        if path_error:
            errors.append(f"示例清单路径不安全：{display_path}：{path_error}")
        if item.get("license") != PUBLIC_IMAGE_LICENSE:
            errors.append(f"示例图片许可必须为{PUBLIC_IMAGE_LICENSE}：{display_path}")
        if item.get("generated") is not True:
            errors.append(f"示例图片未标记为程序生成：{display_path}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"示例图片SHA-256格式无效：{display_path}")
        if relative is None:
            continue
        if Path(relative).suffix.lower() not in IMAGE_EXTENSIONS:
            errors.append(f"示例清单包含非允许图片格式：{relative}")
        if relative in allowed:
            errors.append(f"公开示例清单包含重复路径：{relative}")
            continue
        allowed[relative] = item
    return manifest, allowed


def _load_provenance(root: Path, errors: list[str]) -> tuple[dict, dict[str, dict]]:
    """Load the human-reviewed allowlist that the generator cannot write."""

    provenance_path = root / "examples" / "public_examples_provenance.json"
    if not provenance_path.is_file() or provenance_path.is_symlink():
        errors.append("缺少可读取的独立公开样例来源登记表")
        return {}, {}
    provenance = _load_json(provenance_path, "独立公开样例来源登记表", errors)
    if not isinstance(provenance, dict):
        if provenance is not None:
            errors.append("独立公开样例来源登记表顶层必须是对象")
        return {}, {}
    if provenance.get("version") != PUBLIC_RELEASE_VERSION:
        errors.append(f"独立来源登记表version必须为{PUBLIC_RELEASE_VERSION}")
    if provenance.get("privacy") != "公开":
        errors.append("独立来源登记表privacy必须为公开")
    if provenance.get("license") != PUBLIC_IMAGE_LICENSE:
        errors.append(f"独立来源登记表许可必须为{PUBLIC_IMAGE_LICENSE}")
    if provenance.get("review_policy") != "人工审核固定来源":
        errors.append("独立来源登记表缺少人工审核固定来源策略")
    if provenance.get("generated_by_tool") is not False:
        errors.append("独立来源登记表不得由样例生成程序自动写入")

    items = provenance.get("files")
    if not isinstance(items, list):
        errors.append("独立来源登记表files必须是数组")
        return provenance, {}

    reviewed: dict[str, dict] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"独立来源登记表第{index + 1}项不是对象")
            continue
        relative, path_error = _safe_manifest_path(root, item.get("path"))
        display_path = item.get("path", f"第{index + 1}项")
        if path_error:
            errors.append(f"独立来源登记路径不安全：{display_path}：{path_error}")
        if item.get("license") != PUBLIC_IMAGE_LICENSE:
            errors.append(f"独立来源许可必须为{PUBLIC_IMAGE_LICENSE}：{display_path}")
        if item.get("generated") is not True:
            errors.append(f"独立来源不是程序生成图片：{display_path}")
        if item.get("reviewed") is not True:
            errors.append(f"独立来源未完成人工审核：{display_path}")
        if not isinstance(item.get("origin"), str) or not item["origin"].strip():
            errors.append(f"独立来源缺少具体来源说明：{display_path}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"独立来源SHA-256格式无效：{display_path}")
        if relative is None:
            continue
        if Path(relative).suffix.lower() not in IMAGE_EXTENSIONS:
            errors.append(f"独立来源包含非允许图片格式：{relative}")
        if relative in reviewed:
            errors.append(f"独立来源登记表包含重复路径：{relative}")
            continue
        reviewed[relative] = item
    return provenance, reviewed


def _verified_public_entries(
    manifest_entries: dict[str, dict],
    provenance_entries: dict[str, dict],
    errors: list[str],
) -> dict[str, dict]:
    """Return only entries independently approved by both registries."""

    verified: dict[str, dict] = {}
    for relative in sorted(set(manifest_entries) | set(provenance_entries)):
        manifest_item = manifest_entries.get(relative)
        provenance_item = provenance_entries.get(relative)
        if manifest_item is None:
            errors.append(f"独立来源已审核但公开示例清单缺少图片：{relative}")
            continue
        if provenance_item is None:
            errors.append(f"公开示例未在独立来源登记表中审核：{relative}")
            continue
        mismatched = [
            field
            for field in ("sha256", "license", "generated")
            if manifest_item.get(field) != provenance_item.get(field)
        ]
        if mismatched:
            errors.append(
                f"公开示例清单与独立来源登记不一致（{','.join(mismatched)}）：{relative}"
            )
            continue
        verified[relative] = manifest_item
    return verified


def _inspect_image_metadata(path: Path, relative: str, errors: list[str]) -> None:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            for tag, value in exif.items():
                if tag not in ALLOWED_EXIF_TAGS and value not in (None, "", b""):
                    tag_name = ExifTags.TAGS.get(tag, str(tag))
                    errors.append(f"示例图片包含未允许EXIF字段{tag_name}：{relative}")
            for key, value in image.info.items():
                if key.casefold() not in ALLOWED_IMAGE_INFO_KEYS and value not in (
                    None,
                    "",
                    b"",
                ):
                    errors.append(f"示例图片包含未允许元数据字段{key}：{relative}")
    except Exception as exc:
        errors.append(f"示例图片读取失败：{relative}：{exc}")


def _manifest_reference(
    sample: dict,
    allowed: dict[str, dict],
) -> tuple[str | None, str | None]:
    digest = sample.get("sha256")
    if not isinstance(digest, str):
        return None, "样本缺少SHA-256"
    file_value = sample.get("file")
    if isinstance(file_value, str):
        entry = allowed.get(file_value)
        if entry is None:
            return None, f"样本图片未登记：{file_value}"
        if entry.get("sha256") != digest:
            return None, f"样本哈希与公开清单不一致：{file_value}"
        return file_value, None
    hint = sample.get("file_hint")
    if not isinstance(hint, str) or not hint or Path(hint).name != hint:
        return None, "样本缺少安全的file或file_hint"
    matches = [
        relative
        for relative, entry in allowed.items()
        if PurePosixPath(relative).name == hint and entry.get("sha256") == digest
    ]
    if len(matches) != 1:
        return None, f"file_hint未唯一引用公开清单图片：{hint}"
    return matches[0], None


def _validate_ground_truth(
    root: Path,
    relative: str,
    allowed: dict[str, dict],
    errors: list[str],
) -> None:
    document = _load_json(root / relative, "公开Ground Truth", errors)
    if not isinstance(document, dict):
        return
    dataset = document.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("privacy") != "公开":
        errors.append(f"Ground Truth privacy必须为公开：{relative}")
    samples = document.get("samples")
    if not isinstance(samples, list):
        errors.append(f"Ground Truth samples必须是数组：{relative}")
        return
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            errors.append(f"Ground Truth样本不是对象：{relative}#{index + 1}")
            continue
        reference, reference_error = _manifest_reference(sample, allowed)
        if reference_error:
            errors.append(f"{reference_error}：{relative}#{index + 1}")
            continue
        sample_id = sample.get("id")
        if sample_id != PurePosixPath(reference).stem:
            errors.append(f"Ground Truth样本ID必须与合成图片文件名一致：{relative}#{index + 1}")


def _validate_analysis(
    root: Path,
    relative: str,
    allowed: dict[str, dict],
    errors: list[str],
) -> None:
    document = _load_json(root / relative, "公开analysis", errors)
    if not isinstance(document, dict):
        return
    source = document.get("source")
    if not isinstance(source, dict):
        errors.append(f"公开analysis缺少source：{relative}")
        return
    filename = source.get("filename")
    digest = source.get("sha256")
    if not isinstance(filename, str) or Path(filename).name != filename:
        errors.append(f"公开analysis来源文件名不安全：{relative}")
        return
    matches = [
        manifest_path
        for manifest_path, entry in allowed.items()
        if PurePosixPath(manifest_path).name == filename
        and entry.get("sha256") == digest
    ]
    if len(matches) != 1:
        errors.append(f"公开analysis未唯一引用清单中的合成图片：{relative}")


def scan(root: Path) -> dict:
    root = root.resolve()
    errors: list[str] = []
    _, manifest_entries = _load_manifest(root, errors)
    _, provenance_entries = _load_provenance(root, errors)
    allowed = _verified_public_entries(manifest_entries, provenance_entries, errors)
    checked: list[str] = []
    checked_text_count = 0
    font_file_count = 0
    candidates = candidate_files(root)
    candidate_relatives: set[str] = set()

    for path in candidates:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            errors.append(f"Git候选路径越界：{path}")
            continue
        candidate_relatives.add(relative)

        # This check must precede is_file(): broken and directory symlinks are
        # deliberately not followed, but they are still release violations.
        if path.is_symlink():
            errors.append(f"仓库包含符号链接：{relative}")
            continue
        if not path.is_file():
            continue

        relative_parts = {part.casefold() for part in PurePosixPath(relative).parts}
        suffix = path.suffix.lower()
        header = _read_header(path)
        font_file = suffix in FONT_EXTENSIONS or _has_font_signature(header)
        archive_file = suffix in ARCHIVE_EXTENSIONS or _has_archive_signature(header)
        image_file = suffix in IMAGE_EXTENSIONS or _has_image_signature(header)

        for label in sorted(find_secret_labels(path)):
            errors.append(f"检测到{label}：{relative}")

        if font_file:
            font_file_count += 1
            errors.append(f"仓库包含字体文件：{relative}")
        if archive_file:
            errors.append(f"仓库包含压缩包或构建产物：{relative}")
        if suffix in SENSITIVE_EXTENSIONS or (
            path.name.startswith(".env") and path.name != ".env.example"
        ):
            errors.append(f"仓库包含敏感凭据文件：{relative}")
        if relative_parts & PRIVATE_PARTS:
            errors.append(f"仓库包含私人素材目录或文件：{relative}")
        if relative_parts & BUILD_PARTS or any(
            part.endswith(".egg-info") for part in relative_parts
        ):
            errors.append(f"仓库包含缓存或构建目录：{relative}")

        if suffix == ".json" and relative not in PUBLIC_JSON_ALLOWLIST:
            if "ground_truth" in relative.casefold() or "golden" in relative.casefold():
                errors.append(f"仓库包含未授权Ground Truth/Golden JSON：{relative}")
            else:
                errors.append(f"仓库包含未列入白名单的JSON：{relative}")

        if not image_file:
            checked_text_count += 1
            if _is_probably_binary(header) and not font_file and not archive_file:
                errors.append(f"仓库包含未授权二进制文件：{relative}")
            continue

        checked.append(relative)
        if not relative.startswith("examples/"):
            errors.append(f"公开源码中的图片不在examples目录：{relative}")
            continue
        entry = allowed.get(relative)
        if entry is None:
            errors.append(f"示例图片未登记：{relative}")
            continue
        if sha256(path) != entry.get("sha256"):
            errors.append(f"示例图片哈希与清单不一致：{relative}")
        _inspect_image_metadata(path, relative, errors)

    for relative in allowed:
        path = root / Path(*PurePosixPath(relative).parts)
        if relative not in candidate_relatives:
            errors.append(f"示例清单登记文件不是Git候选文件：{relative}")
        elif not path.exists():
            errors.append(f"示例清单登记文件不存在：{relative}")

    for relative in sorted(PUBLIC_GROUND_TRUTH_JSONS & candidate_relatives):
        _validate_ground_truth(root, relative, allowed, errors)
    for relative in sorted(PUBLIC_ANALYSIS_JSONS & candidate_relatives):
        _validate_analysis(root, relative, allowed, errors)

    return {
        "status": "通过" if not errors else "失败",
        "checked_image_count": len(checked),
        "checked_text_file_count": checked_text_count,
        "checked_candidate_file_count": len(candidates),
        "font_file_count": font_file_count,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(
        description="检查公开源码中的图片许可、私人素材、字体与密钥风险。"
    )
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = scan(Path(args.root).resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0 if result["status"] == "通过" else 1


if __name__ == "__main__":
    raise SystemExit(main())
