from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_contains_cross_platform_matrix_and_wheel_smoke():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in text
    assert "macos-latest" in text
    assert "windows-latest" in text
    assert '"3.10"' in text
    assert '"3.12"' in text
    assert '"3.13"' in text
    assert "python -m build --wheel" in text
    assert "Clean virtual environment Wheel install and CLI smoke" in text
    assert "clean_wheel_smoke.py" in text
    assert "--force-reinstall" not in text
    assert 'PYTHONUTF8: "1"' in text
    assert "color-palette-doctor" in text
    assert "privacy_scan.py" in text
    assert "validate_schemas.py" in text
    assert "compileall" in text
    wheel_smoke = (ROOT / "tools" / "clean_wheel_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "*.jpg" in wheel_smoke
    assert "*.jpeg" in wheel_smoke
    assert "optional-dlib" in text
    assert text.count("persist-credentials: false") == 2
    assert "dist/*.whl" in text
    assert "build_codex_kit.py" in text
    assert "verify_codex_kit.py" in text
    assert "color-palette-codex-kit-v0.14.1.zip" in text
    assert "matrix.python-version == '3.12'" in text


def test_optional_dlib_does_not_depend_on_apt_mirrors():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    optional_dlib = text.split("  optional-dlib:\n", 1)[1]
    assert "cmake --version" in optional_dlib
    assert "apt-get" not in optional_dlib


def test_optional_cjk_font_install_cannot_block_core_ci():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    font_step = text.split("Install CJK font on Ubuntu (best effort)", 1)[1].split(
        "Install package and development tools", 1
    )[0]
    assert "continue-on-error: true" in font_step
    assert "timeout-minutes: 3" in font_step
    assert "timeout 150s" in font_step


def test_ci_scans_checkout_before_build_or_fixture_generation():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    first_scan = text.index("Privacy scan of checkout")
    assert first_scan < text.index('python -m pip install -e ".[dev]"')
    assert first_scan < text.index("python -m build --wheel")
    generator = text.find("generate_public_fixtures.py")
    assert generator == -1 or first_scan < generator


def test_clean_wheel_smoke_rejects_extra_output_directories():
    text = (ROOT / "tools" / "clean_wheel_smoke.py").read_text(encoding="utf-8")
    assert "entries = sorted(output_dir.iterdir())" in text
    assert "all(path.is_file() for path in entries)" in text


def test_ci_asserts_opencv_4_x_runtime():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Verify OpenCV 4.x compatibility contract" in text
    assert "major==4" in text
