from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, PngImagePlugin
import pytest

from tools.privacy_scan import main as privacy_main
from tools.privacy_scan import scan, sha256


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_manifest(
    root: Path,
    entries: list[dict] | None = None,
    *,
    provenance_entries: list[dict] | None = None,
    write_provenance: bool = True,
) -> None:
    manifest_entries = entries if entries is not None else []
    _write_json(
        root / "examples" / "public_examples_manifest.json",
        {
            "version": "0.13.0",
            "privacy": "公开",
            "license": "CC0-1.0",
            "origin": "程序生成，无真人、无私人素材、无外部版权依赖",
            "files": manifest_entries,
        },
    )
    if write_provenance:
        reviewed_entries = (
            manifest_entries if provenance_entries is None else provenance_entries
        )
        _write_json(
            root / "examples" / "public_examples_provenance.json",
            {
                "version": "0.13.0",
                "privacy": "公开",
                "license": "CC0-1.0",
                "review_policy": "人工审核固定来源",
                "generated_by_tool": False,
                "files": [
                    {
                        **entry,
                        "reviewed": True,
                        "origin": "测试用程序合成图片",
                    }
                    for entry in reviewed_entries
                ],
            },
        )


def _write_public_png(
    root: Path,
    relative: str = "examples/public/synthetic.png",
    *,
    author: str | None = None,
) -> dict:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (16, 16), (40, 80, 120))
    if author is None:
        image.save(path)
    else:
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Author", author)
        image.save(path, pnginfo=metadata)
    return {
        "path": relative,
        "sha256": sha256(path),
        "license": "CC0-1.0",
        "generated": True,
    }


def _assert_error(result: dict, fragment: str) -> None:
    assert result["status"] == "失败"
    assert any(fragment in error for error in result["errors"]), result["errors"]


def test_minimal_public_manifest_passes(tmp_path: Path):
    _write_manifest(tmp_path)
    result = scan(tmp_path)
    assert result["status"] == "通过", result["errors"]


