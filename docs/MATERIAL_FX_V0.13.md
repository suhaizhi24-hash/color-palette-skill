# Material FX V0.13 规则与 Schema

## 目标

Material FX 只分析最终图像中可靠可见的视觉现象。它不修改原图，不调用网络或
付费模型，也不保证还原作者实际使用的软件、滤镜、插件或制作步骤。

## 分析链路

```text
候选视觉现象
→ Flat / Edge / Face / Highlight ROI 多区域验证
→ 排除竞争解释
→ 内部阈值与置信度
→ 0..N 个中文 display_name
→ PNG 逐行显示标签
```

内部 `confidence`、`evidence`、`alternatives`、`regions` 仅写入
`analysis.json`；正式 PNG 不读取这些字段。

## 分类

| 内部类型 | 正式中文标签 |
| --- | --- |
| `grain/fine` | 细颗粒 |
| `grain/coarse` | 粗颗粒 |
| `softness` | 柔化 |
| `gaussian_blur` | 高斯模糊 |
| `low_clarity` | 低清晰度 |
| `highlight_diffusion` | 高光扩散 |
| `rgb_shift` | RGB 色彩偏移 |
| `image_degradation` | 画质降低 |
| `film_scan` | 胶片扫描质感 |
| `film_border` | 胶片边框 |
| `dust` | 灰尘 |
| `scratch` | 划痕 |

无可靠效果时 `items` 为空，`summary` 固定为“未发现明显素材特效”。

## 排除规则

- 主体清晰、背景随距离自然失焦时，不把浅景深归为全局模糊；
- 不因平滑肤色单独判断柔化或高斯模糊；
- 不因强逆光单独判断高光扩散；
- 暗部色噪、JPEG 块效应和真实物体纹理不归为颗粒；
- 高饱和、高对比仍由既有色彩模块负责。

## Schema 与旧数据

V0.13 新增：

```json
{
  "material_effects": {
    "ruleset_version": "material-fx-0.13.0",
    "items": [
      {
        "type": "grain",
        "subtype": "fine",
        "display_name": "细颗粒",
        "confidence": 0.85,
        "evidence": ["内部证据"],
        "alternatives": ["数字噪点"],
        "regions": ["r1c1", "r2c3"]
      }
    ],
    "summary": "细颗粒",
    "status": "已识别",
    "diagnostics": {}
  }
}
```

新分析结果同时保留旧 `effects` 兼容字段。读取旧 V0.12 数据时，报告层会从
`effects.detected` 回退；旧数据没有已识别项时显示统一的无效果文案。

## 验收层级

1. 公开确定性合成回归：验证分类与误报边界；
2. 公开报告回归：验证 1600×1200、PNG + JSON 和中文逐行标签；
3. 私人真实样片 QA：Case 001 / Case 002 仅在本地执行，不进入公开仓库。
