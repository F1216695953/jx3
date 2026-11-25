# 应用配置

## 当前应用设置

`src/config.py` 已设置：

- 窗口标题：剑网3无界日常助手。
- Windows 目标进程：`JX3ClientX3DX64.exe`。
- 最低目标分辨率：`1280×720`，宽高比 `16:9`。
- 窗口类名未提供，未设置 `hwnd_class`，沿用默认匹配。
- 图标未提供，保留 `icons/icon.png` 和 `icons/icon.ico`。
- GitHub 链接指向 `https://github.com/F1216695953/jx3`。

## 更新源

`pyappify.yml` 中的 China 和 Global 两个配置都使用当前 GitHub 仓库作为更新源，适合早期测试。正式发布时如需单独更新仓库，再调整对应 profile 和构建工作流。

MirrorChyan 与 CNB 同步步骤已关闭；当前 Release 直接发布到 GitHub。

## OCR 启动兼容性

OCR 默认使用 ONNX Runtime CPU（`use_openvino=False`、`use_npu=False`）。部分电脑在 OpenVINO 的 `compile_model` 阶段出现 `0xC0000005` 原生访问冲突，普通 Python 异常处理无法捕获，因此默认避开该路径。OCR 模型和任务识别区域保持原设置。ONNX Runtime 及其依赖已加入安装包依赖清单。

这不代表所有 Windows 10 硬件都已验证；安装后仍需在目标电脑验证启动和识别。

## 分辨率

`src/config.py` 的 `supported_resolution` 使用 `16:9` 和 `1280×720` 最低尺寸。窗口类名未知时不要猜值；拿到客户端窗口信息后再补 `hwnd_class`。
