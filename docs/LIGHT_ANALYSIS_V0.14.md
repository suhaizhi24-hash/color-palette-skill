# Light Analysis Intelligence V0.14

V0.14 将光线构成拆为三个完全独立的判断：Light Source、Light Quality 与 Lighting Ratio。
正式报告仍保持原有卡片布局，只显示中文“光源、光质、光比”。

## 分类契约

| 维度 | 内部枚举 | 正式中文 |
|---|---|---|
| Source | `natural` / `studio` / `flash` / `mixed` / `self_luminous` / `unknown` | 自然光 / 人工棚拍 / 人工闪光 / 混合光 / 自发光 / 暂不判定 |
| Quality | `hard` / `soft` / `not_applicable` / `unknown` | 硬光 / 柔光 / 不适用 / 暂不判定 |
| Ratio | `low` / `medium` / `high` / `not_applicable` / `unknown` | 低 / 中 / 高 / 不适用 / 暂不判定 |

Source 使用场景环境、主体与背景曝光关系、投影与高光结构等证据。综合色温仅记录为辅助
信息，不参与最终决策，因此偏暖不会直接成为人工光，偏冷也不会直接成为自然光。

Quality 只分析主体 ROI 的阴影边缘与半影。窄而清晰的转换、集中高光与明确明暗分离属于
硬光；宽过渡、充分阴影细节与包裹性属于柔光。来源分类不参与光质分类。

Ratio 使用平滑后的局部照明场，在同一主体内比较连贯的受光区与阴影区，并综合区域动态、
空间连贯性与近似 ΔEV。全图 Contrast、白背景、黑衣服或物体固有色不能直接产生高光比。

## 主体 ROI

分析按 Face → Upper Body → Full Body → Main Subject 降级。脸部过小时继续观察上半身、
手臂、衣褶、身体立体面与投影，不立即返回“暂不判定”。

## 自发光

烟花、霓虹、LED、灯具与火焰等以自身发光结构为主体时，Source 为 `self_luminous`，
Quality 与 Ratio 均为 `not_applicable`。这避免把没有“被照亮主体”的画面强行套入人物光比。

## JSON 与报告边界

`analysis.json` 保留结构化枚举、主体 ROI 和内部特征；旧版 `light` 中文对象继续输出作为兼容
适配层。报告渲染优先读取 V0.14 `lighting`，旧 JSON 缺少该字段时回退到 `light`。内部
debug、confidence、evidence、ROI、色温与 EV 均不得进入正式 PNG。

## QA

自动规则测试位于 `tests/lighting/`。A–F 真实 Ground Truth 只登记在
`tests/lighting/lighting_benchmark.json`，真实照片必须保存在公开仓库之外：

```bash
python scripts/run_lighting_benchmark.py --input-dir /path/to/light_qa
```

图片文件名仅用于 runner 将本地 `A`–`F` 资产与登记项配对，分析器从不读取文件名作为分类
证据。未提供真实图片时 runner 明确返回 `pending_external_asset`，不得声称 6/6 通过。

Light Analysis 是根据最终成片可观察到的受光特征进行视觉推断，不保证还原真实摄影现场的
具体灯具型号、数量或精确灯位。
