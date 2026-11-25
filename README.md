# 剑网3无界日常助手

[English](README_en.md) | 简体中文

基于 [ok-script](https://github.com/ok-oldking/ok-script) 的 Windows 桌面日常规划工具。当前首个任务提供可编辑清单、每日时间预算和手动打卡；它不会自动点击或操作游戏。

## 当前配置

- 客户端：Windows，`JX3ClientX3DX64.exe`
- 最低分辨率：`1280×720`，宽高比 `16:9`
- 窗口类名：未配置，使用默认窗口匹配
- 图标：暂时保留仓库模板图标
- 更新源：本仓库 `https://github.com/F1216695953/jx3`

## 启动

```powershell
.\.venv\Scripts\python.exe main_debug.py
```

启动后在任务列表运行“每日清单”。在任务设置里填写“日常事项”和“已完成事项”；默认预算为 60 分钟，每项预计 10 分钟。完成状态按本地日期每天重置。

## 文档

- [快速开始](docs/getting-started.md)
- [应用配置](docs/configuration.md)
- [任务说明](docs/tasks.md)
- [打包与发布](docs/release.md)
- [English documentation](docs/en/index.md)
