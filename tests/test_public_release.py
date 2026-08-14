import ast
import json
from pathlib import Path

from jsonschema import Draft202012Validator

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
