# v0.15 Synthetic Quantitative Golden Dataset

全部测试样本由 `test_quantitative.py` 在运行时以 NumPy 构建，不包含私人照片或真实 Ground Truth 原图。

| Fixture | 验证关系 |
|---|---|
| L* Gradient | 百分位单调、Histogram 归一、C* 接近 0 |
| Raised Blacks | P1/P5 上升、near-black share 下降 |
| Compressed Highlights | P95/P99 下降、shoulder ratio 下降、headroom 上升 |
| Chroma Blocks | C50/C90/high share 单调 |
| Lab Hue Blocks | 红/黄/绿/青/蓝/洋红固定扇区 |
| Neutral Gray Variants | a*/b* 方向、share、4×4 coverage |
| Scene Palette 60/30/10 | 蓝主色、橙辅助色、红点缀色 |
| Subject/BG | 正负 ΔL 与 ΔE00 |
| Local vs Global | 大面积全局阶跃不被误写为整图局部标准差 |
| Invalid Mask | 完全透明/无效像素不进入百分位和占比 |
| Determinism | 同一输入五次的全部定量指标一致（runtime 除外） |

这些 fixtures 证明公式和软件关系，不冒充真实摄影审美 Ground Truth。
