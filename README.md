# 调色盘 / 色彩卡片

Local-first、Zero-token 的中文照片色彩分析工具。项目只分析照片，不自动调色、不套用 LUT、不调用 OpenAI API 或其他付费大模型接口，也不要求 API Key。

## 核心输出

```text
output/
├── photo_analysis.json
└── photo_color_report.png
```

正式报告固定为 4:3、1600×1200，包含七个中文模块：

1. 影调结构
2. 明暗关系
3. 色彩浓度
4. 白平衡&色相
5. 影调色卡
6. 肤色锚点
7. 素材特效&光线构成

## 安装

需要 Python 3.10 或更高版本。

开发安装：

```bash
python -m pip install -e .
```

Wheel 安装：

```bash
python -m pip install color_palette_skill-0.12.0-py3-none-any.whl
```

## 使用

```bash
color-palette photo.jpg --output ./result
```

默认使用 `opencv` 作为跨平台基线：

```bash
color-palette photo.jpg --output ./result --face-backend opencv
```

其他选项：

```text
--face-backend auto     优先使用 dlib，缺失时安全降级
--face-backend dlib     请求 dlib，缺失时安全降级为 OpenCV
--face-backend none     关闭肤色分析，不影响核心色彩分析
--max-side 1600         设置分析副本最长边
```

## 环境诊断

```bash
color-palette-doctor
```

诊断内容包括：

- JPG / PNG / WebP 支持
- LittleCMS / ICC 色彩管理
- 中文字体
- OpenCV / dlib 人脸后端
- Python 与主要依赖版本
- Zero-token 与 PNG-only 输出契约

## 支持格式与原图保真

- JPG / JPEG
- PNG：完全透明像素不参与分析
- WebP
- EXIF Orientation 自动修正
- 嵌入 ICC 时转换至 sRGB 工作空间

允许：方向修正、ICC 标准化、等比缩放、排版裁切。

禁止：曝光、白平衡、色相、饱和度、对比度调整；LUT、滤镜、美颜、锐化、降噪、柔焦、颗粒添加；生成式重绘。

## Golden Dataset

```bash
color-palette-golden ./my-images \
  --ground-truth ./ground_truth.json \
  --output ./golden_validation_report.json \
  --strict-missing
```

私人照片不进入公开仓库；验证按 SHA-256 在本地匹配。

## 公开示例与隐私

公开示例全部由程序生成，登记在：

```text
examples/public_examples_manifest.json
```

发布前运行：

```bash
python tools/privacy_scan.py .
```

## 当前阶段

V0.12.0：首个开源 Beta 候选版本。

仓库配置了 Ubuntu、macOS、Windows 与 Python 3.10、3.12、3.13 的 GitHub Actions 矩阵。具体通过状态以当前 Pull Request 的 Actions 结果为准。

项目采用 [Apache-2.0](LICENSE) 许可证。贡献前请阅读 [贡献指南](CONTRIBUTING.md) 与 [行为准则](CODE_OF_CONDUCT.md)。
