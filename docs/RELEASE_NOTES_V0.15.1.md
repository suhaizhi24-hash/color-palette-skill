# 调色盘 / 色彩卡片 v0.15.1 Beta

> Candidate：真实私人样片人工验收与最新 commit 三平台 CI 通过前，不得创建 Tag 或 Release。

## 本轮变更

v0.15.1 只修正倾斜、柔焦单人像在 OpenCV 常规检测中漏检时的肤色锚点恢复路径，并增加可审计的 `skin.diagnostics`。苹果肌主锚点与额头副锚点现在独立评估，主锚点不再被无效额头样本反向否定。

## 不变的契约

- Local-first / Zero-token，不调用 OpenAI API 或其他付费模型；
- 不要求 API Key；
- 不修改原始照片的曝光、白平衡、色相、饱和度、对比度或肤色；
- Quantitative Core、Light Analysis、Material FX、Neutral Axis 与 Scene Palette 不变；
- 正式报告仍为 1600×1200 中文七模块 PNG；
- 每张照片只生成 `*_analysis.json` 与 `*_color_report.png`，JPG/JPEG 正式输出为 0。

## 已知限制

极端侧脸、大面积遮挡、过小人脸、极端色光或多个相似候选仍会 fail closed 并显示“样本不足”。安全降级优先于伪造肤色数值。
