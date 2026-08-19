from __future__ import annotations

import base64
import csv
import hashlib
import io
from pathlib import Path
import shutil
import zipfile

import pytest

from tools.build_codex_kit import (
    EXPECTED_MEMBERS,
    KIT_NAME,
    KIT_VERSION,
    KitBuildError,
    build_codex_kit,
)
from tools.verify_codex_kit import KitVerificationError, PATH_CASES, inspect_codex_kit


ROOT = Path(__file__).resolve().parents[1]
DIST_INFO = f"color_palette_skill-{KIT_VERSION}.dist-info"


def _record(files: dict[str, bytes]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    for name, data in sorted(files.items()):
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        writer.writerow([name, f"sha256={digest}", str(len(data))])
    writer.writerow([f"{DIST_INFO}/RECORD", "", ""])
    return stream.getvalue().encode("utf-8")


def _wheel(tmp_path: Path) -> Path:
    files = {
        "color_palette/__init__.py": f'__version__ = "{KIT_VERSION}"\n'.encode(),
        f"{DIST_INFO}/METADATA": (
            "Metadata-Version: 2.4\n"
            "Name: color-palette-skill\n"
            f"Version: {KIT_VERSION}\n"
            "Requires-Dist: Pillow>=10\n\n"
        ).encode(),
        f"{DIST_INFO}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: pytest\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n\n"
        ),
    }
    files[f"{DIST_INFO}/RECORD"] = _record(files)
    path = tmp_path / f"color_palette_skill-{KIT_VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def test_codex_kit_has_exact_reviewed_public_structure(tmp_path):
    wheel = _wheel(tmp_path)
    kit = tmp_path / KIT_NAME
    result = build_codex_kit(wheel, kit)
    inspected = inspect_codex_kit(kit)

    assert result["status"] == "通过"
    assert tuple(inspected["members"]) == EXPECTED_MEMBERS
    assert result["private_assets"] is False
    assert result["font_files"] is False
    assert result["secret_or_token_findings"] == 0
    assert result["sample_source"] == "examples/synthetic_portrait.png"


def test_codex_kit_build_is_deterministic(tmp_path):
    wheel = _wheel(tmp_path)
    first = tmp_path / "first" / KIT_NAME
    second = tmp_path / "second" / KIT_NAME
    first_result = build_codex_kit(wheel, first)
    second_result = build_codex_kit(wheel, second)
    assert first_result["kit_sha256"] == second_result["kit_sha256"]
    assert first.read_bytes() == second.read_bytes()


def test_codex_kit_rejects_sample_not_matching_independent_provenance(tmp_path):
    wheel = _wheel(tmp_path)
    root = tmp_path / "root"
    (root / "examples").mkdir(parents=True)
    for relative in (
        "START_HERE.md",
        "CODEX_PROMPT.txt",
        "examples/public_examples_provenance.json",
        "examples/public_examples_manifest.json",
        "examples/synthetic_portrait.png",
    ):
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (root / "examples/synthetic_portrait.png").write_bytes(b"unknown private image")

    with pytest.raises(KitBuildError, match="哈希"):
        build_codex_kit(wheel, tmp_path / KIT_NAME, root=root)


@pytest.mark.parametrize("extra_name", [".env", "private/user.jpg", "fonts/PingFang.ttf"])
def test_codex_kit_rejects_any_extra_secret_private_or_font_file(tmp_path, extra_name):
    wheel = _wheel(tmp_path)
    kit = tmp_path / KIT_NAME
    build_codex_kit(wheel, kit)
    with zipfile.ZipFile(kit, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"color-palette-codex-kit-v{KIT_VERSION}/{extra_name}", b"x")
    with pytest.raises(KitVerificationError, match="必须且只能包含固定条目"):
        inspect_codex_kit(kit)


def test_codex_kit_rejects_embedded_token(tmp_path):
    wheel = _wheel(tmp_path)
    source_kit = tmp_path / "source" / KIT_NAME
    target_kit = tmp_path / "target" / KIT_NAME
    build_codex_kit(wheel, source_kit)
    target_kit.parent.mkdir()
    token = b"github_" + b"pat_" + b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    with zipfile.ZipFile(source_kit) as source, zipfile.ZipFile(
        target_kit, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for name in EXPECTED_MEMBERS:
            data = source.read(name)
            if name.endswith("CODEX_PROMPT.txt"):
                data += b"\n" + token
            target.writestr(name, data)
    with pytest.raises(KitVerificationError, match="GitHub令牌"):
        inspect_codex_kit(target_kit)


def test_quickstart_files_keep_zero_token_and_non_destructive_boundaries():
    prompt = (ROOT / "CODEX_PROMPT.txt").read_text(encoding="utf-8")
    start = (ROOT / "START_HERE.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/CODEX_QUICKSTART.md").read_text(encoding="utf-8")

    assert "不要修改系统级 Python 配置" in prompt
    assert "不调用外部付费 API" in prompt
    assert "原始照片未被修改" in prompt
    assert "无需 OpenAI API Key" in start
    assert "不需要 GitHub Token" in guide
    assert "PNG + JSON" in guide


def test_codex_kit_path_contract_covers_english_chinese_and_spaces():
    assert PATH_CASES == ("english-path", "中文路径", "path with spaces")