def test_privacy_cli_prints_chinese_when_stdout_starts_as_cp1252(
    tmp_path: Path,
    monkeypatch,
):
    _write_manifest(tmp_path)
    raw_output = io.BytesIO()
    windows_style_stdout = io.TextIOWrapper(raw_output, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", windows_style_stdout)

    assert privacy_main([str(tmp_path)]) == 0
    windows_style_stdout.flush()

    decoded = raw_output.getvalue().decode("utf-8")
    assert '"status": "通过"' in decoded
    assert windows_style_stdout.encoding.casefold().replace("-", "") == "utf8"


def test_missing_independent_provenance_registry_is_rejected(tmp_path: Path):
    _write_manifest(tmp_path, write_provenance=False)
    result = scan(tmp_path)
    _assert_error(result, "缺少可读取的独立公开样例来源登记表")


def test_self_registered_unknown_image_is_rejected(tmp_path: Path):
    entry = _write_public_png(tmp_path)
    _write_manifest(tmp_path, [entry], provenance_entries=[])
    result = scan(tmp_path)
    _assert_error(result, "公开示例未在独立来源登记表中审核")


def test_manifest_hash_must_match_independent_provenance(tmp_path: Path):
    entry = _write_public_png(tmp_path)
    reviewed = {**entry, "sha256": "0" * 64}
    _write_manifest(tmp_path, [entry], provenance_entries=[reviewed])
    result = scan(tmp_path)
    _assert_error(result, "公开示例清单与独立来源登记不一致")


def test_file_directory_and_broken_symlinks_are_rejected(tmp_path: Path):
    _write_manifest(tmp_path)
    target_file = tmp_path / "target.txt"
    target_file.write_text("公开测试", encoding="utf-8")
    target_directory = tmp_path / "target-directory"
    target_directory.mkdir()
    try:
        (tmp_path / "file-link").symlink_to(target_file.name)
        (tmp_path / "directory-link").symlink_to(
            target_directory.name,
            target_is_directory=True,
        )
        (tmp_path / "broken-link").symlink_to("missing-target")
    except OSError as exc:
        pytest.skip(f"当前平台不允许创建符号链接：{exc}")

    result = scan(tmp_path)
    _assert_error(result, "仓库包含符号链接：file-link")
    _assert_error(result, "仓库包含符号链接：directory-link")
    _assert_error(result, "仓库包含符号链接：broken-link")


@pytest.mark.parametrize(
    "relative",
    ["build/leak.txt", "dist/leak.txt", "archive/source.zip"],
)
def test_force_tracked_build_dist_and_archive_are_rejected(
    tmp_path: Path,
    relative: str,
):
    _write_manifest(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "build/\ndist/\narchive/\n",
        encoding="utf-8",
    )
    artifact = tmp_path / relative
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("release artifact", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-f", relative], cwd=tmp_path, check=True)

    result = scan(tmp_path)
    if relative.startswith("archive/"):
        _assert_error(result, "压缩包或构建产物")
    else:
        _assert_error(result, "缓存或构建目录")


def test_unlisted_ground_truth_json_is_rejected(tmp_path: Path):
    _write_manifest(tmp_path)
    _write_json(
        tmp_path / "examples" / "customer_ground_truth.json",
        {"dataset": {"privacy": "私人"}, "samples": []},
    )
    result = scan(tmp_path)
    _assert_error(result, "未授权Ground Truth/Golden JSON")


def test_public_ground_truth_requires_public_privacy_and_manifest_reference(
    tmp_path: Path,
):
    _write_manifest(tmp_path)
    _write_json(
        tmp_path / "examples" / "golden_ground_truth.example.json",
        {
            "dataset": {"privacy": "私人"},
            "samples": [
                {
                    "id": "customer",
                    "file_hint": "customer.png",
                    "sha256": "0" * 64,
                }
            ],
        },
    )
    result = scan(tmp_path)
    _assert_error(result, "Ground Truth privacy必须为公开")
    _assert_error(result, "file_hint未唯一引用公开清单图片")


def test_valid_ground_truth_references_manifest_image(tmp_path: Path):
    entry = _write_public_png(tmp_path)
    _write_manifest(tmp_path, [entry])
    _write_json(
        tmp_path / "examples" / "golden_ground_truth.example.json",
        {
            "dataset": {"privacy": "公开"},
            "samples": [
                {
                    "id": "synthetic",
                    "file_hint": "synthetic.png",
                    "sha256": entry["sha256"],
                }
            ],
        },
    )
    result = scan(tmp_path)
    assert result["status"] == "通过", result["errors"]


def test_public_analysis_requires_manifest_image_reference(tmp_path: Path):
    _write_manifest(tmp_path)
    _write_json(
        tmp_path / "examples" / "output_v013" / "synthetic_portrait_analysis.json",
        {
            "source": {
                "filename": "customer.png",
                "sha256": "0" * 64,
            }
        },
    )
    result = scan(tmp_path)
    _assert_error(result, "公开analysis未唯一引用清单中的合成图片")


def test_manifest_rejects_path_traversal(tmp_path: Path):
    _write_manifest(
        tmp_path,
        [
            {
                "path": "../outside.png",
                "sha256": "0" * 64,
                "license": "CC0-1.0",
                "generated": True,
            }
        ],
    )
    result = scan(tmp_path)
    _assert_error(result, "示例清单路径不安全")


def test_manifest_accepts_only_cc0_license(tmp_path: Path):
    entry = _write_public_png(tmp_path)
    entry["license"] = "generated"
    _write_manifest(tmp_path, [entry])
    result = scan(tmp_path)
    _assert_error(result, "示例图片许可必须为CC0-1.0")


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("OpenAI格式密钥", "sk-" + "proj-" + "A" * 28),
        ("Anthropic格式密钥", "sk-" + "ant-api03-" + "A" * 28),
        ("GitHub精细权限令牌", "github" + "_pat_" + "A" * 28),
        ("GitLab令牌", "gl" + "pat-" + "A" * 28),
        ("Slack令牌", "xox" + "b-" + "A" * 28),
        ("Google API密钥", "AI" + "za" + "A" * 35),
        ("Hugging Face令牌", "hf" + "_" + "A" * 28),
    ],
)
def test_common_high_confidence_tokens_are_rejected(
    tmp_path: Path,
    label: str,
    token: str,
):
    _write_manifest(tmp_path)
    (tmp_path / "credentials.txt").write_text(token, encoding="utf-8")
    result = scan(tmp_path)
    _assert_error(result, label)


def test_sensitive_image_metadata_is_rejected(tmp_path: Path):
    entry = _write_public_png(tmp_path, author="Private Photographer")
    _write_manifest(tmp_path, [entry])
    result = scan(tmp_path)
    _assert_error(result, "未允许元数据字段Author")


def test_image_disguised_as_unknown_binary_is_rejected(tmp_path: Path):
    _write_manifest(tmp_path)
    disguised = tmp_path / "portrait.bin"
    Image.new("RGB", (8, 8), "red").save(disguised, format="PNG")
    result = scan(tmp_path)
    _assert_error(result, "公开源码中的图片不在examples目录")


def test_private_source_image_formats_are_ignored_by_default():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = {
        "*.[Hh][Ee][Ii][Cc]",
        "*.[Aa][Vv][Ii][Ff]",
        "*.[Dd][Nn][Gg]",
        "*.[Cc][Rr]2",
        "*.[Cc][Rr]3",
        "*.[Nn][Ee][Ff]",
        "*.[Aa][Rr][Ww]",
    }
    assert required_patterns <= set(text.splitlines())
