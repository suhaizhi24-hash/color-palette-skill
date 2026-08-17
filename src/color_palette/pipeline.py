from __future__ import annotations

from pathlib import Path
import json

from .analyzer import analyze
from .render import FontResolver, render_report


def run(
    image_path: str | Path,
    output_dir: str | Path,
    *,
    face_backend: str | None = None,
    max_side: int = 1600,
) -> dict[str, Path]:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    analysis, loaded, _ = analyze(
        image_path,
        max_side=max_side,
        face_backend=face_backend,
    )
    stem = Path(image_path).stem
    json_path = output / f"{stem}_analysis.json"
    png_path = output / f"{stem}_color_report.png"

    analysis["font_policy"] = FontResolver().metadata()
    analysis["outputs"] = {
        "analysis_json": json_path.name,
        "color_report_png": png_path.name,
        "jpg_generated": False,
    }
    json_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    render_report(analysis, loaded, png_path)

    return {"analysis_json": json_path, "color_report_png": png_path}
