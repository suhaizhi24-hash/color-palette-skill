# Codex 快速体验指南

这份指南面向第一次使用 Python 和命令行的用户。你只需要下载体验包、放入照片，并把准备好的提示词发送给 Codex。

## 1. 下载体验包

打开项目的 GitHub Release 页面，下载：

```text
color-palette-codex-kit-v0.14.1.zip
```

普通用户选择这个 ZIP；熟悉 Python 的用户可以改为下载 `.whl` 文件。

## 2. 解压

### macOS

在“下载”文件夹中双击 ZIP，系统会生成 `color-palette-codex-kit-v0.14.1` 文件夹。

### Windows

右键 ZIP，选择“全部解压”，再打开生成的 `color-palette-codex-kit-v0.14.1` 文件夹。不要直接在压缩包预览窗口中运行。

## 3. 放入照片

把要分析的 JPG、JPEG、PNG 或 WebP 照片复制到解压后的文件夹。体验包中的 `sample/synthetic_sample.png` 是公开合成样片，不是真人照片。

请保留原照片的备份。调色盘只读取照片，不修改照片内容。

## 4. 使用 Codex 打开文件夹

### macOS

在 Codex 中选择刚解压的 `color-palette-codex-kit-v0.14.1` 文件夹作为工作文件夹。

### Windows

在 Codex 中选择“打开文件夹”，定位到解压后的 `color-palette-codex-kit-v0.14.1` 文件夹。

## 5. 复制提示词

打开文件夹中的 `CODEX_PROMPT.txt`，复制全部内容并发送给 Codex。提示词会要求 Codex：

- 检查 Python 3.10 或更高版本；
- 在独立环境中安装体验包内的 Wheel；
- 运行 `color-palette-doctor`；
- 查找用户照片并逐张分析；
- 检查 PNG + JSON 输出且确认没有 JPG/JPEG 正式报告。

不需要 OpenAI API Key，也不需要 GitHub Token。调色盘项目不会把图片上传到项目作者的服务器；核心图片分析在本地执行。

使用 Codex 本身可能受你自己的 Codex/ChatGPT 账户方案和使用额度约束，但本项目不会要求、保存或消耗项目作者的 API Token。

## 6. 查看报告

成功后，每张照片会得到：

```text
*_analysis.json
*_color_report.png
```

正式报告是 1600×1200 的中文 PNG。详细数值保存在 JSON；调色盘不会生成 JPG/JPEG 正式报告，也不会修改原始照片。

## 7. 常见问题

### Codex 提示找不到 Python

请安装 Python 3.10 或更高版本，再让 Codex重新检查。不要让 Codex 修改系统级 Python 配置。

### 系统阻止打开文件或执行程序

确认 ZIP 来自本项目 GitHub Release，并重新解压到普通用户目录。macOS 和 Windows 的安全提示应由你本人确认，不要关闭系统整体安全保护。

### 报告中文显示异常

先查看 `color-palette-doctor` 的字体结果。项目不会携带字体文件；缺少中文字体不会阻止输出，但可读性可能下降。

### 照片会上传吗？

调色盘引擎不会调用 OpenAI API、外部付费模型或项目作者服务器。若你让 Codex 读取本地文件，Codex 自身的数据处理方式以你的产品设置和适用服务条款为准。

### 体验包需要联网吗？

首次安装 Wheel 的依赖时，Python 可能需要访问软件包源。照片分析本身保持 Local-first / Zero-token。
