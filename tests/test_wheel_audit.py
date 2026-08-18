from __future__ import annotations

import base64
import csv
import hashlib
import io
from pathlib import Path
import stat
import zipfile

import pytest

from tools.audit_wheel import audit_wheel, main


DIST_INFO = "color_palette_skill-0.14.0.dist-info"


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


def _wheel(
    tmp_path: Path,
    *,
    extra: dict[str, bytes] | None = None,
    metadata_extra: bytes = b"",
    filename: str = "color_palette_skill-0.14.0-py3-none-any.whl",
) -> Path:
    files = {
        "color_palette/__init__.py": b'__version__ = "0.14.0"\n',
        f"{DIST_INFO}/METADATA": (
            b"Metadata-Version: 2.4\n"
            b"Name: color-palette-skill\n"
            b"Version: 0.14.0\n"
            b"Requires-Dist: Pillow>=10\n"
            + metadata_extra
            + b"\n"
        ),
        f"{DIST_INFO}/WHEEL": (
            b"Wheel-Version: 1.0\n"
            b"Generator: pytest\n"
            b"Root-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
    }
    files.update(extra or {})
    files[f"{DIST_INFO}/RECORD"] = _record(files)
    path = tmp_path / filename
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def test_valid_pure_python_wheel_passes(tmp_path):
    path = _wheel(tmp_path)
    result = audit_wheel(path, expected_version="0.14.0")
    assert result["status"] == "通过", result["errors"]
    assert result["paid_model_runtime_dependency"] is False
    assert result["runtime_dependencies"] == ["pillow"]
    assert result["optional_dependencies"] == []


def test_optional_extra_is_reported_separately_from_core_runtime(tmp_path):
    path = _wheel(
        tmp_path,
        metadata_extra=b'Requires-Dist: pytest>=8; extra == "dev"\n',
    )
    result = audit_wheel(path)
    assert result["status"] == "通过", result["errors"]
    assert result["runtime_dependencies"] == ["pillow"]
    assert result["optional_dependencies"] == ["pytest"]


@pytest.mark.parametrize(
    "member",
    [
        "../escape.py",
        "/absolute.py",
        "C:/escape.py",
        "color_palette\\escape.py",
        "color_palette/NUL.py",
    ],
)
def test_unsafe_or_nonportable_member_paths_are_rejected(tmp_path, member):
    path = _wheel(tmp_path, extra={member: b"x = 1\n"})
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert result["errors"]


@pytest.mark.parametrize(
    "member",
    [
        "color_palette/reference.jpg",
        "color_palette/PingFang.ttc",
        "color_palette/native.pyd",
        "color_palette/data/golden.json",
        "examples/private_portrait.py",
        "tests/test_private.py",
    ],
)
def test_images_fonts_data_native_files_and_release_extras_are_rejected(
    tmp_path, member
):
    path = _wheel(tmp_path, extra={member: b"not allowed"})
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert any(
        "不允许" in error or "发布外" in error or "敏感" in error
        for error in result["errors"]
    )


def test_case_insensitive_member_collision_is_rejected_for_windows(tmp_path):
    path = _wheel(
        tmp_path,
        extra={
            "color_palette/Color.py": b"VALUE = 1\n",
            "color_palette/color.py": b"VALUE = 2\n",
        },
    )
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert any("大小写碰撞" in error for error in result["errors"])


def test_symbolic_link_member_is_rejected(tmp_path):
    path = _wheel(tmp_path)
    link = zipfile.ZipInfo("color_palette/link.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(link, b"__init__.py")
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert any("符号链接" in error for error in result["errors"])


def test_embedded_github_token_is_rejected(tmp_path):
    # 分段构造，避免隐私扫描把测试源码自身当作真实令牌。
    token = b"github_" + b"pat_" + b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    path = _wheel(
        tmp_path,
        extra={"color_palette/leak.py": b'TOKEN = "' + token + b'"\n'},
    )
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert any("GitHub令牌" in error for error in result["errors"])


def test_paid_model_runtime_dependency_is_rejected(tmp_path):
    path = _wheel(tmp_path, metadata_extra=b"Requires-Dist: openai>=1\n")
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert result["paid_model_runtime_dependency"] is True
    assert any("付费大模型" in error for error in result["errors"])


def test_record_hash_mismatch_is_rejected(tmp_path):
    path = _wheel(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("color_palette/__init__.py", b"tampered = True\n")
    result = audit_wheel(path)
    assert result["status"] == "失败"
    assert any("重复" in error or "哈希不匹配" in error for error in result["errors"])


def test_cli_accepts_directory_for_windows_compatible_glob_handling(tmp_path):
    _wheel(tmp_path)
    assert main([str(tmp_path), "--expected-version", "0.14.0"]) == 0


def test_ci_audits_wheel_before_install_and_smoke():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    build = workflow.index("Build wheel")
    audit = workflow.index("Audit built wheel")
    clean_install_and_smoke = workflow.index(
        "Clean virtual environment Wheel install and CLI smoke"
    )
    assert build < audit < clean_install_and_smoke
    assert "python tools/audit_wheel.py dist" in workflow
    assert "python tools/clean_wheel_smoke.py dist" in workflow
    assert "--expected-version 0.14.0" in workflow
