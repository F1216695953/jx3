# Quick Start

## Environment

This project targets a Windows desktop client and Python 3.12. Clone the repository and enter its folder:

```powershell
git clone https://github.com/F1216695953/jx3.git
cd jx3
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe main_debug.py
```

The app matches `JX3ClientX3DX64.exe`. The minimum target resolution is `1280×720` at `16:9`. No window class was supplied, so default matching remains enabled; the template icon is retained.

## Use Daily Checklist

1. Select **Daily Checklist** from the task list.
2. Add one item per row under **Daily Tasks** in task settings.
3. Enter completed item names under **Completed Tasks**; names must match the checklist.
4. Set **Daily Budget Minutes** and **Estimated Minutes Per Task**, then run the task to review progress and estimates.
5. Completion entries clear when the local date changes.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p '*.py'
```

This task only organizes and displays user-entered data. It does not read the game screen or send game input.
