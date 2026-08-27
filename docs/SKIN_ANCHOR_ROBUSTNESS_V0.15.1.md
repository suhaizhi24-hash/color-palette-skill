# v0.15.1 Skin Anchor Robustness Calibration

## 范围

v0.15.1 是一个肤色锚点稳健性小版本。它针对“肉眼可见的倾斜、柔焦单人脸在 OpenCV 基线检测中返回 0”这一工程漏检增加安全恢复路径。

本轮不修改 Quantitative Core、Light Analysis、Material FX、Neutral Axis、Scene Palette、正式 Renderer 布局或 PNG-only 协议。

## 检测顺序

1. Pass A 运行原有 OpenCV 正脸/侧脸级联；可选 dlib 的现有路径保持不变。
2. 原始检测框先按 IoU 与近中心关系去重，再作为 `raw_face_candidates` 进入候选质量评估。
3. 候选质量分独立参考检测器置信度、面积、画面中心距离、眼部特征完整度、清晰度、肤色像素支持、正面程度与主体/背景分离。
4. 只有通过上述验证的 `valid_faces` 才参与单人/多人决策；原始候选数量不再直接等于人物数量。
5. 只有 Pass A 没有满足基础尺寸条件的候选时，Pass B 才执行，避免正常基线路径与旋转恢复路径叠加制造误检。
6. Pass B 使用原始灰度、CLAHE 和直方图均衡副本，检查 −15°、−8°、+8°、+15°。
7. 检测框必须通过逆仿射变换回到未旋转工作图，并裁切到图像边界内。
8. 恢复候选还必须通过尺寸、几何比例、肤色像素占比与 L* 合理性检查。
9. `valid_face_count >= 2` 或多个恢复候选确实面积/得分接近时继续 fail closed，禁止合并多人肤色。

## 肤色样本与锚点

- 肤色候选同时参考 YCrCb、CIELAB L*/a*/b*、C*ab、RGB 关系和局部连续性。
- 左右苹果肌分别测量有效肤色占比、L* 中位数、L* MAD/IQR、a*/b* 离散和高光/阴影污染。
- 每侧候选还记录 ROI、L* P25/P50/P75、C* 中位数、头发/唇色污染、局部边缘密度与候选得分。主锚点优先选择连续、低污染的中间调稳定肤色，而不是最低离散但落入头发、耳侧或下颌阴影的样本。
- 当已确认的主脸具有两处可信眼部特征时，只在锚点阶段使用眼线方向建立旋转后的脸颊/额头采样几何；该几何不参与 raw/valid face 判定，也不会改变多人保护。
- 主锚点选择稳定中间调样本，不等价于“选最亮脸颊”。
- 额头副锚点独立评估。主锚点 `valid` 而额头 `low_confidence` / `insufficient` 是合法结果。
- 内部状态为 `valid | low_confidence | insufficient`；正式用户可见报告继续只显示有效数值或“样本不足”。

## Cross-Anchor Coherence Gate

苹果肌与额头之间记录 `ΔL*`、`Δa*`、`Δb*` 和 `ΔE00`，但色差大本身不构成错误：

- 差异在正常范围内时记录 `coherent`；
- 色差较大、主要体现为亮度差且没有头发、唇色、高光热点、高局部边缘或高色度污染时，记录 `illumination_difference`，允许保留真实硬光差异；
- 色差较大、同时存在色度分离和局部污染证据时，记录 `contamination_suspected`，优先检查另一侧脸颊；若没有更可靠替代，主锚点降级为 `low_confidence`，不得继续保持高置信有效状态；
- 任一锚点缺失时记录 `insufficient`。

通用阈值集中定义在 `faces.py`，不得按文件名、SHA-256 或单张真实照片特判。

## `skin.diagnostics`

v0.15.1 分析器新增可选兼容字段 `skin.diagnostics`，包含：

- `face_candidates`
- `raw_face_candidates` / `raw_face_candidate_count`
- `valid_faces` / `valid_face_count`
- `primary_face_id` / `primary_face_score`
- `candidate_scores` / `candidate_rejections`
- `multi_face_block_reason`
- `skin_output_decision`
- `backend`
- `recovery_used`
- `failure_stage` / `failure_reason`
- `primary_anchor_reason` / `secondary_anchor_reason`
- `cheek_candidates`
- `primary_secondary_delta_l` / `primary_secondary_delta_a` / `primary_secondary_delta_b` / `primary_secondary_delta_e00`
- `anchor_coherence`
- `face_detection_ms` / `recovery_detection_ms` / `skin_anchor_ms`

该字段只用于工程审计与本地 QA。正式 1600×1200 PNG 不显示 diagnostics、人脸框、锚点标记或置信度。旧 v0.15.0 JSON 没有该字段仍可通过 0.15.0 Schema 和兼容 Renderer。

## 证据边界

合成回归测试证明的是软件规则、坐标反变换、安全降级与输出契约，不等于普遍的摄影科学 Ground Truth。真实照片及调试 PNG 必须保留在 `qa/skin_v0151_real_review/` 的版本控制之外，仅用于本地 QA，不得提交 Git。

## 已知限制

- 极端侧脸、大面积遮挡、过小人脸或极端色光仍可能降级为样本不足。
- 安全降级优先于为了出数值而放宽到引入非肤色物体。
- dlib 仍是可选增强，不属于核心 CI 必要依赖。
