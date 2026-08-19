# V0.14 Light Analysis 规则

Light Source、Light Quality 与 Lighting Ratio 必须独立判断。综合色温仅记录为低权重辅助信息，不得使用“偏暖即人工光”或“偏冷即自然光”的捷径。

## Source

- `natural`：自然环境与连续空间照明结构占主导，且没有更强的棚拍、直闪、混合光或自发光证据。
- `studio`：受控背景、主体与背景分离、稳定的人工布光结构占主导；不推导柔光。
- `flash`：暗环境中的主体曝光跃升、集中高光与主体/背景分离共同成立。
- `mixed`：闪光或人工主光与有结构的环境光、空间色彩差异共同成立。
- `self_luminous`：画面主体是烟花、霓虹、LED、灯具或火焰等自身发光结构。
- `unknown`：结构证据不足时才使用。

## Quality

只分析主体 ROI 的 Shadow Edge / Penumbra。清晰窄过渡、明暗快速分离为硬光；宽过渡、暗部细节充分且包裹性强为柔光。来源分类不参与光质判断。

## Ratio

只比较同一个主体 ROI 内相互连贯的受光区与阴影区。内部可记录视觉动态范围、区域连贯性与近似 ΔEV，但最终报告只显示低、中、高或不适用。全图黑白跨度、白背景、黑衣服与物体固有色不构成高光比证据。

## ROI fallback

顺序为 Face ROI → Upper Body ROI → Full Body ROI → Main Subject ROI。脸部过小时必须继续检查身体立体面、手臂、衣褶与投影。

## 自发光

确定为自发光时，光质与光比均为 `not_applicable` / “不适用”。

## 两层 QA

- 自动规则测试：仓库内执行，覆盖独立性、Schema、报告字段与旧 JSON 兼容。
- 真实图片 Benchmark：A–F 只登记 Ground Truth；图片由用户从外部本地目录提供。未提供图片时状态必须是 `pending_external_asset`，不得生成合成图冒充或声称 6/6 通过。
