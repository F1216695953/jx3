# 快速开始

## 环境

本项目使用 Windows 桌面客户端和 Python 3.12。克隆仓库并进入目录：

```powershell
git clone https://github.com/F1216695953/jx3.git
cd jx3
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt
```

## 启动

```powershell
.\.venv\Scripts\python.exe main_debug.py
```

应用按 `JX3ClientX3DX64.exe` 匹配游戏窗口。目标分辨率最低为 `1280×720`，比例为 `16:9`。未提供窗口类名，因此配置中保留默认匹配；图标暂时使用模板文件。

## 使用每日清单

1. 在任务列表选择“每日清单”。
2. 在任务设置里逐行填写“日常事项”。
3. 将当天已完成的事项名称填写到“已完成事项”，名称需与清单项目一致。
4. 设置“每日时间预算（分钟）”和“单项预计用时（分钟）”，运行任务查看进度和估算。
5. 完成记录在本地日期变化后自动清空。

## 检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p '*.py'
```

本任务只整理和展示用户填写的数据，不读取游戏画面或发送游戏输入。
