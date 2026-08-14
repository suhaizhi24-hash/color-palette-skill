from __future__ import annotations

from pathlib import Path

from .constants import SUPPORTED_EXTENSIONS
from .pipeline import run


def run_batch(input_dir: str | Path, output_dir: str | Path) -> list[dict]:
    source = Path(input_dir)
    destination = Path(output_dir)
    results = []
    for image_path in sorted(source.iterdir()):
        if image_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        sample_output = destination / image_path.stem
        try:
            outputs = run(image_path, sample_output)
            results.append({"image": image_path.name, "status": "成功", **{k: str(v) for k, v in outputs.items()}})
        except Exception as exc:
            results.append({"image": image_path.name, "status": "失败", "error": str(exc)})
    return results
