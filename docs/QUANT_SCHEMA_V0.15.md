# Analysis Schema 0.15.0

## 兼容策略

Schema 版本升级为 `0.15.0`。旧的 `tone`、`contrast`、`saturation`、`white_balance`、`tonal_palette`、`skin`、`lighting`、`light`、`material_effects` 与 `effects` 保留，正式 Renderer 继续只消费既有字段。

新顶层属性 `quantitative` 与 `color_dna` 在 Schema 中定义为可选，便于旧 JSON 被兼容 Renderer 读取；v0.15.0 分析器生成的新 JSON 必须同时包含两者。

## 结构

```json
{
  "schema_version": "0.15.0",
  "quantitative": {
    "measurement_context": {},
    "luminance": {},
    "histograms": {},
    "contrast": {},
    "tone_signature": {},
    "chroma": {},
    "hue_distribution": {},
    "neutral_axis": {},
    "palettes": {},
    "subject_background": {},
    "confidence": {},
    "summary_zh": "",
    "performance": {}
  },
  "color_dna": {}
}
```

## 约束

- share：0–1；
- L*：0–100；
- hue angle：0 <= h < 360；
- RGB：三个 0–255 integer；
- insufficient：不可测数值使用 null；
- JSON 不允许 NaN 或 Infinity；
- `edit_parameter_inference` 恒为 false；
- `schema_version`、输出策略、官方语言与发布清单保持一致。

## 迁移说明

v0.14.x 客户端如只读取旧字段无需修改。严格校验器需切换到 0.15.0 Schema。旧 JSON 不会被重新标注为 0.15.0；它应按原版本存档或由兼容 Renderer 显示。
