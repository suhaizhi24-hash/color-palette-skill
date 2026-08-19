# Material FX V0.13 QA Checklist

## 正向分类

- [x] 细颗粒：跨多个低纹理区域持续出现的小尺度随机残差；
- [x] 粗颗粒：较大尺度随机纹理，与 JPEG 块效应分离；
- [x] RGB 色彩偏移：高反差边缘的通道方向性错位；
- [x] 高斯模糊：全局主体边缘扩散且没有保留清晰主体；
- [x] 高光扩散：高光外围连续亮度扩散；
- [x] 多标签结构与正式报告逐行中文标签；
- [ ] Case 001：等待仓库外真实样片；
- [ ] Case 002 / S95-5：等待仓库外真实样片。

## Negative / Boundary

- [x] Clean Digital：显示“未发现明显素材特效”；
- [x] Natural DOF：主体清晰时不得输出全局高斯模糊或柔化；
- [x] Smooth Skin：不得仅凭平滑区域输出模糊；
- [x] Strong Backlight：不得仅凭硬边逆光输出高光扩散；
- [x] High Saturation：不得因颜色浓烈输出 Material FX；
- [x] JPEG / 数字噪点竞争解释不会被直接归为颗粒。

## 输出契约

- [x] 0 个效果时结构合法且文案固定；
- [x] 1 个或多个效果时只消费 `display_name`；
- [x] 正式报告不显示 confidence、evidence、alternatives、ROI 或技术评分；
- [x] 1600×1200 版式位置不变；
- [x] 仍只生成 `*_analysis.json` 和 `*_color_report.png`；
- [x] 输入文件不修改，`render_color_adjustment=false`。
