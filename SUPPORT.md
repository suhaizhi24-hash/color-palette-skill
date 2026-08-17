# 支持说明

## 提交安装问题

安装失败时，请先查阅 `README.md` 和 `docs/OFFLINE_INSTALL.md`，并在 Issue 中提供以下已脱敏信息：

- 操作系统、版本和 CPU 架构；
- Python 版本与安装来源；
- `color-palette-skill` 版本和安装方式；
- Wheel 文件名；
- `python -m pip --version` 与 `python -m pip check` 结果；
- `color-palette-doctor` 输出；
- 完整但已脱敏的错误文本，以及能够复现问题的最短命令。

请将命令中的用户名、主目录、照片名称和绝对路径替换为占位符。不要附加虚拟环境、缓存目录或整个项目压缩包。

## 提交 Bug

Bug Issue 建议包含：

- 操作系统、CPU 架构和 Python 版本；
- OpenCV、Pillow 与本项目版本；
- 使用的 CLI 命令和人脸后端；
- 输入格式、像素尺寸，以及是否包含 ICC、EXIF 方向或透明通道；
- 预期结果与实际结果；
- 是否生成了 `{filename}_analysis.json` 和 `{filename}_color_report.png`；
- 是否意外生成 JPG/JPEG；
- 最小复现步骤和已脱敏错误日志。

优先使用 `examples/` 中的公开合成图片复现。若只有真实照片会触发问题，请先尝试制作不含真人和个人数据的合成最小样例。

## 隐私与附件

用户照片默认不得附在公开 Issue、Discussion、Pull Request 或评论中。也不得上传私人 Ground Truth、真实人像验收图、字体、API Key、Token、EXIF GPS 或其他个人数据。

可以提交以下诊断材料，但必须先脱敏：

- `analysis.json`：删除或替换文件名、图片哈希、ICC 名称/哈希、人脸框、取样坐标及其他可关联原图的信息；
- 错误日志：删除用户名、本地绝对路径、环境变量、访问地址、账号标识和凭据；
- `color-palette-doctor` 输出：确认其中不含自定义字体路径或本机身份信息。

无法确认材料是否安全时，请不要公开上传；先按 `SECURITY.md` 中的方式请求私密沟通渠道。

## 输出与联网边界

正式分析应只生成：

```text
{filename}_analysis.json
{filename}_color_report.png
```

核心分析为 Local-first / Zero-token，不依赖 OpenAI API 或其他付费大模型接口，也不需要 API Key。若发现非预期联网、凭据请求、原图被修改或额外生成 JPG/JPEG，请停止处理私人照片，并按安全问题流程报告。
