# 跨平台发布加固 V0.12

## 支持矩阵

GitHub Actions 配置：

- Ubuntu Latest
- macOS Latest
- Windows Latest
- Python 3.10 / 3.12 / 3.13

每个核心矩阵执行：

1. 安装项目与测试依赖；
2. 生成公开合成样本；
3. 运行全部单元测试；
4. 校验 JSON Schema 与公开示例；
5. 运行环境诊断；
6. 执行隐私、密钥与字体扫描；
7. 验证光线/素材特效公开数据集；
8. 编译 Python 源码；
9. 构建并安装 Wheel；
10. 运行 PNG + JSON CLI 烟雾测试并确认不生成 JPG/JPEG。

## 字体

- macOS：PingFang SC
- Windows：Microsoft YaHei / SimHei
- Linux：Noto Sans CJK / Source Han Sans
- 允许通过 `COLOR_PALETTE_FONT_REGULAR` 和 `COLOR_PALETTE_FONT_BOLD` 指定本地字体路径
- 仓库不分发字体文件

## 人脸后端

默认：OpenCV。`auto` 与 `dlib` 为可选增强入口；dlib 不可用或运行失败时自动使用 OpenCV。

dlib 为可选增强后端，单独设置非阻塞 CI 任务。dlib 缺失或运行失败时不会中断核心色彩分析。

## 当前验证边界

任何单一本地环境的结果都不能替代其他操作系统。Windows、macOS 与 Ubuntu 的“通过”状态必须来自 GitHub Actions 或对应实机。
