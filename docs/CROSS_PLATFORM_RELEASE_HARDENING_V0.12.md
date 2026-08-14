# 跨平台发布加固 V0.12

## 支持矩阵

GitHub Actions 配置：

- Ubuntu Latest
- macOS Latest
- Windows Latest
- Python 3.10 / 3.12 / 3.13

每个核心矩阵执行：

1. 只安装隐私扫描必需的外部 Pillow 依赖；
2. 在安装项目、生成样例、构建或发布前扫描 checkout 原貌；
3. 对照人工审核、生成器不可写的独立来源表验证所有公开样例；
4. 安装项目、测试依赖与 CI 系统中文字体；
5. 编译 Python 源码并确认运行时为 OpenCV 4.x；
6. 运行全部单元测试；
7. 校验 JSON Schema 与公开示例；
8. 运行环境诊断；
9. 再次执行隐私、密钥与字体扫描；
10. 验证光线/素材特效公开数据集；
11. 构建并审计 Wheel；
12. 在全新虚拟环境安装 Wheel，运行 PNG + JSON CLI 烟雾测试并确认不生成 JPG/JPEG。

## 字体

- macOS：PingFang SC
- Windows：Microsoft YaHei / SimHei
- Linux：Noto Sans CJK / Source Han Sans
- 允许通过 `COLOR_PALETTE_FONT_REGULAR` 和 `COLOR_PALETTE_FONT_BOLD` 指定本地字体路径
- 仓库不分发字体文件

## 人脸后端

默认：OpenCV。`auto` 与 `dlib` 为可选增强入口；dlib 不可用或运行失败时自动使用 OpenCV。

V0.12.0 的 OpenCV 依赖接受范围为 `>=4.14,<5`；核心 CI 对各平台实际解析到的 OpenCV 4.x 运行完整测试。
OpenCV 5.x 暂未纳入兼容性承诺。

dlib 为可选增强后端，单独设置非阻塞 CI 任务。dlib 缺失或运行失败时不会中断核心色彩分析。

## 当前验证边界

任何单一本地环境的结果都不能替代其他操作系统。Windows、macOS 与 Ubuntu 的“通过”状态必须来自 GitHub Actions 或对应实机。
