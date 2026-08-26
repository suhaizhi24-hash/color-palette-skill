import json

from tools.build_quantitative_preview import build_preview


def test_quantitative_preview_is_explicitly_non_formal(tmp_path):
    result = build_preview("examples/synthetic_portrait.png", tmp_path)
    document = json.loads(result["json"].read_text(encoding="utf-8"))
    markdown = result["markdown"].read_text(encoding="utf-8")
    assert document["development_preview"] is True
    assert document["formal_report_ui"] is False
    assert "quantitative" in document and "color_dna" in document
    assert "development_preview = true" in markdown
    assert not list(tmp_path.glob("*.jpg"))
    assert not list(tmp_path.glob("*.jpeg"))
