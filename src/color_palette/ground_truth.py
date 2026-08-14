from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Iterable

from .analyzer import analyze
from .constants import SUPPORTED_EXTENSIONS
from .io import sha256_file


GROUND_TRUTH_SCHEMA_VERSION = "1.0.0"


class GroundTruthError(ValueError):
    """Raised when a ground-truth document is missing or malformed."""


@dataclass(frozen=True)
class FieldCheck:
    path: str
    expected: Any
    actual: Any
    passed: bool
    severity: str
    tolerance: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "severity": self.severity,
            "tolerance": self.tolerance,
        }


def load_ground_truth(path: str | Path) -> dict:
    document_path = Path(path).expanduser().resolve()
    if not document_path.exists():
        raise GroundTruthError(f"Ground Truth 文件不存在：{document_path}")
    try:
        document = json.loads(document_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GroundTruthError(f"Ground Truth 读取失败：{document_path.name}") from exc
    _validate_document(document)
    return document


def discover_images(path: str | Path) -> list[Path]:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise GroundTruthError(f"待验证路径不存在：{root}")
    if root.is_file():
        if root.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise GroundTruthError(f"不支持的图片格式：{root.suffix or '无扩展名'}")
        return [root]
    return sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def validate_dataset(
    image_path: str | Path,
    ground_truth: dict,
    *,
    strict_missing: bool = False,
    include_advisory: bool = False,
    max_side: int = 1600,
    face_backend: str | None = None,
) -> dict:
    """Validate local images against a hash-only Ground Truth document.

    The public project never needs to contain the source images. A sample is
    matched by SHA-256, analyzed locally, and compared with user-confirmed
    categorical labels plus optional numeric tolerances.
    """
    images = discover_images(image_path)
    samples_by_hash = {sample["sha256"]: sample for sample in ground_truth["samples"]}
    matched_hashes: set[str] = set()
    results: list[dict] = []
    unknown_images: list[dict] = []

    for image in images:
        digest = sha256_file(image)
        sample = samples_by_hash.get(digest)
        if sample is None:
            unknown_images.append({"file": image.name, "sha256": digest})
            continue
        matched_hashes.add(digest)
        analysis, _, _ = analyze(
            image,
            max_side=max_side,
            analyze_faces=include_advisory,
            include_palette=False,
            face_backend=face_backend,
        )
        comparison = compare_analysis(analysis, sample, include_advisory=include_advisory)
        comparison.update(
            {
                "sample_id": sample["id"],
                "file": image.name,
                "sha256": digest,
            }
        )
        results.append(comparison)

    missing_samples = [
        {
            "sample_id": sample["id"],
            "file_hint": sample.get("file_hint"),
            "sha256": sample["sha256"],
        }
        for sample in ground_truth["samples"]
        if sample["sha256"] not in matched_hashes
    ]

    required_failures = sum(result["required_failure_count"] for result in results)
    advisory_mismatches = sum(result["advisory_mismatch_count"] for result in results)
    missing_is_failure = strict_missing and bool(missing_samples)
    passed = required_failures == 0 and not missing_is_failure and bool(results)

    return {
        "ground_truth_schema_version": ground_truth["schema_version"],
        "dataset": ground_truth["dataset"],
        "status": "通过" if passed else "失败",
        "strict_missing": strict_missing,
        "include_advisory": include_advisory,
        "max_side": max_side,
        "face_backend": face_backend,
        "summary": {
            "input_image_count": len(images),
            "matched_sample_count": len(results),
            "ground_truth_sample_count": len(ground_truth["samples"]),
            "required_failure_count": required_failures,
            "advisory_mismatch_count": advisory_mismatches,
            "unknown_image_count": len(unknown_images),
            "missing_sample_count": len(missing_samples),
        },
        "results": results,
        "unknown_images": unknown_images,
        "missing_samples": missing_samples,
    }


def compare_analysis(
    analysis: dict,
    sample: dict,
    *,
    include_advisory: bool = True,
) -> dict:
    checks: list[FieldCheck] = []
    for path, expected in sample.get("expected", {}).items():
        actual = _get_path(analysis, path)
        checks.append(
            FieldCheck(
                path=path,
                expected=expected,
                actual=actual,
                passed=actual == expected,
                severity="required",
            )
        )
    if include_advisory:
        for path, expected in sample.get("advisory", {}).items():
            actual = _get_path(analysis, path)
            checks.append(
                FieldCheck(
                    path=path,
                    expected=expected,
                    actual=actual,
                    passed=actual == expected,
                    severity="advisory",
                )
            )
    for metric in sample.get("metrics", []):
        path = metric["path"]
        expected = metric["value"]
        tolerance = float(metric["tolerance"])
        actual = _get_path(analysis, path)
        passed = isinstance(actual, (int, float)) and abs(float(actual) - float(expected)) <= tolerance
        checks.append(
            FieldCheck(
                path=path,
                expected=expected,
                actual=actual,
                passed=passed,
                severity=metric.get("severity", "required"),
                tolerance=tolerance,
            )
        )

    required_failure_count = sum(
        1 for check in checks if check.severity == "required" and not check.passed
    )
    advisory_mismatch_count = sum(
        1 for check in checks if check.severity == "advisory" and not check.passed
    )
    return {
        "status": "通过" if required_failure_count == 0 else "失败",
        "required_failure_count": required_failure_count,
        "advisory_mismatch_count": advisory_mismatch_count,
        "checks": [check.as_dict() for check in checks],
    }


def write_validation_report(report: dict, path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _get_path(document: dict, path: str) -> Any:
    value: Any = document
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def _validate_document(document: dict) -> None:
    if document.get("schema_version") != GROUND_TRUTH_SCHEMA_VERSION:
        raise GroundTruthError(
            f"不支持的 Ground Truth 版本：{document.get('schema_version')!r}"
        )
    if not isinstance(document.get("dataset"), dict):
        raise GroundTruthError("Ground Truth 缺少 dataset")
    samples = document.get("samples")
    if not isinstance(samples, list) or not samples:
        raise GroundTruthError("Ground Truth 至少需要一个 sample")
    seen_hashes: set[str] = set()
    seen_ids: set[str] = set()
    for sample in samples:
        if not isinstance(sample, dict):
            raise GroundTruthError("sample 必须是对象")
        sample_id = sample.get("id")
        digest = sample.get("sha256")
        if not isinstance(sample_id, str) or not sample_id:
            raise GroundTruthError("sample.id 不能为空")
        if not isinstance(digest, str) or len(digest) != 64:
            raise GroundTruthError(f"sample {sample_id} 的 sha256 无效")
        if sample_id in seen_ids:
            raise GroundTruthError(f"sample.id 重复：{sample_id}")
        if digest in seen_hashes:
            raise GroundTruthError(f"sample.sha256 重复：{digest}")
        seen_ids.add(sample_id)
        seen_hashes.add(digest)
        for key in ["expected", "advisory"]:
            if key in sample and not isinstance(sample[key], dict):
                raise GroundTruthError(f"sample {sample_id}.{key} 必须是对象")
