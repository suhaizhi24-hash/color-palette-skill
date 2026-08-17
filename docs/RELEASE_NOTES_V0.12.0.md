# 调色盘 / 色彩卡片 v0.12.0 Beta

## 发布建议

- 建议 Tag：`v0.12.0`
- 发布类型：**Pre-release**
- 本文件只准备发布说明；当前 Pull Request 不创建 Tag，也不发布 GitHub Release。

## 项目定位

调色盘 / 色彩卡片是一款 Local-first / Zero-token 的中文照片色彩分析工具。核心分析、确定性规则、中文文案与报告渲染均在本机完成，不调用 OpenAI API 或其他付费大模型接口，也不要求用户提供 API Key。

项目只分析照片，不修改原图的曝光、白平衡、色相、饱和度、对比度或肤色；不会套用 LUT、滤镜、美颜、锐化、降噪、柔焦，也不会进行生成式重绘。

## 正式输出

每次成功分析固定生成且只生成：

```text
{filename}_analysis.json
{filename}_color_report.png
```

正式视觉报告为 PNG-only，尺寸为 1600×1200、比例为 4:3，不生成 JPG/JPEG。详细分析数值保留在 `analysis.json`。

## 中文七模块

正式报告以 `zh-CN` 为官方语言，并固定按以下顺序包含七个模块：

1. 影调结构
2. 明暗关系
3. 色彩浓度
4. 白平衡&色相
5. 影调色卡
6. 肤色锚点
7. 素材特效&光线构成

单人人像的肤色模块使用苹果肌主锚点与额头副锚点，并显示两张 1:1 原始像素取样截图。多人肤色不会合并；置信度不足时显示“样本不足”。正式报告的原图区域不显示锚点圆圈、数字、人脸框或关键点。

## 支持的输入格式

- JPG / JPEG
- PNG，包括透明 PNG；完全透明像素不参与色彩统计
- 静态 WebP
- EXIF Orientation 方向修正
- 嵌入 ICC 时转换到 sRGB 工作空间；读取失败会明确记录并安全降级

JPG/JPEG 仅属于输入格式，不属于正式报告输出格式。

## 安装

需要 Python 3.10 或更高版本。

从 Release Asset 下载 Wheel 后安装：

```bash
python -m pip install color_palette_skill-0.12.0-py3-none-any.whl
color-palette-doctor
```

从源码安装：

```bash
python -m pip install .
color-palette-doctor
```

项目不分发字体文件。正式字体优先使用 PingFang SC，并依次回退到 Noto Sans CJK SC / Source Han Sans SC 及操作系统中文字体；字体缺失不会阻塞报告输出，`color-palette-doctor` 会报告字体可用性与回退状态。

## CLI 示例

```bash
color-palette photo.jpg --output ./result
```

预期输出：

```text
result/
├── photo_analysis.json
└── photo_color_report.png
```

跨平台默认使用 OpenCV 人脸后端：

```bash
color-palette photo.jpg --output ./result --face-backend opencv
```

## 跨平台 CI

Beta 发布门禁覆盖以下 9 个核心组合：

- Ubuntu：Python 3.10 / 3.12 / 3.13
- macOS：Python 3.10 / 3.12 / 3.13
- Windows：Python 3.10 / 3.12 / 3.13

核心流程包含编译、pytest、JSON Schema、隐私扫描、Wheel 构建与审计、全新虚拟环境安装、CLI PNG + JSON 烟雾测试及 JPG/JPEG 零生成检查。dlib 是可选增强任务，不会因安装失败阻塞核心 CI。最终发布应以目标 commit 对应的 GitHub Actions 结果为准。

## 隐私说明

- 用户照片默认只在本机读取，不上传到远程服务。
- 公开仓库不包含私人照片、私人 Ground Truth、人像验收图或字体文件。
- 公开图片均为程序生成的合成样例，并由独立的人工审核来源表登记；未知图片默认不能通过隐私扫描。
- 不要在公开 Issue 中上传私人照片、API Key、EXIF GPS 或其他个人数据。
- 如需反馈问题，优先提交脱敏后的 `analysis.json`、`color-palette-doctor` 输出和错误日志。

## 已知限制

- v0.12.0 的依赖接受范围为 OpenCV `>=4.14,<5`；核心 CI 验证各平台实际解析到的 4.x，尚未承诺 OpenCV 5.x 兼容性，也未逐一固定测试每个后续 4.x 小版本。
- OpenCV 基础人脸检测可能漏检侧脸、遮挡或复杂多人场景。
- dlib 仅为可选增强，不属于核心运行依赖。
- 在系统完全缺少中文字体时仍会生成报告，但可读性取决于运行环境的可用字体与紧急回退效果。
- 光线与素材特效仍需扩充经人工审核的公开 Golden Dataset，证据不足时不会强行给出确定结论。

## License

本项目使用 [Apache License 2.0](../LICENSE)。
