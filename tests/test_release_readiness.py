from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_workflow_is_manual_or_version_tag_only():
    text = _workflow_text()
    trigger_block = text.split("permissions:", 1)[0]

    assert "workflow_dispatch:" in trigger_block
    assert 'push:\n    tags:\n      - "v*"' in trigger_block
    assert "pull_request:" not in trigger_block
    assert "schedule:" not in trigger_block
    assert "refs/heads/main" in text
    assert "ref_name == 'v' + version" in text


def test_release_workflow_is_read_only_and_artifact_only():
    text = _workflow_text()
    folded = text.casefold()

    assert text.count("permissions:") == 1
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "${{ secrets." not in text
    assert "personal_access_token" not in folded
    assert "gh release create" not in folded
    assert "softprops/action-gh-release" not in folded
    assert "persist-credentials: false" in text
    assert "actions/upload-artifact@v4" in text


def test_release_workflow_runs_complete_gates_in_safe_order():
    text = _workflow_text()
    smoke = (ROOT / "tools" / "clean_wheel_smoke.py").read_text(encoding="utf-8")
    first_privacy_scan = text.index("安装项目前扫描发布候选源码")
    project_install = text.index('python -m pip install -e ".[dev]"')
    second_privacy_scan = text.index("再次执行隐私扫描")
    schema_evidence = text.index("schema_validation_release.json")
    public_golden = text.index("运行公开 Golden Dataset")
    wheel_build = text.index("python -m build --wheel")
    wheel_audit = text.index("python tools/audit_wheel.py dist")
    clean_install = text.index("python tools/clean_wheel_smoke.py dist")
    wheel_hash = text.index("记录 Wheel SHA-256 与源码 commit")
    artifact_upload = text.index("上传已验证的发布候选 Artifact")

    assert first_privacy_scan < project_install < wheel_build
    assert second_privacy_scan < schema_evidence < public_golden < wheel_build
    assert wheel_build < wheel_audit < clean_install < wheel_hash < artifact_upload
    assert "generate_public_fixtures.py" not in text

    required_markers = (
        "python -m compileall -q src tests tools scripts",
        "major == 4",
        "python -m pytest -q",
        "python tools/validate_schemas.py",
        "python tools/privacy_scan.py",
        "test_core_source_has_no_network_or_paid_model_client_imports",
        "tests/test_formats.py tests/test_release_formats.py",
        "color-palette-golden",
        "validate_light_effect_dataset.py",
        "color-palette --help",
        "color-palette-doctor",
        "--expected-version 0.14.0",
        "run_lighting_benchmark.py --manifest-only",
        "SOURCE_DATE_EPOCH",
        "{'.jpg', '.jpeg'}",
    )
    for marker in required_markers:
        assert marker in text

    assert '"pip", "check"' in smoke
    assert 'rglob("*.jpg")' in smoke
    assert 'rglob("*.jpeg")' in smoke


def test_release_artifact_contains_wheel_hash_commit_and_gate_evidence():
    text = _workflow_text()

    for marker in (
        "dist/*.whl",
        "dist/SHA256SUMS.txt",
        "dist/SOURCE_COMMIT.txt",
        "privacy_scan_release.json",
        "schema_validation_release.json",
        "golden_validation_report.json",
        "light_effect_validation_release.json",
        "lighting_benchmark_registry_release.json",
        "doctor_release.json",
        "wheel_audit_release.json",
        "clean_wheel_smoke_release.json",
        "ci_output/",
        "if-no-files-found: error",
    ):
        assert marker in text
