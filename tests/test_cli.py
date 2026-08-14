from color_palette.cli import main


def test_cli_smoke(gradient_jpg, tmp_path):
    code = main([str(gradient_jpg), "--output", str(tmp_path / "cli")])
    assert code == 0
    assert (tmp_path / "cli" / "gradient_analysis.json").exists()
    assert (tmp_path / "cli" / "gradient_color_report.png").exists()
    assert not (tmp_path / "cli" / "gradient_color_report.jpg").exists()
