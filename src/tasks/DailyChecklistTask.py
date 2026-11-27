from datetime import date
import re

import numpy as np

from ok import og

from src.tasks.MyBaseTask import MyBaseTask


def normalize_task_names(value):
    """Return non-empty, unique task names while preserving their order."""
    if not isinstance(value, list):
        return []

    names = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def summarize_checklist(tasks, completed, budget_minutes, minutes_per_task):
    tasks = normalize_task_names(tasks)
    completed_names = set(normalize_task_names(completed))
    done = [task for task in tasks if task in completed_names]
    remaining = [task for task in tasks if task not in completed_names]
    budget = max(1, int(budget_minutes))
    per_task = max(1, int(minutes_per_task))
    return {
        "tasks": tasks,
        "done": done,
        "remaining": remaining,
        "budget_minutes": budget,
        "minutes_per_task": per_task,
        "planned_minutes": len(tasks) * per_task,
        "remaining_minutes": len(remaining) * per_task,
    }


class DailyChecklistTask(MyBaseTask):
    """Display a user-maintained plan and process Huaxialou check-in."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Daily Checklist"
        self.description = "Review a daily plan and automatically check Huaxialou sign-in status."
        self.default_config.update({
            "Daily Tasks": [],
            "Completed Tasks": [],
            "Daily Budget Minutes": 60,
            "Estimated Minutes Per Task": 10,
            "启用大侠之路检测": True,
            "窗口前置": True,
            "整合茶馆任务": False,
            "茶馆任务列表": "不选择",
            "接受第一次跑商任务": False,  # 默认关闭跑商接取流程。
            "第一次跑商任务": False,  # 默认关闭跑商交接循环，与接取开关独立。
            "完成后返回角色选择": False,  # 默认不在日常任务结束后离开当前角色。
            "Daxia Road Retry Limit": 5,
            "_progress_date": "",
        })
        self.config_description.update({
            "Daily Tasks": "Enter your daily tasks, one item per row.",
            "Completed Tasks": "Enter completed task names; each must match a Daily Tasks item.",
            "Daily Budget Minutes": "Available time for today's plan, in minutes.",
            "Estimated Minutes Per Task": "Rough time estimate for each task, in minutes.",
            "启用大侠之路检测": "开启后，日常签到完成后执行完整的大侠之路检测和关键词处理流程。",
            "窗口前置": "开启后，执行任务前自动将游戏窗口置于前台；关闭后跳过前置检查。",
            "整合茶馆任务": "总开关：依次执行启用茶馆日常、第一次茶馆，并按任务关键词执行对应茶馆任务。",
            "茶馆任务列表": "选择一个茶馆任务执行；未选择时不执行茶馆任务。整合茶馆任务会临时切换此选择。",
            "接受第一次跑商任务": "开启后，在茶馆流程之后、大侠之路之前，通过活动日历前往据点贸易并接取第一次跑商任务。",  # 说明独立开关及执行顺序。
            "第一次跑商任务": "开启后，在跑商接取流程之后循环执行据点、总管、据点贸易、交任务和接受任务；未发现接受任务时结束。",  # 说明跑商执行开关。
            "完成后返回角色选择": "开启后，检测主界面；未通过时按 Esc 等2秒重试，通过后按 Esc 等2秒并点击指定位置，识别‘角色’后点击，未命中则重新检测主界面。",  # 说明结束后的角色切换流程。
            "Daxia Road Retry Limit": "Maximum number of incomplete Daxia Road entries to process in one run.",
        })
        self.config_type.update({
            "茶馆任务列表": {
                "type": "drop_down",
                "options": [
                    "不选择",
                    "启用茶馆日常",
                    "第一次茶馆",
                    "翻茶叶",
                    "山泉",
                    "客人",
                    "竹笋",
                    "交茶馆",
                    "花茶",
                    "花草",
                    "茶树",
                ],
            },
        })

    @staticmethod
    def _translate(message):
        try:
            return og.app.tr(message)
        except Exception:
            return message

    def _task_enabled(self, name):
        """仅由“茶馆任务列表”下拉选择决定是否执行。"""
        selection = self.config.get("茶馆任务列表")
        if selection is not None:
            return selection == name
        return bool(self.config.get(name, False))

    def run(self):
        self._run_huaxialou_checkin()
        self._run_tea_cake_claim()
        if self.config.get("整合茶馆任务", False):
            self._run_integrated_tea_tasks()
        else:
            selected_task = self.config.get("茶馆任务列表", "不选择")
            task_runners = {
                "启用茶馆日常": self._run_tea_house_daily,
                "第一次茶馆": self._run_first_tea,
                "翻茶叶": self._run_flip_tea_leaves,
                "山泉": self._run_spring_water,
                "客人": self._run_guest,
                "竹笋": self._run_bamboo_shoot,
                "交茶馆": self._run_turn_in_tea_house,
                "花茶": self._run_flower_tea,
                "花草": self._run_flower_grass,
                "茶树": self._run_tea_tree,
            }
            runner = task_runners.get(selected_task)
            if runner is not None:
                runner()
            else:
                self.info_set("茶馆任务状态", "未选择")
        self._first_trade_redirected = False  # 重置本轮接取流程是否已转入跑商循环。
        self._first_trade_finished = False  # 重置本轮是否已识别跑商完成。
        self._run_first_trade_accept()  # 根据独立开关决定是否接取第一次跑商任务。
        if not self._first_trade_redirected and not self._first_trade_finished:  # 已跳转或已完成时不再执行跑商循环。
            self._run_first_trade()  # 根据独立开关执行第一次跑商交接循环。
        self._run_daxia_until_complete()
        self._return_to_character_selection()  # 所有日常流程结束后按开关返回角色选择。

        today = date.today().isoformat()
        if self.config.get("_progress_date") != today:
            self.config["Completed Tasks"] = []
            self.config["_progress_date"] = today

        tasks = normalize_task_names(self.config.get("Daily Tasks", []))
        completed = normalize_task_names(self.config.get("Completed Tasks", []))
        valid_completed = [task for task in completed if task in tasks]
        if valid_completed != completed:
            self.config["Completed Tasks"] = valid_completed

        summary = summarize_checklist(
            tasks,
            valid_completed,
            self.config.get("Daily Budget Minutes", 60),
            self.config.get("Estimated Minutes Per Task", 10),
        )
        done_count = len(summary["done"])
        task_count = len(summary["tasks"])
        self.info_set(self._translate("Daily progress"), f"{done_count}/{task_count}")
        self.info_set(
            self._translate("Time budget / planned"),
            f"{summary['budget_minutes']} / {summary['planned_minutes']} min",
        )
        self.info_set(
            self._translate("Estimated time remaining"),
            f"{summary['remaining_minutes']} min",
        )

        if not summary["tasks"]:
            self.info_set(
                self._translate("Checklist status"),
                self._translate("Add items to Daily Tasks in task settings."),
            )
        else:
            for index, task in enumerate(summary["tasks"], start=1):
                status = "Done" if task in summary["done"] else "Pending"
                self.info_set(f"{index:02d}. {task}", self._translate(status))
        self.log_info(self._translate("Daily checklist updated."))

    def _run_integrated_tea_tasks(self):
        """通过总开关依次接取茶馆任务并按任务关键词分派对应流程。"""
        if not self._ensure_game_foreground():
            self.info_set("整合茶馆任务状态", "游戏窗口未在前台，未执行")
            return False

        self.info_set("整合茶馆任务状态", "执行启用茶馆日常")
        if not self._call_task_with_switch("启用茶馆日常", self._run_tea_house_daily):
            self.info_set("整合茶馆任务状态", "茶馆日常未完成")
            return False

        self.info_set("整合茶馆任务状态", "执行第一次茶馆")
        if not self._call_task_with_switch("第一次茶馆", self._run_first_tea):
            self.info_set("整合茶馆任务状态", "第一次茶馆未完成")
            return False

        task_region = self.box_of_screen(0.042, 0.146, to_x=0.203, to_y=0.258)
        task_keywords = ("茶叶", "山泉", "神秘", "春笋", "赵云", "花材", "茶摊", "花草", "茶树")
        self.info_set("整合茶馆任务状态", "识别后续任务")
        task_words = self.wait_ocr(
            box=task_region,
            match=re.compile(r"(茶叶|山泉|神秘|春笋|赵云|花材|茶摊|花草|茶树)"),
            time_out=2.0,
            raise_if_not_found=False,
        )
        if not task_words:
            self.info_set("整合茶馆任务状态", "未识别到后续任务")
            self.log_warning("第一次茶馆完成后未在指定区域识别到茶叶、山泉、神秘、春笋、赵云、花材、茶摊、花草或茶树。")
            return False

        recognized_texts = [
            str(getattr(word, "name", getattr(word, "text", "")))
            for word in task_words
        ]
        dispatch = {
            "茶叶": ("翻茶叶", self._run_flip_tea_leaves),
            "山泉": ("山泉", self._run_spring_water),
            "神秘": ("客人", self._run_guest),
            "春笋": ("竹笋", self._run_bamboo_shoot),
            "赵云": ("交茶馆", self._run_turn_in_tea_house),
            "花材": ("花茶", self._run_flower_tea),
            "茶摊": ("花茶", self._run_flower_tea),
            "花草": ("花草", self._run_flower_grass),
            "茶树": ("茶树", self._run_tea_tree),
        }
        selected = next(
            (keyword for keyword in task_keywords if any(keyword in text for text in recognized_texts)),
            None,
        )
        if selected is None:
            self.info_set("整合茶馆任务状态", "任务关键词解析失败")
            self.log_warning(f"OCR 已返回结果但未解析到目标关键词：{recognized_texts}")
            return False

        task_name, task_runner = dispatch[selected]
        self.info_set("整合茶馆任务状态", f"执行{task_name}")
        return self._call_task_with_switch(task_name, task_runner)

    def _call_task_with_switch(self, switch_name, task_runner):
        """临时切换茶馆任务下拉项执行流程，完成后恢复原始选择。"""
        missing = object()
        previous = self.config.get("茶馆任务列表", missing)
        self.config["茶馆任务列表"] = switch_name
        try:
            return bool(task_runner())
        finally:
            if previous is missing:
                self.config.pop("茶馆任务列表", None)
            else:
                self.config["茶馆任务列表"] = previous

    def _run_tea_house_daily(self):
        """开启时从主界面进入活动日历、接取任务并执行后续茶馆步骤。"""
        if not self._task_enabled("启用茶馆日常"):
            self.info_set("茶馆日常状态", "已关闭")
            return False

        if not self._ensure_game_foreground():
            self.info_set("茶馆日常状态", "游戏窗口未在前台，未执行")
            return False

        if self._wait_for_main_interface() is None:
            self.info_set("茶馆日常状态", "未检测到主界面")
            self.log_warning("茶馆日常开始前未确认主界面。")
            return False

        self.info_set("茶馆日常状态", "打开活动日历")
        self.send_key_down("shift")
        try:
            self.send_key("c")
        finally:
            self.send_key_up("shift", after_sleep=1.0)

        calendar_box = self.box_of_screen(2 / 1280, 1 / 720, width=192 / 1280, height=53 / 720)
        calendar_title = self.wait_ocr(
            box=calendar_box,
            match=re.compile(r"活动日历"),
            time_out=5.0,
            raise_if_not_found=False,
        )
        if not calendar_title:
            self.info_set("茶馆日常状态", "未识别到活动日历")
            self.log_warning("按 Shift+C 后，未在指定区域识别到“活动日历”。")
            return False

        self.info_set("茶馆日常状态", "已进入活动日历界面")
        calendar_list_box = self.box_of_screen(9 / 1280, 8 / 720, width=413 / 1280, height=711 / 720)
        tea_house_entry = self.wait_ocr(
            box=calendar_list_box,
            match=re.compile(r"江湖茶馆"),
            time_out=5.0,
            raise_if_not_found=False,
        )
        if not tea_house_entry:
            self.info_set("茶馆日常状态", "活动日历中未识别到江湖茶馆")
            self.log_warning("活动日历列表未识别到“江湖茶馆”，停止本次流程。")
            return False

        self.click_box(tea_house_entry, after_sleep=1.0)
        self.log_info("已点击活动日历中的“江湖茶馆”。")
        self.click_relative(1130 / 1280, 603 / 720, after_sleep=1.0)  # 按当前画面尺寸缩放前往按钮坐标，并等待一秒。
        confirm_box = self.box_of_screen(650 / 1280, 541 / 720, width=187 / 1280, height=55 / 720)
        confirm = self.wait_ocr(
            box=confirm_box,
            match=re.compile(r"确认"),
            time_out=5.0,
            raise_if_not_found=False,
        )
        if confirm:
            self.log_info("识别到“确认”，点击文字位置并等待 40 秒。")
            self.click_box(confirm, after_sleep=40.0)
        else:
            self.log_info("未识别到“确认”，等待 40 秒后继续。")
            self.sleep(40.0)
        self.send_key("f", after_sleep=1.0)

        event_box = self.box_of_screen(800 / 1280, 205 / 720, width=410 / 1280, height=80 / 720)
        event_title = self.wait_ocr(
            box=event_box,
            match=re.compile(r"山城一盏听风雨"),
            time_out=8.0,
            raise_if_not_found=False,
        )
        if not event_title:
            self.info_set("茶馆日常状态", "未识别到山城一盏听风雨")
            self.log_warning("按 F 后，未在指定区域识别到“山城一盏听风雨”。")
            return False

        self.click_box(event_title, after_sleep=1.0)
        accept_box = self.box_of_screen(914 / 1280, 645 / 720, width=186 / 1280, height=57 / 720)
        accept_task = self.wait_ocr(
            box=accept_box,
            match=re.compile(r"接受任务"),
            time_out=8.0,
            raise_if_not_found=False,
        )
        if not accept_task:
            self.info_set("茶馆日常状态", "未识别到接受任务")
            self.log_warning("未在指定区域识别到“接受任务”，茶馆任务未接取。")
            return False

        self.click_box(accept_task, after_sleep=1.0)
        self.info_set("茶馆日常状态", "茶馆任务已接取")
        self.log_info("已点击“接受任务”，茶馆日常任务接取完成。")
        return True

    def _run_first_trade_accept(self):  # 独立执行第一次跑商任务接取流程。
        if not self.config.get("接受第一次跑商任务", False):  # 检查跑商独立开关。
            return False  # 关闭时跳过整个接取流程。
        quest_box = self.box_of_screen(0.041, 0.147, to_x=0.197, to_y=0.290)  # 在原第一步前检查已有据点任务。
        existing_quest = self.wait_ocr(box=quest_box, match=re.compile(r"据点"), time_out=2.0, raise_if_not_found=False)  # 最多两秒识别任务追踪中的据点关键词。
        if existing_quest:  # 已有据点任务时直接转入执行流程。
            self.info_set("跑商接取状态", "已识别到据点，转入第一次跑商任务")  # 显示跳转原因。
            self._first_trade_redirected = True  # 标记本轮已分派跑商，防止主流程重复执行。
            return self._run_first_trade(force=True)  # 直接执行跑商，不受执行开关关闭状态阻挡。
        if not self._ensure_game_foreground():  # 复用窗口前置开关及前台确认。
            self.info_set("跑商接取状态", "游戏窗口未在前台，未执行")  # 显示未执行原因。
            return False  # 不满足窗口要求时停止。
        if self._wait_for_main_interface() is None:  # 复用缩放后的R值和角色OCR主界面检测及十次重试。
            self.info_set("跑商接取状态", "未检测到主界面")  # 显示主界面确认失败。
            return False  # 未确认主界面时不发送打开日历的按键。
        self.info_set("跑商接取状态", "打开活动日历")  # 更新当前执行阶段。
        self.send_key_down("shift")  # 按住 Shift 准备组合键。
        try:  # 确保打开日历后释放 Shift。
            self.send_key("c")  # 发送 Shift+C 打开活动日历。
        finally:  # 即使发送失败也释放组合键。
            self.send_key_up("shift", after_sleep=1.0)  # 释放 Shift 并等待一秒。
        calendar_box = self.box_of_screen(0.002, 0.007, to_x=0.148, to_y=0.069)  # 设置活动日历标题区域。
        calendar = self.wait_ocr(box=calendar_box, match=re.compile(r"活动日历"), time_out=5.0, raise_if_not_found=False)  # 最多五秒确认日历标题。
        if not calendar:  # 日历标题未识别到时停止。
            self.info_set("跑商接取状态", "未识别到活动日历")  # 显示失败阶段。
            return False  # 避免在其他界面继续点击。
        self.info_set("跑商接取状态", "已进入活动日历界面")  # 确认进入日历。
        entry_box = self.box_of_screen(0.005, 0.079, to_x=0.322, to_y=0.849)  # 设置据点贸易活动列表区域。
        entry = self.wait_ocr(box=entry_box, match=re.compile(r"据点贸易|已完成"), time_out=5.0, raise_if_not_found=False) or []  # 同时识别活动入口与完成标记，并兼容OCR超时。
        if any("已完成" in str(getattr(word, "name", "")) for word in entry):  # 已完成优先于点击活动入口。
            self._first_trade_finished = True  # 标记本轮无需接取或继续执行跑商。
            self.info_set("跑商接取状态", "跑商已结束")  # 显示跑商已完成。
            self.info_set("第一次跑商状态", "跑商已结束")  # 同步跑商执行状态。
            self.log_info("活动日历识别到‘已完成’，跑商已结束。")  # 记录提前结束原因。
            return True  # 结束跑商流程，继续其他日常任务。
        if not entry:  # 活动入口缺失时停止。
            self.info_set("跑商接取状态", "未识别到据点贸易活动")  # 显示入口检测失败。
            return False  # 不点击前往按钮。
        self.click_box(entry[0], after_sleep=1.0)  # 点击据点贸易文字并等待一秒。
        self.click_relative(1130 / 1280, 603 / 720, after_sleep=2.0)  # 点击随画面尺寸缩放的前往按钮并等待两秒。
        map_box = self.box_of_screen(0.009, 0.008, to_x=0.219, to_y=0.081)  # 设置阵营沙盘标题识别区域。
        faction_map = self.wait_ocr(box=map_box, match=re.compile(r"阵营沙盘"), time_out=5.0, raise_if_not_found=False)  # 最多五秒确认阵营沙盘页面。
        if not faction_map:  # 未确认沙盘时停止本轮接取。
            self.info_set("跑商接取状态", "未识别到阵营沙盘")  # 显示停止原因。
            return False  # 避免点击其他界面的相同位置。
        self.info_set("跑商接取状态", "已进入阵营沙盘")  # 显示沙盘页面确认成功。
        self.click_relative(0.945, 0.128, after_sleep=1.0)  # 点击指定相对位置并等待一秒后检查确认弹窗。
        confirm_box = self.box_of_screen(0.341, 0.672, to_x=0.657, to_y=0.790)  # 设置跑商确认弹窗的新相对识别区域。
        confirm = self.wait_ocr(box=confirm_box, match=re.compile(r"确认"), time_out=5.0, raise_if_not_found=False)  # 最多五秒查找可选确认弹窗。
        if confirm:  # 存在确认弹窗时先确认。
            self.click_box(confirm[0], after_sleep=40.0)  # 点击确认并等待四十秒抵达。
        else:  # 没有弹窗时直接等待。
            self.sleep(40.0)  # 等待四十秒后查找 NPC。
        npc_box = self.box_of_screen(0.668, 0.318, to_x=0.823, to_y=0.615)  # 设置据点总管文字区域。
        npc = self.wait_ocr(box=npc_box, match=re.compile(r"据点|总管"), time_out=8.0, raise_if_not_found=False)  # 最多八秒匹配任意一个 NPC 关键词。
        if not npc:  # 未识别到 NPC 时停止。
            self.info_set("跑商接取状态", "未识别到据点或总管")  # 显示 NPC 识别失败。
            return False  # 不点击后续对话。
        self.click_box(npc[0], after_sleep=1.0)  # 点击首个 NPC 文字框并等待一秒。
        trade_box = self.box_of_screen(0.625, 0.290, to_x=0.951, to_y=0.411)  # 设置据点贸易对话区域。
        trade = self.wait_ocr(box=trade_box, match=re.compile(r"据点贸易"), time_out=8.0, raise_if_not_found=False)  # 最多八秒查找任务对话。
        if not trade:  # 缺少任务对话时停止。
            self.info_set("跑商接取状态", "未识别到据点贸易对话")  # 显示任务对话识别失败。
            return False  # 不点击接受任务。
        self.click_box(trade[0], after_sleep=1.0)  # 点击任务对话并等待一秒。
        accept_box = self.box_of_screen(914 / 1280, 645 / 720, to_x=1100 / 1280, to_y=702 / 720)  # 设置随分辨率缩放的接受任务区域。
        accept = self.wait_ocr(box=accept_box, match=re.compile(r"接受任务"), time_out=8.0, raise_if_not_found=False)  # 最多八秒等待接受按钮。
        if not accept:  # 未识别到接受按钮时停止。
            self.info_set("跑商接取状态", "未识别到接受任务")  # 显示接取未执行。
            return False  # 不将本次流程标记为已接取。
        self.click_box(accept[0], after_sleep=1.0)  # 点击接受任务并等待一秒。
        self.info_set("跑商接取状态", "第一次跑商任务已接取")  # 显示跑商接取流程完成。
        self.log_info("已点击‘接受任务’，第一次跑商任务接取流程完成。")  # 记录流程执行结果。
        return True  # 返回本次接取流程成功。

    def _run_first_trade(self, force=False):  # 执行独立控制或接取流程明确跳转的跑商循环。
        if not force and not self.config.get("第一次跑商任务", False):  # 直接跳转可执行；正常入口仍遵循独立开关。
            return False  # 关闭时不执行任何操作。
        if not self._ensure_game_foreground():  # 按窗口前置配置确认游戏输入目标。
            self.info_set("第一次跑商状态", "游戏窗口未在前台，未执行")  # 显示窗口确认失败。
            return False  # 前置失败时停止。
        quest_box = self.box_of_screen(0.041, 0.147, to_x=0.197, to_y=0.290)  # 第一步任务追踪区域。
        destination_npc_box = self.box_of_screen(0.182, 0.174, to_x=0.823, to_y=0.743)  # 合并目的地和据点总管区域以一次OCR同时检测。
        confirm_box = self.box_of_screen(0.346, 0.678, to_x=0.676, to_y=0.793)  # 识别目的地后检查确认提示的区域。
        npc_box = self.box_of_screen(0.668, 0.318, to_x=0.823, to_y=0.615)  # 目的地点击后刷新画面再查找 NPC 的区域。
        escort_box = self.box_of_screen(0.625, 0.383, to_x=0.945, to_y=0.515)  # 点击 NPC 后检查镖师关键词的区域。
        trade_box = self.box_of_screen(0.621, 0.239, to_x=0.955, to_y=0.386)  # 据点贸易对话区域。
        action_box = self.box_of_screen(0.717, 0.887, to_x=0.877, to_y=0.974)  # 交任务和接受任务按钮区域。
        step = 1  # 从任务追踪识别开始。
        while True:  # 按用户要求循环，直到没有新的接受任务按钮。
            self.info_set("第一次跑商状态", f"执行第{step}步")  # 显示当前流程阶段。
            if step == 1:  # 查找任务追踪中的据点或日常文字。
                words = self.wait_ocr(box=quest_box, match=re.compile(r"据点|日常"), time_out=2.0, raise_if_not_found=False)  # 任意关键词命中即可。
                if words:  # 仅在识别到据点或日常文字时点击。
                    self.click_box(words[0], after_sleep=3.0)  # 点击命中文字并等待三秒。
                step = 2  # 进入目的地和 NPC 合并识别。
            elif step == 2:  # 同一轮同时检测目的地和据点总管关键词。
                combined_words = self.wait_ocr(  # 在合并后的区域同一轮识别目的地和 NPC 关键词。
                    box=destination_npc_box,  # 覆盖目的地列表及 NPC 文字区域。
                    match=re.compile(r"马嵬驿|龙门|洛道|巴陵|南屏山|浩气|据点|总管"),  # 同时匹配目的地和 NPC 名称。
                    time_out=2.0,  # 最多等待两秒获取同一界面上的匹配文字。
                    raise_if_not_found=False,  # 没有匹配内容时返回空结果。
                ) or []  # OCR超时可能返回None，统一为空列表后再遍历。
                destination_pattern = re.compile(r"马嵬驿|龙门|洛道|巴陵|南屏山|浩气")  # 用于从合并结果中筛出目的地。
                npc_pattern = re.compile(r"据点|总管")  # 用于从合并结果中筛出 NPC。
                destinations = [word for word in combined_words if destination_pattern.search(str(getattr(word, "name", "")))]  # 收集命中的目的地文字框。
                npcs = [word for word in combined_words if npc_pattern.search(str(getattr(word, "name", "")))]  # 收集命中的 NPC 文字框。
                if destinations:  # 同帧同时命中时优先处理目的地，因为点击会改变画面。
                    self.click_box(destinations[0], after_sleep=1.0)  # 点击目的地并等待界面刷新。
                    confirm = self.wait_ocr(box=confirm_box, match=re.compile(r"确认"), time_out=5.0, raise_if_not_found=False)  # 最多五秒查找可选确认提示。
                    if confirm:  # 出现确认提示时点击文字。
                        self.click_box(confirm[0])  # 点击 OCR 命中的确认文字。
                    step = 3  # 目的地操作后用新画面单独识别 NPC。
                    continue  # 不使用本次旧画面中可能已失效的 NPC 文字框。
                if not npcs:  # 这一轮既未识别目的地也未识别 NPC。
                    self.sleep(8.0)  # 按要求等待八秒。
                    step = 1  # 回到第一步。
                    continue  # 不执行当前阶段点击。
                words = npcs  # 继续使用同帧识别到的 NPC 文字框。
                self.click_box(words[0], after_sleep=1.0)  # 点击 NPC 文字并等待一秒。
                self.info_set("第一次跑商状态", "检测镖师")  # 显示新增的镖师检测阶段。
                escort = self.wait_ocr(box=escort_box, match=re.compile(r"镖师"), time_out=8.0, raise_if_not_found=False)  # 最多八秒检查镖师关键词。
                if escort:  # 检测到镖师时关闭当前对话并重新寻路。
                    self.click_relative(0.959, 0.044, after_sleep=1.0)  # 点击指定相对坐标并等待一秒。
                    step = 1  # 返回第一步重新识别据点。
                    continue  # 跳过当前轮据点贸易及交接步骤。
                step = 4  # 进入任务对话识别。
            elif step == 3:  # 目的地点击后刷新画面，再查找 NPC。
                words = self.wait_ocr(box=npc_box, match=re.compile(r"据点|总管"), time_out=2.0, raise_if_not_found=False)  # 在新画面中查找 NPC。
                if not words:  # NPC 未出现时返回第一步重新寻路。
                    self.sleep(8.0)  # 按要求等待八秒。
                    step = 1  # 回到第一步。
                    continue  # 不执行当前阶段点击。
                self.click_box(words[0], after_sleep=1.0)  # 点击新画面中 OCR 命中的 NPC。
                self.info_set("第一次跑商状态", "检测镖师")  # 显示镖师检测阶段。
                escort = self.wait_ocr(box=escort_box, match=re.compile(r"镖师"), time_out=8.0, raise_if_not_found=False)  # 最多八秒检查镖师关键词。
                if escort:  # 检测到镖师时关闭当前对话并重新寻路。
                    self.click_relative(0.959, 0.044, after_sleep=1.0)  # 点击指定相对坐标并等待一秒。
                    step = 1  # 返回第一步重新识别据点。
                    continue  # 跳过当前轮据点贸易及交接步骤。
                step = 4  # 进入任务对话识别。
            elif step == 4:  # 查找据点贸易对话。
                words = self.wait_ocr(box=trade_box, match=re.compile(r"据点贸易"), time_out=2.0, raise_if_not_found=False)  # 识别第三步指定区域。
                if not words:  # 未识别到据点贸易时回到第一步重新开始。
                    step = 1  # 返回任务追踪关键词检测。
                    continue  # 重新执行第一步。
                self.click_box(words[0], after_sleep=1.0)  # 点击任务对话并等待一秒。
                step = 5  # 进入交任务阶段。
            elif step == 5:  # 查找交任务按钮。
                words = self.wait_ocr(box=action_box, match=re.compile(r"交任务"), time_out=2.0, raise_if_not_found=False)  # 检测第四步指定区域。
                if not words:  # 没有交任务按钮时重试当前步骤。
                    self.sleep(1.0)  # 等待一秒并刷新画面。
                    continue  # 保持在第四步。
                self.click_box(words[0], after_sleep=1.0)  # 点击交任务并等待一秒。
                step = 6  # 检查是否存在下一次接受任务。
            else:  # 检查是否存在下一次接受任务。
                words = self.wait_ocr(box=action_box, match=re.compile(r"接受任务"), time_out=2.0, raise_if_not_found=False)  # 在同一区域查找新任务按钮。
                if not words:  # 未发现新任务时按要求结束。
                    self.info_set("第一次跑商状态", "跑商任务结束")  # 显示结束状态。
                    self.log_info("未发现‘接受任务’，跑商任务结束。")  # 记录结束原因。
                    return True  # 完成跑商循环。
                self.click_box(words[0], after_sleep=1.0)  # 点击接受任务并等待画面刷新。
                step = 1  # 返回第一步执行下一轮。

    def _run_first_tea(self):
        """由独立开关控制第一次茶馆的 OCR 后续步骤。"""
        if not self._task_enabled("第一次茶馆"):
            self.info_set("第一次茶馆状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("第一次茶馆状态", "游戏窗口未在前台，未执行")
            return False
        self.info_set("第一次茶馆状态", "执行中")
        return self._run_tea_house_followup_steps()

    def _run_tea_house_followup_steps(self):
        """按 OCR 状态循环执行委托、茶馆、品茗和接受步骤。"""
        complete_box = self.box_of_screen(53 / 1280, 100 / 720, width=213 / 1280, height=81 / 720)
        tea_box = self.box_of_screen(867 / 1280, 239 / 720, width=156 / 1280, height=137 / 720)
        tasting_box = self.box_of_screen(0.626, 0.244, to_x=0.948, to_y=0.351)
        accept_box = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("第一次茶馆状态", "识别完成或委托")
            complete_or_commission = self.wait_ocr(
                box=complete_box,
                match=re.compile(r"(完成|委托)"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not complete_or_commission:
                self.log_info("未在指定区域识别到“完成”或“委托”，重新执行第一步。")
                continue

            self.click(150, 147, after_sleep=5.0)
            self.info_set("第一次茶馆状态", "识别茶馆")
            tea_keyword = self.wait_ocr(
                box=tea_box,
                match=re.compile(r"茶馆"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not tea_keyword:
                self.log_info("未识别到“茶馆”，返回第一步重新检测。")
                continue

            self.click_box(tea_keyword, after_sleep=2.0)
            self.info_set("第一次茶馆状态", "识别品茗")
            tasting_keyword = self.wait_ocr(
                box=tasting_box,
                match=re.compile(r"品茗"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not tasting_keyword:
                self.log_info("未识别到“品茗”，返回第一步重新检测。")
                continue

            self.click_box(tasting_keyword, after_sleep=2.0)
            self.info_set("第一次茶馆状态", "识别接受")
            accept_keyword = self.wait_ocr(
                box=accept_box,
                match=re.compile(r"接受"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not accept_keyword:
                self.log_info("未识别到“接受”，返回第一步重新检测。")
                continue

            self.click_box(accept_keyword, after_sleep=2.0)
            self.info_set("第一次茶馆状态", "已完成")
            self.log_info("已依次完成“完成/委托、茶馆、品茗、接受”后续步骤。")
            return True

    def _run_flip_tea_leaves(self):
        """由独立开关控制翻茶叶任务的 OCR 操作。"""
        if not self._task_enabled("翻茶叶"):
            self.info_set("翻茶叶状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("翻茶叶状态", "游戏窗口未在前台，未执行")
            return False

        first_region = self.box_of_screen(0.050, 0.182, to_x=0.152, to_y=0.215)
        second_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        accept_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("翻茶叶状态", "识别茶叶入口")
            tea_leaf_entry = self.wait_ocr(
                box=first_region,
                match=re.compile(r"茶叶"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not tea_leaf_entry:
                continue
            self.click_box(tea_leaf_entry, after_sleep=7.0)

            self.info_set("翻茶叶状态", "识别茶叶选项")
            tea_leaf_option = self.wait_ocr(
                box=second_region,
                match=re.compile(r"茶叶"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not tea_leaf_option:
                self.log_info("未识别到第二步“茶叶”，返回第一步。")
                continue
            self.click_box(tea_leaf_option, after_sleep=5.0)

            while True:
                self.info_set("翻茶叶状态", "识别回复")
                reply_option = self.wait_ocr(
                    box=first_region,
                    match=re.compile(r"回复"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not reply_option:
                    self.log_info("未识别到第三步“回复”，返回第一步。")
                    break
                self.click_box(reply_option, after_sleep=7.0)

                while True:
                    self.info_set("翻茶叶状态", "识别茶馆小童")
                    tea_child = self.wait_ocr(
                        box=second_region,
                        match=re.compile(r"茶馆小童"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not tea_child:
                        self.log_info("未识别到第四步“茶馆小童”，返回第三步。")
                        break
                    self.click_box(tea_child, after_sleep=2.0)

                    while True:
                        self.info_set("翻茶叶状态", "识别品茗")
                        tasting_option = self.wait_ocr(
                            box=tasting_region,
                            match=re.compile(r"品茗"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tasting_option:
                            self.log_info("未识别到第五步“品茗”，返回第四步重新检测茶馆小童。")
                            break
                        self.click_box(tasting_option, after_sleep=2.0)

                        self.info_set("翻茶叶状态", "识别交任务")
                        hand_in_task = self.wait_ocr(
                            box=accept_region,
                            match=re.compile(r"交任务"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not hand_in_task:
                            self.log_info("未识别到第六步“交任务”，返回第五步重新检测品茗。")
                            continue

                        self.click_box(hand_in_task, after_sleep=2.0)
                        self.info_set("翻茶叶状态", "已完成")
                        self.log_info("已完成翻茶叶流程。")
                        return True

    def _run_spring_water(self):
        """由独立开关控制山泉任务的六步操作。"""
        if not self._task_enabled("山泉"):
            self.info_set("山泉状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("山泉状态", "游戏窗口未在前台，未执行")
            return False

        spring_region = self.box_of_screen(0.045, 0.147, to_x=0.201, to_y=0.278)
        number_region = self.box_of_screen(0.777, 0.504, to_x=0.859, to_y=0.644)
        tea_child_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        hand_in_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("山泉状态", "识别泉水")
            spring_water = self.wait_ocr(
                box=spring_region,
                match=re.compile(r"泉水"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not spring_water:
                continue
            self.click_box(spring_water, after_sleep=25.0)

            self.info_set("山泉状态", "识别数字 8")
            number_eight = self.wait_ocr(
                box=number_region,
                match=re.compile(r"8"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not number_eight:
                self.log_info("未识别到第二步“8”，返回第一步。")
                continue
            self.click_box(number_eight, after_sleep=7.0)

            while True:
                self.info_set("山泉状态", "点击第三步入口")
                self.click_relative(0.106, 0.174, after_sleep=23.0)

                while True:
                    self.info_set("山泉状态", "识别茶馆小童")
                    tea_child = self.wait_ocr(
                        box=tea_child_region,
                        match=re.compile(r"茶馆小童"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not tea_child:
                        self.log_info("未识别到第四步“茶馆小童”，返回第三步。")
                        break
                    self.click_box(tea_child, after_sleep=2.0)

                    while True:
                        self.info_set("山泉状态", "识别品茗")
                        tasting_option = self.wait_ocr(
                            box=tasting_region,
                            match=re.compile(r"品茗"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tasting_option:
                            self.log_info("未识别到第五步“品茗”，返回第四步。")
                            break
                        self.click_box(tasting_option, after_sleep=2.0)

                        self.info_set("山泉状态", "识别交任务")
                        hand_in_task = self.wait_ocr(
                            box=hand_in_region,
                            match=re.compile(r"交任务"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not hand_in_task:
                            self.log_info("未识别到第六步“交任务”，返回第五步。")
                            continue

                        self.click_box(hand_in_task, after_sleep=2.0)
                        self.info_set("山泉状态", "已完成")
                        self.log_info("已完成山泉流程。")
                        return True

    def _run_guest(self):
        """由独立开关控制客人任务的七步 OCR 操作。"""
        if not self._task_enabled("客人"):
            self.info_set("客人状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("客人状态", "游戏窗口未在前台，未执行")
            return False

        first_region = self.box_of_screen(0.045, 0.147, to_x=0.201, to_y=0.278)
        second_region = self.box_of_screen(0.673, 0.331, to_x=0.820, to_y=0.658)
        guest_region = self.box_of_screen(0.636, 0.589, to_x=0.925, to_y=0.703)
        reply_region = self.box_of_screen(0.050, 0.182, to_x=0.152, to_y=0.215)
        tea_child_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        hand_in_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("客人状态", "识别神秘入口")
            mysterious_entry = self.wait_ocr(
                box=first_region,
                match=re.compile(r"神秘"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not mysterious_entry:
                continue
            self.click_box(mysterious_entry, after_sleep=7.0)

            self.info_set("客人状态", "识别神秘选项")
            mysterious_option = self.wait_ocr(
                box=second_region,
                match=re.compile(r"神秘"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not mysterious_option:
                self.log_info("未识别到第二步“神秘”，返回第一步。")
                continue
            self.click_box(mysterious_option, after_sleep=5.0)

            while True:
                self.info_set("客人状态", "识别客人")
                guest_option = self.wait_ocr(
                    box=guest_region,
                    match=re.compile(r"客人"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not guest_option:
                    self.log_info("未识别到第三步“客人”，返回第一步。")
                    break
                self.click_box(guest_option, after_sleep=2.0)
                self.click_relative(0.614, 0.817)

                while True:
                    self.info_set("客人状态", "识别回复")
                    reply_option = self.wait_ocr(
                        box=reply_region,
                        match=re.compile(r"回复"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not reply_option:
                        self.log_info("未识别到第四步“回复”，返回第一步。")
                        break
                    self.click_box(reply_option, after_sleep=7.0)

                    while True:
                        self.info_set("客人状态", "识别茶馆小童")
                        tea_child = self.wait_ocr(
                            box=tea_child_region,
                            match=re.compile(r"茶馆小童"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tea_child:
                            self.log_info("未识别到第五步“茶馆小童”，返回第四步。")
                            break
                        self.click_box(tea_child, after_sleep=2.0)

                        while True:
                            self.info_set("客人状态", "识别品茗")
                            tasting_option = self.wait_ocr(
                                box=tasting_region,
                                match=re.compile(r"品茗"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not tasting_option:
                                self.log_info("未识别到第六步“品茗”，返回第五步。")
                                break
                            self.click_box(tasting_option, after_sleep=2.0)

                            self.info_set("客人状态", "识别交任务")
                            hand_in_task = self.wait_ocr(
                                box=hand_in_region,
                                match=re.compile(r"交任务"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not hand_in_task:
                                self.log_info("未识别到第七步“交任务”，返回第六步。")
                                continue

                            self.click_box(hand_in_task, after_sleep=2.0)
                            self.info_set("客人状态", "已完成")
                            self.log_info("已完成客人流程。")
                            return True

    def _run_bamboo_shoot(self):
        """由独立开关控制竹笋任务的六步操作。"""
        if not self._task_enabled("竹笋"):
            self.info_set("竹笋状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("竹笋状态", "游戏窗口未在前台，未执行")
            return False

        first_region = self.box_of_screen(0.045, 0.147, to_x=0.201, to_y=0.278)
        second_region = self.box_of_screen(0.673, 0.332, to_x=0.823, to_y=0.567)
        reply_region = self.box_of_screen(0.046, 0.146, to_x=0.191, to_y=0.231)
        tea_child_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        hand_in_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("竹笋状态", "识别春笋入口")
            spring_shoot_entry = self.wait_ocr(
                box=first_region,
                match=re.compile(r"春笋"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not spring_shoot_entry:
                continue
            self.click_box(spring_shoot_entry, after_sleep=25.0)

            while True:
                self.info_set("竹笋状态", "识别春笋选项")
                spring_shoot_option = self.wait_ocr(
                    box=second_region,
                    match=re.compile(r"春笋"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not spring_shoot_option:
                    self.log_info("未识别到第二步“春笋”，等待 2 秒后重试第二步。")
                    self.sleep(2.0)
                    continue
                self.click_box(spring_shoot_option, after_sleep=5.0)

                while True:
                    self.info_set("竹笋状态", "识别回复")
                    reply_option = self.wait_ocr(
                        box=reply_region,
                        match=re.compile(r"回复"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not reply_option:
                        self.log_info("未识别到第三步“回复”，返回第二步。")
                        break
                    self.click_box(reply_option, after_sleep=25.0)

                    while True:
                        self.info_set("竹笋状态", "识别茶馆小童")
                        tea_child = self.wait_ocr(
                            box=tea_child_region,
                            match=re.compile(r"茶馆小童"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tea_child:
                            self.log_info("未识别到第四步“茶馆小童”，返回第三步。")
                            break
                        self.click_box(tea_child, after_sleep=2.0)

                        while True:
                            self.info_set("竹笋状态", "识别品茗")
                            tasting_option = self.wait_ocr(
                                box=tasting_region,
                                match=re.compile(r"品茗"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not tasting_option:
                                self.log_info("未识别到第五步“品茗”，返回第四步。")
                                break
                            self.click_box(tasting_option, after_sleep=2.0)

                            self.info_set("竹笋状态", "识别交任务")
                            hand_in_task = self.wait_ocr(
                                box=hand_in_region,
                                match=re.compile(r"交任务"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not hand_in_task:
                                self.log_info("未识别到第六步“交任务”，返回第五步。")
                                continue

                            self.click_box(hand_in_task, after_sleep=2.0)
                            self.info_set("竹笋状态", "已完成")
                            self.log_info("已完成竹笋流程。")
                            return True

    def _run_flower_tea(self):
        """由独立开关控制花茶任务的六步操作。"""
        if not self._task_enabled("花茶"):
            self.info_set("花茶状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("花茶状态", "游戏窗口未在前台，未执行")
            return False

        flower_region = self.box_of_screen(0.045, 0.149, to_x=0.196, to_y=0.258)
        operation_region = self.box_of_screen(0.677, 0.332, to_x=0.809, to_y=0.490)
        reply_region = self.box_of_screen(0.050, 0.182, to_x=0.152, to_y=0.215)
        tea_child_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        hand_in_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("花茶状态", "识别花材")
            flower_material = self.wait_ocr(
                box=flower_region,
                match=re.compile(r"花材"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not flower_material:
                continue
            self.click_box(flower_material, after_sleep=7.0)
            operation = self.wait_ocr(
                box=operation_region,
                match=re.compile(r"操作"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not operation:
                self.log_info("花材后未识别到“操作”，返回第一步。")
                continue
            self.click_box(operation, after_sleep=2.0)

            self.info_set("花茶状态", "识别茶摊")
            tea_stall = self.wait_ocr(
                box=flower_region,
                match=re.compile(r"茶摊"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not tea_stall:
                self.log_info("未识别到第二步“茶摊”，返回第一步。")
                continue
            self.click_box(tea_stall, after_sleep=7.0)
            operation = self.wait_ocr(
                box=operation_region,
                match=re.compile(r"操作"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not operation:
                self.log_info("茶摊后未识别到“操作”，返回第一步。")
                continue
            self.click_box(operation, after_sleep=2.0)

            while True:
                self.info_set("花茶状态", "识别回复")
                reply_option = self.wait_ocr(
                    box=reply_region,
                    match=re.compile(r"回复"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not reply_option:
                    self.log_info("未识别到第三步“回复”，返回第一步。")
                    break
                self.click_box(reply_option, after_sleep=7.0)

                while True:
                    self.info_set("花茶状态", "识别茶馆小童")
                    tea_child = self.wait_ocr(
                        box=tea_child_region,
                        match=re.compile(r"茶馆小童"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not tea_child:
                        self.log_info("未识别到第四步“茶馆小童”，返回第三步。")
                        break
                    self.click_box(tea_child, after_sleep=2.0)

                    while True:
                        self.info_set("花茶状态", "识别品茗")
                        tasting_option = self.wait_ocr(
                            box=tasting_region,
                            match=re.compile(r"品茗"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tasting_option:
                            self.log_info("未识别到第五步“品茗”，返回第四步。")
                            break
                        self.click_box(tasting_option, after_sleep=2.0)

                        self.info_set("花茶状态", "识别交任务")
                        hand_in_task = self.wait_ocr(
                            box=hand_in_region,
                            match=re.compile(r"交任务"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not hand_in_task:
                            self.log_info("未识别到第六步“交任务”，返回第五步。")
                            continue

                        self.click_box(hand_in_task, after_sleep=2.0)
                        self.info_set("花茶状态", "已完成")
                        self.log_info("已完成花茶流程。")
                        return True

    def _run_flower_grass(self):
        """由独立开关控制花草任务的六步 OCR 操作。"""
        if not self._task_enabled("花草"):
            self.info_set("花草状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("花草状态", "游戏窗口未在前台，未执行")
            return False

        first_region = self.box_of_screen(0.045, 0.147, to_x=0.201, to_y=0.278)
        second_region = self.box_of_screen(0.673, 0.332, to_x=0.823, to_y=0.567)
        reply_region = self.box_of_screen(0.046, 0.146, to_x=0.191, to_y=0.231)
        tea_child_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        hand_in_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("花草状态", "识别花草入口")
            flower_grass_entry = self.wait_ocr(
                box=first_region,
                match=re.compile(r"花草"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not flower_grass_entry:
                continue
            self.click_box(flower_grass_entry, after_sleep=40.0)

            while True:
                self.info_set("花草状态", "识别花草选项")
                flower_grass_option = self.wait_ocr(
                    box=second_region,
                    match=re.compile(r"花草"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not flower_grass_option:
                    self.log_info("未识别到第二步“花草”，等待 2 秒后重试第二步。")
                    self.sleep(2.0)
                    continue
                self.click_box(flower_grass_option, after_sleep=5.0)

                while True:
                    self.info_set("花草状态", "识别回复")
                    reply_option = self.wait_ocr(
                        box=reply_region,
                        match=re.compile(r"回复"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not reply_option:
                        self.log_info("未识别到第三步“回复”，返回第二步。")
                        break
                    self.click_box(reply_option, after_sleep=40.0)

                    while True:
                        self.info_set("花草状态", "识别茶馆小童")
                        tea_child = self.wait_ocr(
                            box=tea_child_region,
                            match=re.compile(r"茶馆小童"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tea_child:
                            self.log_info("未识别到第四步“茶馆小童”，返回第三步。")
                            break
                        self.click_box(tea_child, after_sleep=2.0)

                        while True:
                            self.info_set("花草状态", "识别品茗")
                            tasting_option = self.wait_ocr(
                                box=tasting_region,
                                match=re.compile(r"品茗"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not tasting_option:
                                self.log_info("未识别到第五步“品茗”，返回第四步。")
                                break
                            self.click_box(tasting_option, after_sleep=2.0)

                            self.info_set("花草状态", "识别交任务")
                            hand_in_task = self.wait_ocr(
                                box=hand_in_region,
                                match=re.compile(r"交任务"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not hand_in_task:
                                self.log_info("未识别到第六步“交任务”，返回第五步。")
                                continue

                            self.click_box(hand_in_task, after_sleep=2.0)
                            self.info_set("花草状态", "已完成")
                            self.log_info("已完成花草流程。")
                            return True

    def _run_turn_in_tea_house(self):
        """由独立开关控制交茶馆任务的四步 OCR 操作。"""
        if not self._task_enabled("交茶馆"):
            self.info_set("交茶馆状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("交茶馆状态", "游戏窗口未在前台，未执行")
            return False

        first_region = self.box_of_screen(0.045, 0.144, to_x=0.171, to_y=0.236)
        second_region = self.box_of_screen(0.673, 0.339, to_x=0.824, to_y=0.585)
        mountain_region = self.box_of_screen(0.623, 0.272, to_x=0.957, to_y=0.418)
        hand_in_region = self.box_of_screen(0.714, 0.879, to_x=0.864, to_y=0.976)

        while True:
            self.info_set("交茶馆状态", "识别赵云入口")
            zhao_yun_entry = self.wait_ocr(
                box=first_region,
                match=re.compile(r"赵云"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not zhao_yun_entry:
                continue
            self.click_box(zhao_yun_entry, after_sleep=5.0)

            self.info_set("交茶馆状态", "识别赵云选项")
            zhao_yun_option = self.wait_ocr(
                box=second_region,
                match=re.compile(r"赵云"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not zhao_yun_option:
                self.log_info("未识别到第二步“赵云”，返回第一步。")
                continue
            self.click_box(zhao_yun_option, after_sleep=2.0)

            while True:
                self.info_set("交茶馆状态", "识别山城")
                mountain_option = self.wait_ocr(
                    box=mountain_region,
                    match=re.compile(r"山城"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not mountain_option:
                    self.log_info("未识别到第三步“山城”，返回第二步。")
                    break
                self.click_box(mountain_option, after_sleep=2.0)

                self.info_set("交茶馆状态", "识别交任务")
                hand_in_task = self.wait_ocr(
                    box=hand_in_region,
                    match=re.compile(r"交任务"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not hand_in_task:
                    self.log_info("未识别到第四步“交任务”，返回第三步。")
                    continue

                self.click_box(hand_in_task)
                self.info_set("交茶馆状态", "已完成")
                self.log_info("已完成交茶馆流程。")
                return True

    def _run_tea_tree(self):
        """由独立开关控制茶树任务的七步 OCR 和按键操作。"""
        if not self._task_enabled("茶树"):
            self.info_set("茶树状态", "已关闭")
            return False
        if not self._ensure_game_foreground():
            self.info_set("茶树状态", "游戏窗口未在前台，未执行")
            return False

        first_region = self.box_of_screen(0.045, 0.147, to_x=0.201, to_y=0.278)
        operation_region = self.box_of_screen(0.673, 0.332, to_x=0.823, to_y=0.567)
        reply_region = self.box_of_screen(0.046, 0.146, to_x=0.191, to_y=0.231)
        tea_child_region = self.box_of_screen(0.677, 0.332, to_x=0.823, to_y=0.621)
        tasting_region = self.box_of_screen(0.624, 0.249, to_x=0.956, to_y=0.361)
        hand_in_region = self.box_of_screen(0.712, 0.893, to_x=0.861, to_y=0.975)

        while True:
            self.info_set("茶树状态", "识别茶树入口")
            tea_tree_entry = self.wait_ocr(
                box=first_region,
                match=re.compile(r"茶树"),
                time_out=2.0,
                raise_if_not_found=False,
            )
            if not tea_tree_entry:
                continue
            self.click_box(tea_tree_entry, after_sleep=40.0)

            while True:
                self.info_set("茶树状态", "识别操作")
                operation = self.wait_ocr(
                    box=operation_region,
                    match=re.compile(r"操作"),
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not operation:
                    self.log_info("未识别到第二步“操作”，等待 2 秒后重试第二步。")
                    self.sleep(2.0)
                    continue
                self.click_box(operation, after_sleep=5.0)

                while True:
                    self.info_set("茶树状态", "每隔 1 秒按键 1，持续 30 秒")
                    for _ in range(30):
                        self.send_key("1", after_sleep=1.0)

                    self.info_set("茶树状态", "识别回复")
                    reply = self.wait_ocr(
                        box=reply_region,
                        match=re.compile(r"回复"),
                        time_out=2.0,
                        raise_if_not_found=False,
                    )
                    if not reply:
                        self.log_info("未识别到第四步“回复”，返回第三步重新按键 1。")
                        continue
                    self.click_box(reply, after_sleep=40.0)

                    while True:
                        self.info_set("茶树状态", "识别茶馆小童")
                        tea_child = self.wait_ocr(
                            box=tea_child_region,
                            match=re.compile(r"茶馆小童"),
                            time_out=2.0,
                            raise_if_not_found=False,
                        )
                        if not tea_child:
                            self.log_info("未识别到第五步“茶馆小童”，返回第四步。")
                            break
                        self.click_box(tea_child, after_sleep=2.0)

                        while True:
                            self.info_set("茶树状态", "识别品茗")
                            tasting = self.wait_ocr(
                                box=tasting_region,
                                match=re.compile(r"品茗"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not tasting:
                                self.log_info("未识别到第六步“品茗”，返回第五步。")
                                break
                            self.click_box(tasting, after_sleep=2.0)

                            self.info_set("茶树状态", "识别交任务")
                            hand_in = self.wait_ocr(
                                box=hand_in_region,
                                match=re.compile(r"交任务"),
                                time_out=2.0,
                                raise_if_not_found=False,
                            )
                            if not hand_in:
                                self.log_info("未识别到第七步“交任务”，重试第七步。")
                                continue
                            self.click_box(hand_in, after_sleep=2.0)
                            self.info_set("茶树状态", "已完成")
                            self.log_info("已完成茶树流程。")
                            return True

    def _run_daxia_until_complete(self):
        """每轮回到主界面后重新打开大侠之路，直到识别为完成。"""
        if not self.config.get("启用大侠之路检测", True):
            return self._check_daxia_road_progress()

        while True:
            if not self._ensure_game_foreground():
                self.info_set("大侠之路状态", "游戏窗口未在前台，暂停大侠之路检测")
                return False
            if self._check_daxia_road_progress():
                return True
            if self._wait_for_main_interface() is None:
                self.info_set("大侠之路状态", "尚未确认主界面，继续尝试返回并检测")
                self.log_warning("未确认主界面；稍后再次尝试返回主界面，再继续大侠之路检测。")
            else:
                self.log_info("大侠之路尚未完成，已返回主界面；稍后重新打开并继续检测。")
            self.sleep(1.0)

    def _run_huaxialou_checkin(self):
        """按 N 打开花萼楼，再根据指定区域的红色占比执行签到。"""
        if not self._ensure_game_foreground():
            self.info_set("日常签到状态", "游戏窗口未在前台，未执行签到检查")
            return False

        main_frame = self._wait_for_main_interface()
        if main_frame is None:
            self.info_set("主界面状态", "不在主界面")
            self.log_info("主界面检测失败：缩放后的(90,37)处R值未超过160，或角色区域识别到‘角色’。")
            return False
        self.info_set("主界面状态", "在主界面")
        self.log_info("主界面检测通过：缩放后的(90,37)处R值超过160，且角色区域未识别到‘角色’。")

        self.log_info("按 N 打开花萼楼界面。")
        self.send_key("n", after_sleep=1.0)
        frame = self.next_frame()
        if frame is None:
            self.info_set("日常签到状态", "无法读取签到区域")
            self.log_warning("未获取到花萼楼页面截图，按 Esc 返回主界面。")
            self.send_key("esc", after_sleep=1.0)
            return False

        red_value = self._get_check_in_red_value(frame)
        if red_value > 220:
            self.info_set("日常签到状态", "日常签到未完成")
            self.log_info(f"日常签到未完成，坐标 (246,123) 的 R 值为 {red_value}，点击屏幕正中间。")
            self.click_relative(0.5, 0.5, after_sleep=1.0)
            self.sleep(5.0)
            self.log_info("等待 5 秒后点击屏幕中间下方 3/4 位置。")
            self.click_relative(0.5, 0.75, after_sleep=1.0)
            frame = self.next_frame()
            if frame is None:
                self.info_set("日常签到状态", "无法读取签到状态")
                self.log_warning("第二次签到状态识别未获取到画面。")
                return True
            red_value = self._get_check_in_red_value(frame)
            if red_value > 220:
                self.info_set("日常签到状态", "日常签到未完成")
                self.log_info(f"再次识别仍未完成，坐标 (246,123) 的 R 值为 {red_value}。")
                return True

        self.info_set("日常签到状态", "日常签到已完成")
        self.log_info(f"日常签到已完成，坐标 (246,123) 的 R 值为 {red_value}，按 Esc 返回主界面。")
        self.send_key("esc", after_sleep=1.0)
        return False

    def _run_tea_cake_claim(self):
        """检测茶饼领取状态，领取后返回主界面再继续后续任务。"""
        if not self._ensure_game_foreground():
            self.info_set("茶饼状态", "游戏窗口未在前台，未执行茶饼检查")
            return False

        frame = self._wait_for_main_interface()
        if frame is None:
            self.info_set("茶饼状态", "不在主界面")
            self.log_info("茶饼流程开始时未通过主界面颜色及OCR检测。")
            return False

        self.send_key("esc", after_sleep=0.5)
        frame = self.next_frame()
        tea_rgb = self._sample_pixel_rgb(frame, 1173, 261)
        if tea_rgb != (229, 94, 58):
            self.info_set("茶饼状态", "茶饼已领")
            self.log_info(f"(1173,261) RGB={tea_rgb}，判定茶饼已领取。")
            self.send_key("esc", after_sleep=0.5)
            self._return_to_main_after_esc()
            return False

        self.info_set("茶饼状态", "茶饼未领")
        self.log_info("检测到茶饼未领取，点击 (1124,288)。")
        self.click(1124, 288, after_sleep=2.0)

        hero_box = self.box_of_screen(4 / 1280, 2 / 720, width=206 / 1280, height=50 / 720)
        hero = self.wait_ocr(
            box=hero_box,
            match=re.compile(r"红尘侠影"),
            time_out=3.0,
            raise_if_not_found=False,
        )
        if hero:
            claim_box = self.box_of_screen(1024 / 1280, 638 / 720, width=193 / 1280, height=63 / 720)
            claim = self.wait_ocr(
                box=claim_box,
                match=re.compile(r"领取"),
                time_out=3.0,
                raise_if_not_found=False,
            )
            if claim:
                self.log_info("识别到“领取”，点击领取区域中心 (1121,670)。")
                self.click(1121, 670, after_sleep=0.5)

        self.send_key("esc", after_sleep=0.5)
        if not self._return_to_main_after_esc():
            self.send_key("esc", after_sleep=0.5)
            self._return_to_main_after_esc()
        return True

    def _return_to_main_after_esc(self):
        """按主界面规则轮询确认，失败时发送 Esc 后继续检测。"""
        is_main = self._wait_for_main_interface() is not None
        self.info_set("主界面状态", "在主界面" if is_main else "不在主界面")
        return is_main

    def _return_to_character_selection(self):  # 按独立开关从日常结束后的界面返回角色选择。
        if not self.config.get("完成后返回角色选择", False):  # 检查结束后返回角色选择开关。
            return False  # 关闭时不执行任何窗口操作。
        self.info_set("返回角色选择状态", "等待主界面")  # 显示当前等待阶段。
        while True:  # 循环检测主界面并打开返回角色操作，直到OCR命中。
            frame = self.next_frame()  # 获取最新截图用于主界面判断。
            if not self._is_main_interface(frame):  # 未在主界面时先用Esc返回。
                self.log_info("当前不在主界面，按 Esc 等待2秒后重新检测主界面。")  # 记录本轮返回操作。
                self.send_key("esc", after_sleep=2.0)  # 按Esc并等待两秒。
                continue  # 返回主界面检测。
            self.send_key("esc", after_sleep=2.0)  # 确认在主界面后按Esc并等待两秒。
            self.click_relative(0.967, 0.931, after_sleep=2.0)  # 点击指定相对坐标并等待两秒。
            self.info_set("返回角色选择状态", "识别返回角色")  # 显示进入OCR识别阶段。
            return_box = self.box_of_screen(0.263, 0.642, to_x=0.733, to_y=0.797)  # 使用新的角色关键词识别区域。
            return_button = self.wait_ocr(box=return_box, match=re.compile(r"角色"), time_out=5.0, raise_if_not_found=False)  # 最多五秒识别包含角色的文字。
            if not return_button:  # OCR未命中时重新确认主界面。
                self.info_set("返回角色选择状态", "未识别到角色，重新检测主界面")  # 显示重试原因。
                self.log_info("指定区域未识别到‘角色’，返回主界面检测。")  # 记录失败后的跳转。
                continue  # 回到主界面检测，不结束整个流程。
            self.click_box(return_button[0], after_sleep=1.0)  # 点击OCR关键词位置并等待一秒。
            self.info_set("返回角色选择状态", "已点击返回角色")  # 显示已经发送角色选择操作。
            return True  # 完成本次返回角色流程。

    def _wait_for_main_interface(self, attempts=10):
        """轮询主界面条件；首次不满足时按 Esc 后继续检测。"""
        for attempt in range(max(1, attempts)):
            frame = self.next_frame()
            if self._is_main_interface(frame):
                return frame
            self.log_info("未确认主界面，按 Esc 等待 2 秒后重新检测。")  # 记录重试原因及等待时间。
            self.send_key("esc", after_sleep=2.0)  # 发送 Esc 并等待两秒后再刷新截图。
        return None

    def _check_daxia_road_progress(self):
        """打开大侠之路，验证进度，并按指定条件处理可领取项目。"""
        if not self.config.get("启用大侠之路检测", True):
            self.info_set("大侠之路状态", "大侠之路检测已关闭")
            self.log_info("配置开关已关闭，跳过整个大侠之路检测流程。")
            return False

        self.log_info("返回主界面后按 H 打开大侠之路。")
        self.send_key("h", after_sleep=1.0)
        retry_limit = max(1, int(self.config.get("Daxia Road Retry Limit", 5)))
        for attempt in range(retry_limit):
            if not self._is_daxia_road_page():
                self.info_set("大侠之路状态", "未确认进入大侠之路")
                self.log_warning("(0,0) 的 200×50 区域未识别到“大侠之路”。")
                self.send_key("esc", after_sleep=0.5)
                return False

            progress_box = self.box_of_screen(617 / 1280, 617 / 720, width=55 / 1280, height=55 / 720)
            progress = self.wait_ocr(
                box=progress_box,
                match="100",
                time_out=3.0,
                raise_if_not_found=False,
            )
            if progress:
                self.log_info("进度区域识别到 100；继续检测五个颜色标记，未命中时验证完成颜色。")

            self.info_set("大侠之路状态", "大侠之路未完成")
            self.log_info("大侠之路未完成：检查指定颜色和任务关键词。")
            frame = self.next_frame()
            keyword_match = re.compile(r"(在线|一分钟|沙盘|外观|奇遇|茶饼|好友装备)")
            marker_x = self._find_daxia_retry_marker(frame, (400,))
            if marker_x is not None:
                task_box_x, retry_click_x, task_click_x = 250, 400, 330
            else:
                marker_x = self._find_daxia_retry_marker(frame, (600,))
                if marker_x is not None:
                    task_box_x, retry_click_x, task_click_x = 450, 600, 530
                else:
                    marker_x = self._find_daxia_retry_marker(frame, (800,))
                    if marker_x is not None:
                        task_box_x, retry_click_x, task_click_x = 650, 800, 730
                    else:
                        marker_x = self._find_daxia_retry_marker(frame, (1000,))
                        if marker_x is not None:
                            task_box_x, retry_click_x, task_click_x = 850, 1000, 930
                        else:
                            marker_x = self._find_daxia_retry_marker(frame, (1200,))
                            if marker_x is None:
                                self.log_info("五个颜色标记均未命中。")
                                if progress:
                                    return self._verify_daxia_completion_color(frame)
                                self.log_info("进度区域未识别到 100，停止本轮处理。")
                                self.send_key("esc", after_sleep=0.5)
                                return False
                            task_box_x, retry_click_x, task_click_x = 1050, 1200, 1130

            height, width = frame.shape[:2]  # 使用当前游戏画面尺寸缩放点击坐标。
            retry_x, retry_y = round(retry_click_x * width / 1280), round(215 * height / 720)  # 缩放关键词未命中时的重试位置。
            action_x, action_y = round(task_click_x * width / 1280), round(360 * height / 720)  # 缩放当前任务的执行位置。
            friend_x, friend_y = round(300 * width / 1280), round(260 * height / 720)  # 缩放好友装备的后续点击位置。
            task_box = self.box_of_screen(task_box_x / 1280, 495 / 720, width=174 / 1280, height=48 / 720)
            task_words = []
            while not task_words:
                task_words = self.wait_ocr(
                    box=task_box,
                    match=keyword_match,
                    time_out=2.0,
                    raise_if_not_found=False,
                )
                if not task_words:
                    self.log_info(f"未识别到关键词，点击 ({retry_x},{retry_y}) 后继续检测。")  # 显示缩放后的实际重试坐标。
                    self.click(retry_x, retry_y, after_sleep=0.5)  # 在当前分辨率对应位置重试。

            if any("茶饼" in str(getattr(word, "name", getattr(word, "text", ""))) for word in task_words):
                self.log_info("五次检测中的关键词区域识别到“茶饼”，不执行当前分支点击，返回颜色检测起点重新循环。")
                continue

            is_friend_equipment = any(
                "好友装备" in str(getattr(word, "name", getattr(word, "text", "")))
                for word in task_words
            )
            self.log_info(f"识别到大侠之路任务关键词，点击 ({action_x},{action_y})，等待 5 秒后按 Esc。")  # 显示实际任务点击坐标。
            self.click(action_x, action_y, after_sleep=0)  # 点击缩放后的任务位置。
            self.sleep(5.0)
            if is_friend_equipment:
                self.log_info(f"识别到“好友装备”，等待后点击 ({friend_x},{friend_y})，再返回大侠之路检测流程。")  # 显示实际好友装备坐标。
                self.click(friend_x, friend_y, after_sleep=0)  # 点击缩放后的好友装备位置。
                self.sleep(2.0)
                self.send_key("esc", after_sleep=1.0)
                return False

            self.send_key("esc", after_sleep=1.0)
            if self._is_daxia_road_page():
                self.info_set("大侠之路状态", "已返回大侠之路页面")
                self.log_info("按 Esc 后已通过标题 OCR 确认返回大侠之路页面。")
                self.send_key("esc", after_sleep=0.5)
            return False

        self.info_set("大侠之路状态", "大侠之路未完成")
        self.log_warning(f"本轮已检查 {retry_limit} 次，回到主界面后会继续检测。")
        self.send_key("esc", after_sleep=0.5)
        return False

    def _is_daxia_road_page(self):
        """通过左上角 200×50 区域 OCR 确认当前页面。"""
        title_box = self.box_of_screen(0, 0, width=200 / 1280, height=50 / 720)
        return bool(self.wait_ocr(
            box=title_box,
            match="大侠之路",
            time_out=5.0,
            raise_if_not_found=False,
        ))

    def _verify_daxia_completion_color(self, frame):
        """识别 100 后，循环点击目标坐标直至 RGB 匹配，再返回主页。"""
        if not isinstance(frame, np.ndarray):
            self.info_set("大侠之路状态", "无法读取完成颜色")
            return False

        target_x, target_y = 1456, 969
        while True:
            rgb = self._sample_daxia_completion_rgb(frame, target_x, target_y)
            if rgb == (149, 255, 149):
                self.send_key("esc", after_sleep=1.0)
                self.info_set("大侠之路状态", "大侠之路已完成")
                self.log_info("识别到 100，且 (1456,969) RGB 为 (149,255,149)；按 Esc 返回主页。")
                return True

            height, width = frame.shape[:2]
            click_x = round(target_x * width / 1920)
            click_y = round(target_y * height / 1080)
            self.log_info(f"(1456,969) 当前 RGB={rgb}，目标为 (149,255,149)，点击后重新检测。")
            self.click(click_x, click_y, after_sleep=0.5)
            frame = self.next_frame()
            if frame is None:
                self.info_set("大侠之路状态", "无法读取完成颜色")
                return False

    def _is_main_interface(self, frame):  # 按当前画面尺寸缩放颜色点和角色区域，确认主界面。
        """以1280×720为基准，R(90,37)>160且角色区域无“角色”时判定为主界面。"""
        if not isinstance(frame, np.ndarray) or frame.ndim < 3 or frame.shape[2] < 3:  # 拒绝无效截图。
            return False  # 无法读取画面时不判定为主界面。
        height, width = frame.shape[:2]  # 读取当前画面尺寸。
        x, y = round(90 * width / 1280), round(37 * height / 720)  # 缩放颜色检测点。
        if not (0 <= x < width and 0 <= y < height):  # 避免读取越界像素。
            return False  # 画面尺寸异常时返回失败。
        if int(frame[y, x, 2]) <= 160:  # 截图使用BGR通道，第三个通道为R。
            return False  # R值必须严格超过160。
        role_x, role_y = round(805 * width / 1280), round(209 * height / 720)  # 缩放角色区域起点。
        role_width, role_height = max(1, round(75 * width / 1280)), max(1, round(36 * height / 720))  # 缩放角色区域宽高。
        role_words = self.ocr(  # 在同一截图内检测角色关键词。
            x=role_x / width, y=role_y / height,  # 将缩放后的起点传为框架要求的相对坐标。
            width=role_width, height=role_height,  # 使用当前分辨率下的像素宽高。
            match=re.compile(r"角色"), frame=frame,  # 匹配包含“角色”的文字。
        )  # 完成角色区域OCR。
        return not role_words  # R值通过且未识别到角色时确认主界面。

    @staticmethod
    def _sample_pixel_rgb(frame, base_x, base_y):
        """按 1280×720 基准坐标读取单个像素的 RGB 值。"""
        if not isinstance(frame, np.ndarray) or frame.ndim < 3 or frame.shape[2] < 3:
            return None
        height, width = frame.shape[:2]
        x = round(base_x * width / 1280)
        y = round(base_y * height / 720)
        if x < 0 or y < 0 or x >= width or y >= height:
            return None
        return tuple(int(channel) for channel in frame[y, x, :3][::-1])

    @staticmethod
    def _sample_daxia_completion_rgb(frame, base_x, base_y):
        """按 1920×1080 基准映射坐标，并返回截图像素的 RGB 元组。"""
        if not isinstance(frame, np.ndarray) or frame.ndim < 3 or frame.shape[2] < 3:
            return None
        height, width = frame.shape[:2]
        x = round(base_x * width / 1920)
        y = round(base_y * height / 1080)
        if x < 0 or y < 0 or x >= width or y >= height:
            return None
        return tuple(int(channel) for channel in frame[y, x, :3][::-1])

    @staticmethod
    def _find_daxia_retry_marker(frame, base_x_positions):
        """按顺序返回首个匹配指定 RGB 的横坐标，未命中则返回 None。"""
        if not isinstance(frame, np.ndarray) or frame.ndim < 3 or frame.shape[2] < 3:
            return None

        height, width = frame.shape[:2]
        for base_x in base_x_positions:
            x, y = base_x, 205
            if width != 1280 or height != 720:
                x = round(x * width / 1280)
                y = round(y * height / 720)
            if x < 0 or y < 0 or x >= width or y >= height:
                continue
            rgb = frame[y, x, :3][::-1]
            if np.array_equal(rgb, np.array([216, 247, 255])):
                return base_x
        return None

    @staticmethod
    def _is_daxia_retry_marker(frame):
        """兼容性判断：前两个检测点任一点匹配即返回 True。"""
        return DailyChecklistTask._find_daxia_retry_marker(frame, (600, 800)) is not None

    def _ensure_game_foreground(self):
        """按配置决定是否将游戏窗口置前并确认输入目标。"""
        if not self.config.get("窗口前置", True):
            self.info_set("窗口前置状态", "已关闭")
            return True

        foreground = self.wait_until(
            lambda: bool(self.hwnd and self.hwnd.is_foreground()),
            time_out=3.0,
            pre_action=self.ensure_in_front,
            raise_if_not_found=False,
        )
        if not foreground:
            self.log_warning("游戏窗口未能进入前台，本轮不执行点击或按键。")
        return bool(foreground)

    @staticmethod
    def _get_check_in_red_value(frame):
        """读取 1280×720 画面坐标 (246,123) 的 R 通道值。"""
        if not isinstance(frame, np.ndarray) or frame.ndim < 3 or frame.shape[2] < 3:
            return 0

        height, width = frame.shape[:2]
        x, y = 246, 123
        if width != 1280 or height != 720:
            x = round(x * width / 1280)
            y = round(y * height / 720)

        if x < 0 or y < 0 or x >= width or y >= height:
            return 0

        return int(frame[y, x, 2])
