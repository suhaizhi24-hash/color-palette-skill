# Compare Mode v0.16 Spec（仅规格）

状态：`spec_only_not_implemented`

## 目标

未来比较 Source 与 Reference 的同定义定量指标，输出 Source、Reference、Delta 与中文“相对调色方向”。不恢复任何 Lightroom / Camera Raw 原始参数。

## 指标

- L50；
- Global Contrast；
- Midtone Contrast；
- C50 / C90；
- Overall / Shadow / Midtone / Highlight Neutral a*/b*；
- Toe Ratio / Shoulder Ratio；
- Subject/BG ΔL / ΔE00。

## Delta

Delta 仅在输入语境、ICC 标准化、分析尺寸策略和指标版本一致时计算。任一侧 `insufficient` 时对应 Delta 为 null。

## 中文输出

允许：

- 中间调需要相对抬亮；
- 全局反差需要收窄；
- 综合色度需要下降；
- 阴影中性色需要向冷青方向移动；
- 高光中性色需要向暖黄方向移动。

禁止：

- 曝光 +0.5；
- Contrast -20；
- Highlights -35；
- Temperature +600；
- 任何没有 Before/After 与外部编辑数据支撑的滑块值。

本文件不授权实现 Compare Engine，也不改变 v0.15.0 正式输出。
