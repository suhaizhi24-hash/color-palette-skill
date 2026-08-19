# 调色盘 / 色彩卡片 — Codex 快速体验

## 最简单的使用方法

1. 把你的照片放进当前文件夹。
2. 用 Codex 打开当前文件夹。
3. 打开 `CODEX_PROMPT.txt`。
4. 把里面的内容发送给 Codex。
5. 等待分析完成。

完成后查看：

`result/*_color_report.png`

无需 OpenAI API Key。
调色盘分析在本地完成。
原始照片不会被调色盘修改。

如果你会使用终端：

```bash
python -m pip install color_palette_skill-0.14.1-py3-none-any.whl
color-palette photo.jpg --output ./result
```
