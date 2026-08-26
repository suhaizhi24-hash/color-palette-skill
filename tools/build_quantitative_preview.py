#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from color_palette.analyzer import analyze
from color_palette.argparse_zh import ChineseArgumentParser


def build_preview(image_path: str | Path, output_dir: str | Path) -> dict[str, Path]:
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    analysis, _, _ = analyze(image_path, face_backend="none")
    document = {
        "development_preview": True,
        "formal_report_ui": False,
        "source": {
            "filename": analysis["source"]["filename"],
            "sha256": analysis["source"]["sha256"],
        },
        "quantitative": analysis["quantitative"],
        "color_dna": analysis["color_dna"],
    }
    json_path = output / "quant_summary.json"
    markdown_path = output / "quant_summary.md"
    json_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(document), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def _markdown(document: dict) -> str:
    quantitative = document["quantitative"]
    dna = document["color_dna"]
    neutral = quantitative["neutral_axis"]["overall"]
    palette = quantitative["palettes"]["scene_palette"]["clusters"]
    palette_lines = [
        f"- {item['role_display_name']}: {item['hex']} / area={item['area_share']:.4f} / C*={item['chroma']:.2f}"
        for item in palette
    ] or ["- 样本不足"]
    return "\n".join(
        [
            "# v0.15 Quantitative Development Preview",
            "",
            "> development_preview = true；不属于正式 1600×1200 七模块 UI。",
            "",
            "## Color DNA",
            "",
            "```json",
            json.dumps(dna, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## L* / Contrast / Tone Signature",
            "",
            f"- L* Percentiles: `{quantitative['luminance']['percentiles']}`",
            f"- Contrast: `{quantitative['contrast']}`",
            f"- Tone Signature: `{quantitative['tone_signature']}`",
            "",
            "## Chroma / Hue",
            "",
            f"- Chroma: `{quantitative['chroma']['percentiles']}`",
            f"- Dominant Hue: `{quantitative['hue_distribution']['dominant_hue']}`",
            f"- Hue Concentration: `{quantitative['hue_distribution']['hue_concentration']}`",
            "",
            "## Neutral Axis",
            "",
            f"- Overall: `{neutral}`",
            f"- Coverage: `{quantitative['neutral_axis']['neutral_spatial_coverage']}`",
            "",
            "## Neutral Tone Palette",
            "",
            f"`{quantitative['palettes']['neutral_tone_palette']}`",
            "",
            "## Scene Palette",
            "",
            *palette_lines,
            "",
            "## Subject / Background",
            "",
            f"`{quantitative['subject_background']}`",
            "",
            "## Confidence",
            "",
            f"`{quantitative['confidence']}`",
            "",
            "## 中文摘要",
            "",
            quantitative["summary_zh"],
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = ChineseArgumentParser(description="生成非正式v0.15定量分析开发预览。")
    parser.add_argument("image", help="公开或本地图片路径")
    parser.add_argument(
        "--output",
        default="qa/quant_v015_preview",
        help="开发预览输出目录",
    )
    args = parser.parse_args(argv)
    result = build_preview(args.image, args.output)
    print(
        json.dumps(
            {key: str(value) for key, value in result.items()}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
