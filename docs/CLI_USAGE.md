# CLI 使用说明 V0.12

## 基本命令

```bash
color-palette photo.jpg --output ./result
```

输出：

```text
result/
├── photo_analysis.json
└── photo_color_report.png
```

正式流程不生成 JPG。

## 人脸/肤色后端

```bash
color-palette photo.jpg --face-backend opencv
color-palette photo.jpg --face-backend auto
color-palette photo.jpg --face-backend dlib
color-palette photo.jpg --face-backend none
```

- `opencv`：跨平台默认；
- `auto`：优先 dlib，缺失时 OpenCV；
- `dlib`：请求 dlib，缺失/失败时安全降级；
- `none`：关闭肤色分析，不影响核心色彩分析。

## 环境诊断

```bash
color-palette-doctor
color-palette-doctor --output doctor.json
```

## Golden Dataset

```bash
color-palette-golden ./images \
  --ground-truth ./ground_truth.json \
  --output ./golden_validation_report.json \
  --strict-missing \
  --face-backend opencv
```
