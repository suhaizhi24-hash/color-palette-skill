# 离线 / 本地安装说明 V0.12

## Wheel 安装

在已准备依赖的环境中：

```bash
python -m pip install color_palette_skill-0.12.0-py3-none-any.whl --no-deps
```

## 源码安装

```bash
python -m pip install . --no-build-isolation --no-deps
```

## 依赖

核心：

- Pillow
- NumPy
- OpenCV Headless 4.9 至 4.x（V0.12.0 暂不支持 5.x）
- scikit-image
- scikit-learn

可选：

- dlib

## 中文字体

项目不分发字体。正式字体优先级为：

- macOS：PingFang SC
- 跨平台回退：Noto Sans CJK SC / Source Han Sans SC
- Windows 上述字体均缺失时：Microsoft YaHei / SimHei 作为系统兜底

也可设置：

```text
COLOR_PALETTE_FONT_REGULAR=/path/to/font
COLOR_PALETTE_FONT_BOLD=/path/to/font
```

字体完全缺失或指定路径不可用时会使用 Pillow 内置紧急回退，报告仍会输出；诊断信息会记录回退状态。

核心运行不调用 OpenAI API，不消耗作者 Token。
