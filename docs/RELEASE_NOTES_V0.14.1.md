# 调色盘 / 色彩卡片 v0.14.1 Beta

## 普通用户 / Codex 用户

下载：

`color-palette-codex-kit-v0.14.1.zip`

解压后阅读 `START_HERE.md`，把照片放入文件夹，再将 `CODEX_PROMPT.txt` 的内容发送给 Codex。

## Python / CLI 用户

下载：

`color_palette_skill-0.14.1-py3-none-any.whl`

```bash
python -m pip install color_palette_skill-0.14.1-py3-none-any.whl
color-palette-doctor
color-palette photo.jpg --output ./result
```

## 本次更新

- README 首页提供普通用户优先的三分钟快速体验；
- 新增 macOS / Windows Codex 指南与可直接复制的中文提示词；
- 新增固定结构、可审计的 Codex Experience Kit；
- 新增体验包解压、干净安装、中文路径、英文路径和含空格路径回归；
- 分析算法、Light Analysis、Material FX、肤色算法、中文七模块和 PNG-only 协议保持不变。

## 隐私与运行边界

- 调色盘分析保持 Local-first / Zero-token，不要求 OpenAI API Key 或 GitHub Token；
- 正式输出仍只有 `{filename}_analysis.json` 与 `{filename}_color_report.png`；
- Experience Kit 只包含文档、Wheel 与已审核公开合成样片；
- 不包含私人照片、真实 Ground Truth、字体、Token、`.env`、缓存或 Git 仓库。

本版本为 Beta Pre-release，不发布到 PyPI。项目依据 Apache License 2.0 开源。
