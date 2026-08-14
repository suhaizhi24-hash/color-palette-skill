# 贡献指南

感谢参与调色盘 / 色彩卡片。

## 开发原则

- 不调用 OpenAI API；
- 不修改输入照片色彩参数；
- 用户可见文案使用中文；
- UI 与官方七模块遵循 SKILL.md；
- 新规则必须有测试或 Golden Dataset 支持；
- 不提交私人照片。
- 不提交私人 Ground Truth、人像验收图或字体文件；
- 不提交密钥、Token、`.env` 或其他凭据；
- dlib 只能作为可选增强，OpenCV 必须保持可用；
- 正式流程只能生成 PNG 与 `analysis.json`，不得生成 JPG/JPEG。

## 本地检查

```bash
python tools/generate_public_fixtures.py
python -m compileall -q src tests tools
pytest
python tools/validate_schemas.py .
python tools/privacy_scan.py .
python tools/validate_light_effect_dataset.py --root .
color-palette-doctor
python -m build --wheel
python tools/audit_wheel.py dist --expected-version 0.12.0
```

## 提交图片示例

只接受程序生成或有明确公开许可的样本，并更新 `examples/public_examples_manifest.json`。
