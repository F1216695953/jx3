# JX3 Unbounded Daily Planner

[English](README_en.md) | [简体中文](README.md)

A Windows desktop daily-planning utility built on [ok-script](https://github.com/ok-oldking/ok-script). Its first task provides an editable checklist, a daily time budget, and manual check-ins; it does not click or control the game.

## Current Configuration

- Client: Windows, `JX3ClientX3DX64.exe`
- Minimum resolution: `1280×720`, aspect ratio `16:9`
- Window class: not configured; default window matching is used
- Icon: template icon retained for now
- Update source: this repository, `https://github.com/F1216695953/jx3`

## Run

```powershell
.\.venv\Scripts\python.exe main_debug.py
```

Run **Daily Checklist** from the task list. Add items under **Daily Tasks** and manually enter completed item names under **Completed Tasks**. The default budget is 60 minutes and the estimate is 10 minutes per task. Check-ins reset each local day.

## Documentation

- [Quick start](docs/en/getting-started.md)
- [App configuration](docs/en/configuration.md)
- [Task guide](docs/en/tasks.md)
- [Packaging and release](docs/en/release.md)
- [简体中文文档](docs/index.md)
