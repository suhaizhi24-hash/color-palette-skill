# 格式、EXIF、ICC 与透明像素协议 V0.12

## EXIF Orientation

- 读取输入文件后先执行方向修正；
- 分析与报告均使用修正后的方向；
- `analysis.json` 保存原方向值与是否执行修正。

## ICC

- 检测嵌入 ICC；
- 可读取时通过 LittleCMS 转换至 sRGB；
- 保存 ICC 名称、SHA-256、转换状态与说明；
- ICC 无法读取时安全降级为按 sRGB 解释，并在 JSON 中明确记录；
- 不允许把 ICC 失败静默描述为“成功转换”。

## 透明 PNG

- Alpha = 0 的完全透明像素不参与统计；
- 0 < Alpha < 255 的可见像素参与统计；
- 报告预览可使用棋盘格展示透明区域；
- 棋盘格仅用于显示，不进入色彩分析。

## WebP

- 支持静态 WebP；
- 发布前通过 Pillow WebP 能力检查；
- 当前官方报告输出仍为 PNG。

## 本地 V0.12 验证样本

- EXIF 旋转 JPEG
- 带 sRGB ICC 的 PNG
- 无效 ICC 的 PNG
- 完全透明/不透明混合 PNG
- 部分透明 PNG
- 无损 WebP
