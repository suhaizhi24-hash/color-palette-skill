#!/usr/bin/env python3
"""Read-only smoke test for the central Photography Knowledge System."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENTRIES = (
    "KNOWLEDGE_REGISTRY.md",
    "color-science/COLOR_SCIENCE_MEMORY.md",
    "color-grading/COLOR_GRADING_MEMORY.md",
    "governance/EVIDENCE_LEVELS.md",
    "governance/KNOWLEDGE_LIFECYCLE.md",
    "color-science/README.md",
    "color-grading/README.md",
)
RULE_PATTERN = re.compile(
    r"^\|\s*((?:CS|PIPE|TONE|HUE|SAT|SKIN|CAM|FILM|LUT|FX|QA|GOV)-\d{3})"
    r"\s*\|\s*([A-Z_]+)\s*\|\s*(.*?)\s*\|$"
)


class KnowledgeSourceUnavailable(RuntimeError):
    """Raised when the central knowledge source cannot be read."""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    status: str
    statement: str


def _candidate_roots(explicit_root: str | None) -> list[Path]:
    if explicit_root:
        return [Path(explicit_root).expanduser()]

    configured = os.environ.get("PHOTOGRAPHY_KNOWLEDGE_ROOT")
    if configured:
        return [Path(configured).expanduser()]

    return [
        REPOSITORY_ROOT.parent.parent / "摄影知识树",
        REPOSITORY_ROOT.parent / "摄影知识树",
    ]


def resolve_knowledge_root(explicit_root: str | None = None) -> Path:
    candidates = _candidate_roots(explicit_root)
    missing_by_root: list[str] = []

    for candidate in candidates:
        root = candidate.resolve()
        missing = [entry for entry in REQUIRED_ENTRIES if not (root / entry).is_file()]
        if not missing:
            return root
        missing_by_root.append(f"{root}: {', '.join(missing)}")

    detail = "; ".join(missing_by_root)
    raise KnowledgeSourceUnavailable(f"knowledge source unavailable: {detail}")


def load_rules(root: Path) -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for relative_path in ("color-science/README.md", "color-grading/README.md"):
        for line in (root / relative_path).read_text(encoding="utf-8").splitlines():
            match = RULE_PATTERN.match(line)
            if not match:
                continue
            rule = Rule(*match.groups())
            if rule.rule_id in rules:
                raise AssertionError(f"duplicate Rule ID: {rule.rule_id}")
            rules[rule.rule_id] = rule
    return rules


def require_rule(rules: dict[str, Rule], rule_id: str, status: str) -> Rule:
    rule = rules.get(rule_id)
    if rule is None:
        raise AssertionError(f"missing Rule ID: {rule_id}")
    if rule.status != status:
        raise AssertionError(
            f"{rule_id} status mismatch: expected {status}, got {rule.status}"
        )
    return rule


def can_claim_validated(rule: Rule) -> bool:
    return rule.status == "VALIDATED"


def require_text(text: str, expected: str, context: str) -> None:
    if expected not in text:
        raise AssertionError(f"missing {context}: {expected}")


def run_cases(root: Path) -> list[str]:
    rules = load_rules(root)
    grading_memory = (root / "color-grading/COLOR_GRADING_MEMORY.md").read_text(
        encoding="utf-8"
    )
    science_memory = (root / "color-science/COLOR_SCIENCE_MEMORY.md").read_text(
        encoding="utf-8"
    )
    evidence_levels = (root / "governance/EVIDENCE_LEVELS.md").read_text(
        encoding="utf-8"
    )

    require_rule(rules, "LUT-101", "FOUNDATIONAL")
    require_rule(rules, "FX-101", "FOUNDATIONAL")
    require_text(grading_memory, "不能独立生成真正的空间结构效果", "LUT boundary")
    require_text(grading_memory, "### Grain", "Grain section")

    require_rule(rules, "SKIN-102", "CREATIVE_HEURISTIC")
    require_text(grading_memory, "冷白皮", "cold-white-skin vocabulary")
    require_text(grading_memory, "不存在唯一参数公式", "perceptual vocabulary boundary")

    require_rule(rules, "CAM-101", "PROJECT_STANDARD")
    camera_unknown = require_rule(rules, "CAM-102", "UNKNOWN")
    require_text(
        grading_memory,
        "Scientifically Exact Camera Profile",
        "camera emulation evidence boundary",
    )
    require_text(grading_memory, "Visual / Creative Emulation", "creative emulation label")

    dji_science = require_rule(rules, "PIPE-003", "PROJECT_STANDARD")
    dji_grading = require_rule(rules, "PIPE-103", "PROJECT_STANDARD")
    expected_pipeline = "DJI D-Log M\n    → DJI 官方 Rec.709 Transform\n    → Creative LUT"
    require_text(science_memory, expected_pipeline, "Color Science DJI workflow")
    require_text(grading_memory, expected_pipeline, "Color Grading DJI workflow")

    status_names = {
        "FOUNDATIONAL",
        "PROJECT_STANDARD",
        "CREATIVE_HEURISTIC",
        "PROVISIONAL",
        "VALIDATED",
        "UNKNOWN",
    }
    available_statuses = set(re.findall(r"\b[A-Z_]+\b", evidence_levels))
    missing_statuses = status_names - available_statuses
    if missing_statuses:
        raise AssertionError(f"missing knowledge statuses: {sorted(missing_statuses)}")
    for rule in (camera_unknown, dji_science, dji_grading):
        if can_claim_validated(rule):
            raise AssertionError(f"non-validated rule promoted: {rule.rule_id}")
    validated_count = sum(rule.status == "VALIDATED" for rule in rules.values())

    return [
        "PASS Case A — LUT-101 + FX-101: 普通 3D LUT 不能独立生成空间 Grain",
        "PASS Case B — SKIN-102 / CREATIVE_HEURISTIC: 冷白皮不是单参数公式",
        "PASS Case C — CAM-101 + CAM-102: 无测量数据不得称 scientifically exact profile",
        "PASS Case D — PIPE-003 + PIPE-103 / PROJECT_STANDARD: DJI workflow 不是普遍唯一工作流",
        f"PASS Case E — 仅 VALIDATED 可声明项目实证完成；当前 VALIDATED={validated_count}",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读检查 Color Palette Skill 与中央摄影知识树的 Consumer 合同。"
    )
    parser.add_argument(
        "--knowledge-root",
        help="中央摄影知识树根目录；默认读取环境变量或工作区相对位置。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = resolve_knowledge_root(args.knowledge_root)
        results = run_cases(root)
    except KnowledgeSourceUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (AssertionError, OSError, UnicodeError) as exc:
        print(f"knowledge consumer smoke failed: {exc}", file=sys.stderr)
        return 1

    print(f"knowledge root: {root}")
    for result in results:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
