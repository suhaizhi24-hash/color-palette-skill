# v0.15 Quantitative Metrics Definitions

## 测量语境

所有指标来自 ICC 标准化后的 sRGB 显示成片，并在统一分析尺寸上计算。完全透明像素和非有限 Lab 像素不参与。L* 是 CIELAB Lightness，不是物理 Luminance、编码 Luma、主观 Brightness 或 Lightroom 控件值。

## L* 与固定占比

L* 范围 0–100，输出 P1、P5、P25、P50、P75、P95、P99。

| 字段 | 固定定义 |
|---|---|
| near_black_share | L* < 5 |
| shadow_share | L* < 10 |
| highlight_share | L* > 90 |
| near_white_share | L* > 95 |
| black_clip_share | L* <= 1 |
| white_clip_share | L* >= 99 |

L* Histogram 固定为 `[0, 100]`、64 bins。`normalized` 以有效像素总数归一化，总和约为 1。

## Contrast

- Global Contrast：`P95 - P5`，单位 L*；
- Midtone Contrast：`P75 - P25`，单位 L*；
- Local Contrast：`sqrt(E[L²] - E[L]²)` 的局部标准差图。

局部窗口为短边的约 3%，转为奇数，并限制在 15–61 px。只有整个窗口均为有效像素且不越过图像边界的中心像素参与统计。输出整体 median/P75，并在现有主体 ROI 与安全背景有效时输出各自 median。

Local Contrast 描述局部 L* 波动，不等同于 Clarity、Texture 或锐化参数。

## Observed Tone Signature

- `black_floor_p1 = P1`
- `shadow_floor_p5 = P5`
- `highlight_ceiling_p99 = P99`
- `highlight_headroom = 100 - P95`
- `midtone_spread = P75 - P25`
- `toe_ratio = (P25 - P5) / max(P75 - P25, 1e-6)`
- `shoulder_ratio = (P95 - P75) / max(P75 - P25, 1e-6)`

这些值描述观察到的成片影调分布，不恢复原始 Tone Curve 或调整滑块。

## C*ab

`C*ab = sqrt(a*² + b*²)`。输出 P25/P50/P75/P90。

- Low Chroma：C* < 10；
- Mid Chroma：10 <= C* < 30；
- High Chroma：C* >= 30。

Chroma Histogram 固定为 `[0, 120]`、48 bins；`overflow_share` 单独记录 C* > 120。

## Hue Distribution

只有 `C* >= 10` 且 `5 < L* < 95` 的像素参与。Hue angle 为：

`h° = (degrees(atan2(b*, a*)) + 360) mod 360`

使用固定 12 个 30° 扇区：红、橙、黄、黄绿、绿、青绿、青、蓝青、蓝、蓝紫、洋红、红紫。每个扇区输出面积占比与 Chroma 加权占比。

`hue_concentration` 的唯一定义是主色相扇区的 Chroma 加权占比，不是“色彩丰富度”或审美评分。

## Neutral Axis

候选像素固定为 `C* <= 8` 且 `10 <= L* <= 95`。空间覆盖使用 4×4 grid：有效像素不少于 32 且 neutral share 至少 1% 的格子视为覆盖。

分段：

- Shadow：L* < 35；
- Midtone：35 <= L* < 70；
- Highlight：L* >= 70。

每段至少需要 `max(32, min(512, ceil(valid_count × 0.0005)))` 个像素，否则 `status = insufficient`，a*/b*/C* 中位数为 null。不能用彩色物体补齐中性色。

## Palettes

### Neutral Tone Palette

只从可信 neutral pixels 取样，固定 L* 分段为 0–20、20–40、40–60、60–80、80–100。样本不足保持 null，不用天空、衣服或树叶替代。

### Scene Palette

在 Lab 中使用 fixed seed = 42 的 MiniBatch K-Means，最多采样 30,000 个有效像素，K 最大为 6。ΔE00 < 4 的 cluster 合并。主色为最大面积稳定 cluster；辅助色需与主色 ΔE00 >= 8；点缀色还需面积 0.5%–20%、C* >= 30 且与主色 ΔE00 >= 15。

Scene Palette 只说明物体颜色结构，不参与 Neutral Axis 或白平衡推断。

## Subject / Background

ROI 顺序复用现有 `face → upper_body → full_body → main_subject`。背景从有效像素中排除主体及短边约 3% 的安全 margin。

- `delta_l = Subject L50 - Background L50`
- `delta_c = Subject C50 - Background C50`
- `delta_e00 = CIEDE2000(subject Lab median, background Lab median)`

任一区域不足 64 个可信像素时返回 `status = insufficient` 与 null，不强判。

## Color DNA

Color DNA 是已定义指标的紧凑映射，不含 0–100 审美分数。

| 字段 | 定义 |
|---|---|
| L50 | L* P50 |
| L95_minus_L5 | Global Contrast |
| L75_minus_L25 | Midtone Contrast |
| black_floor_p1 | L* P1 |
| highlight_headroom | 100 - L* P95 |
| C50 / C90 | C*ab P50 / P90 |
| neutral_a / neutral_b | Overall neutral a*/b* median |
| neutral_share / neutral_coverage | neutral pixel share / 4×4 spatial coverage |
| toe_ratio / shoulder_ratio | Observed Tone Signature 对应公式 |
| subject_background_delta_l | Subject L50 - Background L50 |
| subject_background_delta_e00 | 主体与背景 Lab median 的 CIEDE2000 |
| lighting_confidence | source / quality / ratio 三项已有 confidence 的最小值 |
| material_fx_confidence_max | 已检测 Material FX confidence 最大值 |

缺失的 neutral、ROI 或 classifier confidence 必须为 null，不得用 0 伪装测量结果。

## Performance 记录

- `analysis_runtime_ms`：从图片读取到定量结构完成的一次分析 wall-clock 毫秒；
- `quantitative_runtime_ms`：其中 Quantitative Core 的 wall-clock 毫秒；两者仅用于观察，不参与确定性比较；
- `image_max_side`：实际分析数组最大边；
- `valid_pixel_count`：参与测量的有效像素数；
- `scene_palette_sample_count`：聚类实际采样数；
- `local_contrast_kernel_px`：局部对比窗口边长。

不同硬件的 runtime 不能直接作为质量优劣结论。本轮没有跨硬件绝对秒数门槛。

## 不能说明什么

这些指标不能唯一证明相机、光源、RAW 参数、Lightroom/Camera Raw 滑块、LUT、滤镜或创作者意图。Light 与 Material FX 仍是独立确定性分类器，本轮只复制其已有 confidence，不改写其规则。
