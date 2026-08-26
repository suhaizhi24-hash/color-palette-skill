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
# 必须先扫描checkout原貌；不得先自动登记或生成样例。
python tools/privacy_scan.py .

# 仅在有意更新公开合成夹具时执行：先人工审核并更新
# examples/public_examples_provenance.json，再运行生成器。
python tools/generate_public_fixtures.py
python tools/privacy_scan.py .

python -m compileall -q src tests tools scripts
pytest
python tools/validate_schemas.py .
python scripts/run_lighting_benchmark.py --manifest-only
python tools/validate_light_effect_dataset.py --root .
color-palette-doctor
python -m build --wheel
python tools/audit_wheel.py dist --expected-version 0.15.0
python tools/clean_wheel_smoke.py dist \
  --input examples/public/synthetic_srgb_icc.png \
  --schema schemas/analysis.schema.json \
  --output wheel_smoke_output \
  --result clean_wheel_smoke.json
```

## 提交图片示例

只接受程序生成并经人工审核的合成样本。人工维护
`examples/public_examples_provenance.json`；生成器只读取该来源表并生成
`examples/public_examples_manifest.json`，不得自动把未知图片写入来源表。
