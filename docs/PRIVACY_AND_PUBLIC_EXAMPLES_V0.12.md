# 公开示例与隐私协议 V0.12

## 公开仓库允许的图片

- 只允许程序生成的合成图片；
- 必须位于 `examples/`；
- 必须登记在 `examples/public_examples_manifest.json`；
- 必须标记许可；
- 不得包含 GPS EXIF。

## 私人图片

- 用户上传的照片不得进入公开源码包；
- 私人 Ground Truth 只保存 SHA-256、人工标签和必要提示名；
- 私人验收包与公开 RC 包必须物理分离；
- GitHub CI 不使用私人照片。

## 发布扫描

```bash
python tools/privacy_scan.py . --output privacy_scan.json
```

扫描会检查：

- 图片是否位于允许目录；
- 是否登记许可与 SHA-256；
- 是否含 GPS EXIF；
- 是否存在未登记图片；
- 是否存在字体、私钥、密钥、Token 或环境凭据文件；
- 是否存在高置信度密钥内容或私人素材目录。
