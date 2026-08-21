# v0.15.0 Quantitative Color Analysis Core

## 定位

v0.15.0 把分析主链升级为“真实像素数据 → 可比较指标 → 中文专业解释”。描述型结论继续保留，但正式依据来自 ICC 标准化后的 sRGB 显示成片像素。

本轮不修改正式 1600×1200、4:3 中文七模块 Renderer，不重写 Light Analysis、Material FX 或肤色算法，也不实现 Compare Engine 与 Style Batch。

## 数据流

```text
输入照片
→ EXIF Orientation
→ ICC 转换到 sRGB（失败时明确降级）
→ 分析副本缩放与透明像素过滤
→ CIELAB L* / a* / b*
→ Quantitative Metrics
→ quantitative + color_dna
→ 旧字段与正式七模块继续兼容
```

所有测量针对最终显示成片，不等于场景绝对亮度、RAW 传感器值或拍摄参数。

## 新增输出

- `quantitative.luminance`：L* 百分位与固定阈值占比；
- `quantitative.histograms`：64-bin L* 直方图；
- `quantitative.contrast`：全局、中间调、局部与主体局部对比；
- `quantitative.tone_signature`：观察到的影调特征；
- `quantitative.chroma`：C*ab 百分位、分层与 48-bin 直方图；
- `quantitative.hue_distribution`：过滤低色度噪声后的 12 色相扇区；
- `quantitative.neutral_axis`：整体与分影调中性色轴；
- `quantitative.palettes`：中性影调色卡与场景代表色；
- `quantitative.subject_background`：主体/背景的 ΔL、ΔC 与 ΔE00；
- `quantitative.confidence`：复用现有 Light / Material FX 置信度；
- `color_dna`：无审美评分的紧凑定量摘要。

## 数值先于结论

开发摘要先呈现：

```text
L* P50 = 58.40
Global Contrast = 72.10 L*
Midtone Contrast = 28.60 L*
C* P50 = 17.80
Neutral Axis = a* +0.80 / b* +4.20
```

再给出中文解释。正式 PNG 本轮不展示这些字段。

## 原图与隐私

- `render_color_adjustment = false`；
- 不修改输入图片字节；
- 正式输出仍只有 `*_analysis.json` 与 `*_color_report.png`；
- 不生成 JPG/JPEG 报告；
- 不调用 OpenAI、Anthropic、付费模型或网络服务；
- 合成 Golden Dataset 由测试代码构建，私人真实照片不得进入 Git。

## 科学边界

最终 JPEG / PNG 无法唯一反推出 Lightroom / Camera Raw 原始参数。系统不得从单张成片输出“曝光 +0.5”“Highlights -35”“Temperature +600”等不可验证参数。

本轮软件测试证明公式、Schema、确定性与工程契约成立，不把摄影审美规则升级为已完成真实照片实证验证。
