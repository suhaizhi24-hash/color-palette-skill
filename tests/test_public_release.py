import ast
import io
import json
from pathlib import Path
import struct
import sys

from jsonschema import Draft202012Validator
from PIL import Image
import pytest

from color_palette import __version__
from color_palette.constants import DEFAULT_FACE_BACKEND, OFFICIAL_LANGUAGE
from tools import clean_wheel_smoke, generate_public_fixtures
from tools.privacy_scan import scan
from tools.validate_schemas import validate as validate_schemas
from tools.validate_light_effect_dataset import validate


ROOT = Path(__file__).resolve().parents[1]


def test_public_privacy_scan_passes():
    result = scan(ROOT)
    assert result["status"] == "通过", result["errors"]


def test_light_effect_public_dataset_is_valid():
    result = validate(
        ROOT,
        ROOT / "examples" / "light_effect_ground_truth.example.json",
        ROOT / "schemas" / "light_effect_ground_truth.schema.json",
    )
    assert result["status"] == "通过", result["issues"]


def test_analysis_schema_targets_v012():
    schema = json.loads((ROOT / "schemas" / "analysis.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "0.12.0"


def test_version_and_release_contract_are_consistent():
    expected = "0.12.0"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    schema = json.loads((ROOT / "schemas" / "analysis.schema.json").read_text())
    policy = json.loads((ROOT / "config" / "output_policy.json").read_text())
    release = json.loads((ROOT / "release_manifest.json").read_text())
    public_manifest = json.loads(
        (ROOT / "examples" / "public_examples_manifest.json").read_text()
    )
    provenance = json.loads(
        (ROOT / "examples" / "public_examples_provenance.json").read_text()
    )

    assert __version__ == expected
    assert f'version = "{expected}"' in pyproject
    assert schema["properties"]["schema_version"]["const"] == expected
    assert policy["policy_version"] == expected
    assert release["version"] == expected
    assert public_manifest["version"] == expected
    assert provenance["version"] == expected
    assert release["official_language"] == OFFICIAL_LANGUAGE == "zh-CN"
    assert release["face_backend"]["default"] == DEFAULT_FACE_BACKEND == "opencv"
    assert release["face_backend"]["opencv_supported"] == ">=4.9,<5"
    assert release["report"] == {
        "format": "PNG",
        "width": 1600,
        "height": 1200,
        "ratio": "4:3",
        "generate_jpg": False,
    }


def test_all_public_examples_match_json_schemas():
    result = validate_schemas(ROOT)
    assert result["status"] == "通过", result["errors"]
    assert result["checked_pair_count"] == 3


def test_no_paid_model_runtime_dependency():
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8").casefold()
    banned_packages = ["openai", "anthropic", "google-generativeai", "litellm"]
    assert all(package not in metadata for package in banned_packages)
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src").rglob("*.py")
    ).casefold()
    assert "import openai" not in source
    assert "from openai" not in source


def test_fixture_generator_cannot_write_reviewed_provenance_registry():
    source = (ROOT / "tools" / "generate_public_fixtures.py").read_text(
        encoding="utf-8"
    )
    assert "PROVENANCE_PATH.write_text" not in source
    assert "load_reviewed_provenance" in source


def test_clean_wheel_smoke_help_is_utf8_when_stdout_starts_as_cp1252(
    monkeypatch,
):
    raw_output = io.BytesIO()
    windows_style_stdout = io.TextIOWrapper(raw_output, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", windows_style_stdout)

    with pytest.raises(SystemExit) as exit_info:
        clean_wheel_smoke.main(["--help"])
    assert exit_info.value.code == 0
    windows_style_stdout.flush()

    decoded = raw_output.getvalue().decode("utf-8")
    assert "在干净虚拟环境安装Wheel并执行PNG+JSON回归" in decoded
    assert windows_style_stdout.encoding.casefold().replace("-", "") == "utf8"


def test_fixture_generator_configures_cp1252_stdout_before_provenance_read(
    monkeypatch,
):
    class StopAfterStdioConfigured(Exception):
        pass

    raw_output = io.BytesIO()
    windows_style_stdout = io.TextIOWrapper(raw_output, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", windows_style_stdout)

    def stop_before_generation():
        raise StopAfterStdioConfigured

    monkeypatch.setattr(
        generate_public_fixtures,
        "load_reviewed_provenance",
        stop_before_generation,
    )
    with pytest.raises(StopAfterStdioConfigured):
        generate_public_fixtures.main()

    print("公开样例", file=sys.stdout)
    windows_style_stdout.flush()
    assert raw_output.getvalue().decode("utf-8") == "公开样例\n"
    assert windows_style_stdout.encoding.casefold().replace("-", "") == "utf8"


def test_generated_icc_fixture_has_deterministic_header_date(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_public_fixtures, "OUT", tmp_path)
    path = generate_public_fixtures.save_icc()
    with Image.open(path) as image:
        profile = image.info["icc_profile"]
    assert profile[24:36] == struct.pack(">6H", 2024, 1, 1, 0, 0, 0)


def test_core_source_has_no_network_or_paid_model_client_imports():
    banned_roots = {
        "aiohttp",
        "anthropic",
        "httpx",
        "litellm",
        "openai",
        "requests",
        "socket",
        "urllib",
        "urllib3",
    }
    imported_roots: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint(banned_roots)


def test_cli_has_no_api_key_or_token_option():
    from color_palette.cli import build_parser

    option_strings = {
        option.casefold()
        for action in build_parser()._actions
        for option in action.option_strings
    }
    assert all("key" not in option and "token" not in option for option in option_strings)
