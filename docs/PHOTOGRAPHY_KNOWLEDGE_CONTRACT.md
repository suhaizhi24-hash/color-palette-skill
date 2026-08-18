# Photography Knowledge Consumer Contract

## 定位

摄影知识树负责“知道什么”；Color Palette Skill 负责“如何分析和输出”。中央摄影知识树是 Source of Truth，本仓库是只读 Consumer。

## 中央位置与入口

从本仓库根目录解析时，中央知识根目录为：

```text
../../摄影知识树/
```

读取顺序：

1. `KNOWLEDGE_REGISTRY.md`
2. `color-science/COLOR_SCIENCE_MEMORY.md`（涉及色彩模型、信号链或技术边界时）
3. `color-grading/COLOR_GRADING_MEMORY.md`（涉及调色、LUT、Look、模拟或空间特效时）
4. `governance/EVIDENCE_LEVELS.md`
5. `governance/KNOWLEDGE_LIFECYCLE.md`

自动化检查可通过 `--knowledge-root` 或 `PHOTOGRAPHY_KNOWLEDGE_ROOT` 显式指定中央根目录。路径必须从仓库根目录或显式参数解析，不依赖调用者当前 shell 目录。

## 职责边界

中央知识控制：

- 知识定义与术语边界；
- Evidence level 与 evidence type；
- Knowledge Status；
- Rule ID；
- 科学、工程约束、项目标准和创意 heuristic 的边界。

本 Skill 控制：

- 图片输入与原图保真处理；
- 确定性分析流程；
- 字段组织和中文文案模板；
- 七模块、卡片布局及 PNG/JSON 输出协议；
- 本仓库算法、回归、隐私和发布测试。

Consumer 不得修改中央规则等级。新的运行结果只能作为 Observation 回流，由中央治理流程决定是否升级。

## Rule ID 与 Evidence

适合追踪的内部记录可采用：

```text
Observation: <直接观察到的现象>
Applied Rules: <Rule ID 列表>
Knowledge Status: <中央状态>
Evidence: OBSERVED / INFERRED / MEASURED / CREATIVE / UNKNOWN
```

Rule ID 用于内部推理、debug、research、实验、QA 和知识回流。普通用户的正式 PNG 不批量显示 Rule ID、Evidence 或置信度；如需完整追踪，只在 debug/research 模式或独立 QA 记录中展示。

状态使用规则：

- `FOUNDATIONAL`：稳定技术定义或工具边界；
- `PROJECT_STANDARD`：当前主动采用的工程或工作流标准，不是普遍定律；
- `CREATIVE_HEURISTIC`：创作经验或感知词汇，不得写成科学证明；
- `PROVISIONAL`：待实验验证，不得写成确定事实；
- `VALIDATED`：有中央登记的项目多样本、多条件验证；
- `UNKNOWN`：证据不足，不得猜测补齐。

只有中央状态明确为 `VALIDATED` 时，Consumer 才能声称该规则已经完成项目实证验证。

## 不可访问与降级

中央根目录或任一必需入口不可读取时：

1. 明确报告 `knowledge source unavailable`；
2. 列出不可访问的路径；
3. 不声称读取、应用或验证了中央 Rule ID；
4. 可以继续执行不依赖中央知识的既有本地分析，但必须把知识来源状态标为不可用。

## 禁止复制

禁止把 `COLOR_SCIENCE_MEMORY.md`、`COLOR_GRADING_MEMORY.md` 或其改名副本写入本仓库。合同、测试和报告只能引用中央入口与 Rule ID，不建立第二份永久调色知识。

## Smoke Test

```bash
python tools/photography_knowledge_smoke.py
```

该检查只读中央文件，验证 Consumer 能找到 Registry、解析 Rule ID/Status，并覆盖五个最小边界案例。它不修改中央知识，也不改变分析算法。
