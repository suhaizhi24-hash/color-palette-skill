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

## Round 2 增量字段

- `tone_signature.toe_state` / `shoulder_state`：基于 Toe / Shoulder Span Ratio 的 `compressed | neutral | expanded`；
- `neutral_axis.neutral_confidence` 与 `validity_reason`：多证据中性轴可信度；
- `neutral_axis.subject_neutral_share` / `background_neutral_share`：主体与背景的中性候选占比；
- `neutral_axis.overall.status`：支持 `valid | low_confidence | insufficient`；
- `subject_background.roi.mask_method` / `pixel_share` / `region_pixel_share`：定量 ROI 的可审计诊断。

`toe_ratio` / `shoulder_ratio` 为兼容保留字段，正式语义是暗部/高光跨度比，不是压缩程度。`L50` 为全局画面 L* P50；主体 L50 与背景 L50 只在可信 ROI 成立时使用。

## 迁移说明

v0.14.x 客户端如只读取旧字段无需修改。严格校验器需切换到 0.15.0 Schema。旧 JSON 不会被重新标注为 0.15.0；它应按原版本存档或由兼容 Renderer 显示。
