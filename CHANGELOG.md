# Changelog

## 0.13.0

- Material FX 升级为 0..N 多标签结构，正式报告仅显示中文效果名称；
- 新增细/粗颗粒、柔化/高斯模糊、高光扩散、RGB 色彩偏移、画质降低与胶片扫描类视觉效果识别；
- 新增 Flat / Edge / Face / Highlight ROI 策略与竞争解释排除规则；
- 增加干净数码、自然景深、强逆光、高饱和等负向回归；
- 新增真实 Case 001 / Case 002 本地 QA 清单，不提交私人样片或私人 Ground Truth；
- 分析 Schema 升级到 0.13.0，并保留旧 `effects` 读取回退；
- 保持 1600×1200、PNG + JSON、中文七模块、原图不修改与 Zero-token 契约。

## 0.12.0

- 新增 Windows / macOS / Ubuntu CI 矩阵；
- 新增 `color-palette-doctor` 环境诊断命令；
- 增加 EXIF、ICC、透明 PNG、WebP 发布级测试；
- 增加 OpenCV / dlib / none 人脸后端与安全降级；
- 默认人脸后端改为 OpenCV，以提高跨平台可移植性；
- 明确 OpenCV 兼容范围为 `>=4.14,<5`，5.x 待后续兼容验证；
- 新增公开合成示例许可清单与隐私扫描；
- 新增光线/素材特效独立 Golden Dataset Schema 和公开样本；
- 分析 Schema 升级到 0.12.0；
- 官方输出继续保持 PNG + JSON、中文七模块、Zero-token；
- 固定肤色模块使用两张 1:1 原始像素取样截图，低置信度统一显示“样本不足”；
- 明确 JPG/JPEG 仅属于输入格式，正式报告保持 PNG-only；
- 新增 Beta Release Notes、合并后发布清单与真实用户 Beta 测试计划。
