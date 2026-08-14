# 人脸与肤色后端策略 V0.12

## 目标

核心色彩分析不得因 dlib 缺失而失败。

## 后端

### opencv

- 可移植基线；
- 不依赖 dlib；
- 用于正式 Beta 的可移植基线。
- V0.12.0 的依赖接受范围为 OpenCV `>=4.14,<5`，核心 CI 对实际解析到的 OpenCV 4.x 运行完整测试；
- OpenCV 5.x 暂不属于当前兼容性承诺。

### auto

- dlib 可用时优先 dlib；
- dlib 缺失时使用 OpenCV；
- 分析 JSON 记录实际后端。

### dlib

- 可选增强；
- 若未安装或运行失败，安全降级到 OpenCV；
- `backend_degraded = true`；
- 不影响影调、色彩、白平衡、色卡等核心结果。

### none

- 显式关闭人脸与肤色分析；
- 肤色模块保留并显示中文降级说明；
- 适合服务器、无人像场景或依赖最小化环境。

## 元数据

`analysis.json` 的 `skin` 保存：

- requested_backend
- detector
- available_backends
- backend_degraded
- backend_note

## 发布原则

人脸/肤色属于建议层。跨平台差异必须暴露并记录，但不得阻塞核心色彩规则回归。
