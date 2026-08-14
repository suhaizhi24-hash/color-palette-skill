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
    assert "Wheel CLI smoke test" in text
    assert "color-palette-doctor" in text
    assert "privacy_scan.py" in text
    assert "validate_schemas.py" in text
    assert "compileall" in text
    assert "*.jpeg" in text
    assert "optional-dlib" in text
