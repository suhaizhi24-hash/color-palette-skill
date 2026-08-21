# Style DNA v0.17 Spec（仅规格）

状态：`spec_only_not_implemented`

## 输入

未来接受 10–100 张来源明确、可合法分析的 reference photos。私人图片留在本地，不自动进入 Git、公开 Golden Dataset 或发布资产。

## 流程

```text
references
→ per-image quantitative analysis
→ eligibility / outlier review
→ Median + IQR + Distribution
→ Style DNA
```

## 汇总字段

- L50 Median / IQR；
- Global Contrast Median / IQR；
- Midtone Contrast Median / IQR；
- C50 / C90 Median / IQR；
- Neutral Axis Median / IQR；
- Toe / Shoulder Median / IQR；
- Hue Distribution；
- Scene Palette Distribution；
- Subject/BG 分离分布。

## 治理

- 单张参考图不能定义 Style DNA；
- insufficient 不填 0；
- 输入语境不一致需分组或拒绝聚合；
- Median/IQR 描述样本分布，不证明创作者参数或意图；
- 软件聚合 PASS 不等于摄影规则 VALIDATED；
- 未来实现必须保留异常样本与失败条件。

本轮不实现批处理、聚合引擎或正式 UI。
