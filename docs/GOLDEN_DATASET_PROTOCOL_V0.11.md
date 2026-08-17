# Golden Dataset 回归协议 V0.11

## 目标

把用户确认的摄影判断转化为可执行回归门禁，防止后续修改规则时发生无意漂移。

## 核心流程

```text
用户确认结果
→ Ground Truth JSON
→ 原图 SHA-256 匹配
→ 本地重新分析
→ 分类与数值容差比较
→ golden_validation_report.json
```

整个过程本地运行，不调用 OpenAI API，不上传图片。

## 公开与私人数据分离

### 公开源码包

可以包含：

- Ground Truth JSON Schema；
- 合成图片示例；
- 验证器代码；
- 单元测试；
- 公开许可样片的标签。

不得包含：

- 用户提供的私人照片；
- 私人报告截图；
- 未授权可识别人物样片；
- 私人 Ground Truth 文件。

### 私人验收包

可以包含：

- 图片 SHA-256；
- 文件提示名；
- 用户确认的分类标签；
- 数值基线与容差；
- 本地回归结果。

私人 Ground Truth 不包含图像字节，仍应避免公开发布。

## 字段级别

### 必须字段

发生差异时回归失败：

- `tone.label`：影调结构；
- `contrast.level`：明暗关系；
- `saturation.level`：色彩饱和度；
- `white_balance.judgement`：白平衡正式结论；
- 指定为 required 的参考数值。

### 建议字段

默认记录但不阻塞核心色彩回归：

- `skin.status`；
- `skin.face_count`；
- 指定为 advisory 的参考数值。

原因：人脸检测结果可能受到操作系统、OpenCV/dlib 版本与可选依赖影响。

## 命令

### 核心色彩回归

```bash
color-palette-golden ./images \
  --ground-truth ./ground_truth.json \
  --output ./golden_validation_report.json \
  --strict-missing
```

### 同时验证人脸/肤色建议字段

```bash
color-palette-golden ./images \
  --ground-truth ./ground_truth.json \
  --output ./golden_validation_report.json \
  --strict-missing \
  --include-advisory
```

## 通过标准

核心色彩回归通过必须满足：

- 至少匹配一个样本；
- required 字段差异为 0；
- 开启 `--strict-missing` 时缺少样本为 0；
- 未知图片不会被误当作已确认样本。
