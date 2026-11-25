# Task Guide

## Daily Checklist

The built-in `src/tasks/DailyChecklistTask.py` task only processes user-entered data. It does not read the game screen or send keyboard/mouse input.

Task settings:

- **Daily Tasks**: enter one activity per row.
- **Completed Tasks**: manually enter completed item names; each must exactly match a Daily Tasks entry.
- **Daily Budget Minutes**: 60 minutes by default.
- **Estimated Minutes Per Task**: 10 minutes by default; used to estimate total and remaining time.

Run the task to display completion count, budget and time estimates, plus a **Done/Pending** state for each item. Check-ins reset each local day. Edit the Completed Tasks list in task settings to check items in manually.

## Extend Tasks

The task inherits from `MyBaseTask` and is registered in `onetime_tasks` in `src/config.py`. The repository's `$ok-script-tasks` and `$ok-script-i18n` skills describe task structure and localization.
