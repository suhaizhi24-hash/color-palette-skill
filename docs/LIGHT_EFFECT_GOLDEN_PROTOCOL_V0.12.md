# 光线与素材特效 Golden Dataset 协议 V0.12

## 当前状态

P1-C 尚未启用为正式自动判断门禁。本轮先建立独立的公开人工标签数据集与 Schema，避免在证据不足时提前强判。

## 公开合成样本

- 柔光 / 低光比
- 硬光 / 高光比
- 颗粒
- 暗角

## 文件

```text
examples/light_effect_ground_truth.example.json
schemas/light_effect_ground_truth.schema.json
```

## 验证

```bash
python tools/validate_light_effect_dataset.py --root .
```

当前验证内容：

- Schema
- 文件存在
- SHA-256
- 人工标签完整性

当前不验证：

- 自动算法是否识别正确

只有在 Golden Dataset 扩充并经人工验收后，光线/素材特效才可进入正式回归门禁。
