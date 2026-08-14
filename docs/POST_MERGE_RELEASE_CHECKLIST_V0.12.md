# v0.12.0 Beta 合并后发布清单

适用范围：PR 合并到 `main` 后，由仓库管理员执行。当前 Pull Request 阶段不得创建正式 Tag、发布 GitHub Release 或跳过 `main` 的验证结果。

## 合并与 main 验证

- [ ] PR 已通过人工审查
- [ ] 最新 commit 的 CI 全部通过
- [ ] main 分支保护已启用
- [ ] PR 使用 Squash and merge 合并
- [ ] 合并后 main CI 通过

## Wheel 与本地门禁

- [ ] 从 main 最新 commit 构建 Wheel
- [ ] Wheel SHA-256 已记录
- [ ] 从 Wheel 进行全新虚拟环境安装
- [ ] CLI 只生成 PNG + JSON
- [ ] 不生成 JPG
- [ ] 隐私扫描通过
- [ ] OpenAI/API 依赖扫描通过

## GitHub Pre-release

- [ ] v0.12.0 GitHub Release 已创建
- [ ] Release 标记为 Pre-release
- [ ] Wheel 已上传为 Release Asset
- [ ] 从 Release 页面重新下载 Wheel 并安装验证

## 发布证据记录

```text
合并后的 main commit：
main CI 链接：
Wheel 文件名：color_palette_skill-0.12.0-py3-none-any.whl
Wheel SHA-256：
全新虚拟环境安装结果：
CLI 烟雾测试结果：
隐私扫描结果：
OpenAI/API 依赖扫描结果：
GitHub Release 链接：
Release Asset 下载回归结果：
执行人：
执行日期：
```
