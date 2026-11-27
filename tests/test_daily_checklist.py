import re  # 用于校验跑商目的地关键词正则。
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import ANY, PropertyMock, patch

import numpy as np
from ok.test.TaskTestCase import TaskTestCase

from src.config import config as app_config
from src.tasks.DailyChecklistTask import (
    DailyChecklistTask,
    normalize_task_names,
    summarize_checklist,
)


class DailyChecklistTests(unittest.TestCase):
    def test_normalize_task_names_trims_deduplicates_and_skips_invalid_values(self):
        self.assertEqual(
            normalize_task_names(["  Daily  ", "", "Daily", None, "Weekly"]),
            ["Daily", "Weekly"],
        )

    def test_summary_counts_only_matching_completed_tasks(self):
        result = summarize_checklist(
            ["Sign-in", "Dungeon", "Dungeon"],
            ["Dungeon", "Not in plan"],
            45,
            12,
        )
        self.assertEqual(result["tasks"], ["Sign-in", "Dungeon"])
        self.assertEqual(result["done"], ["Dungeon"])
        self.assertEqual(result["remaining"], ["Sign-in"])
        self.assertEqual(result["planned_minutes"], 24)
        self.assertEqual(result["remaining_minutes"], 12)
        self.assertEqual(result["budget_minutes"], 45)

    def test_summary_clamps_non_positive_time_values(self):
        result = summarize_checklist(["One"], [], 0, -3)
        self.assertEqual(result["budget_minutes"], 1)
        self.assertEqual(result["minutes_per_task"], 1)


class DailyChecklistTaskTests(TaskTestCase):
    task_class = DailyChecklistTask
    config = app_config

    def setUp(self):
        super().setUp()
        self.task.config["启用大侠之路检测"] = True

    def test_task_metadata_and_defaults(self):
        self.assertEqual(self.task.name, "Daily Checklist")
        self.assertIsInstance(self.task.default_config["Daily Tasks"], list)
        self.assertIsInstance(self.task.default_config["Completed Tasks"], list)
        self.assertEqual(self.task.default_config["Daily Budget Minutes"], 60)
        self.assertEqual(self.task.default_config["Estimated Minutes Per Task"], 10)
        self.assertTrue(self.task.default_config["启用大侠之路检测"])
        self.assertTrue(self.task.default_config["窗口前置"])
        self.assertFalse(self.task.default_config["整合茶馆任务"])
        self.assertFalse(self.task.default_config["接受第一次跑商任务"])  # 跑商独立开关默认关闭。
        self.assertFalse(self.task.default_config["第一次跑商任务"])  # 跑商执行循环同样默认关闭。
        self.assertFalse(self.task.default_config["完成后返回角色选择"])  # 完成后返回角色选择默认关闭。
        self.assertEqual(self.task.default_config["茶馆任务列表"], "不选择")
        self.assertEqual(self.task.config_type["茶馆任务列表"]["type"], "drop_down")
        self.assertIn("茶树", self.task.config_type["茶馆任务列表"]["options"])

    def test_foreground_switch_disabled_skips_foreground_activation(self):
        self.task.config = {"窗口前置": False}
        with patch.object(self.task, "wait_until") as wait_until, \
                patch.object(self.task, "ensure_in_front") as ensure_in_front, \
                patch.object(self.task, "info_set") as info_set:
            self.assertTrue(self.task._ensure_game_foreground())

        wait_until.assert_not_called()
        ensure_in_front.assert_not_called()
        info_set.assert_called_once_with("窗口前置状态", "已关闭")

    def test_foreground_switch_enabled_keeps_existing_activation(self):
        self.task.config = {"窗口前置": True}
        with patch.object(self.task, "wait_until", return_value=True) as wait_until, \
                patch.object(self.task, "ensure_in_front") as ensure_in_front:
            self.assertTrue(self.task._ensure_game_foreground())

        wait_until.assert_called_once()
        self.assertEqual(wait_until.call_args.kwargs["pre_action"], ensure_in_front)

    def test_return_to_character_selection_switch_disabled_skips_actions(self):
        self.task.config = {"完成后返回角色选择": False}  # 明确关闭结束后返回开关。
        with patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "next_frame") as next_frame, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "click_relative") as click:
            self.assertFalse(self.task._return_to_character_selection())  # 关闭时返回未执行。
        foreground.assert_not_called()  # 不抢占游戏窗口。
        next_frame.assert_not_called()  # 不读取新截图。
        send_key.assert_not_called()  # 不发送 Esc。
        click.assert_not_called()  # 不执行位置点击。

    def test_return_to_character_selection_retries_until_main_then_clicks_ocr(self):
        self.task.config = {"完成后返回角色选择": True}  # 开启完成后返回角色选择。
        button = object()  # 构造 OCR 识别到的返回角色文字框。
        with patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "next_frame", side_effect=[np.zeros((720, 1280, 3), dtype=np.uint8), np.zeros((720, 1280, 3), dtype=np.uint8)]) as next_frame, \
                patch.object(self.task, "_is_main_interface", side_effect=[False, True]) as is_main, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "click_relative") as click_relative, \
                patch.object(self.task, "box_of_screen", return_value="return-region") as box_of_screen, \
                patch.object(self.task, "wait_ocr", return_value=[button]) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box:
            self.assertTrue(self.task._return_to_character_selection())  # 循环返回主界面并点击 OCR 结果。
        foreground.assert_not_called()  # 返回角色流程不检查窗口前置。
        self.assertEqual(next_frame.call_count, 2)  # 第一次未命中后刷新截图再检测。
        self.assertEqual(is_main.call_count, 2)  # 主界面检测直到命中。
        self.assertEqual(send_key.call_args_list, [unittest.mock.call("esc", after_sleep=2.0)] * 2)  # 未在主界面和已在主界面分别按一次Esc。
        click_relative.assert_called_once_with(0.967, 0.931, after_sleep=2.0)  # 仅主界面确认后点击指定位置。
        box_of_screen.assert_called_once_with(0.263, 0.642, to_x=0.733, to_y=0.797)  # 校验新的OCR区域。
        self.assertEqual(wait_ocr.call_args.kwargs["match"].pattern, "角色")  # 确认关键词调整为角色。
        self.assertEqual(wait_ocr.call_args.kwargs["time_out"], 5.0)  # 确认最多等待五秒。
        click_box.assert_called_once_with(button, after_sleep=1.0)  # 点击识别到的文字位置。

    def test_return_to_character_selection_rechecks_main_when_ocr_misses(self):
        self.task.config = {"完成后返回角色选择": True}  # 开启结束后返回角色选择。
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)  # 创建用于主界面判断的截图。
        with patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "next_frame", return_value=frame) as next_frame, \
                patch.object(self.task, "_is_main_interface", side_effect=[True, False, True]) as is_main, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "click_relative") as click_relative, \
                patch.object(self.task, "box_of_screen", return_value="return-region"), \
                patch.object(self.task, "wait_ocr", side_effect=[None, [frame]]) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set") as info_set:
            self.assertTrue(self.task._return_to_character_selection())  # 未识别后返回检测并在下一轮命中。
        foreground.assert_not_called()  # 即使OCR失败也不检查窗口前置。
        self.assertEqual(next_frame.call_count, 3)  # OCR失败后确实获取新画面检测主界面。
        self.assertEqual(is_main.call_count, 3)  # 覆盖命中、返回失败和再次命中三个状态。
        self.assertEqual(send_key.call_args_list, [unittest.mock.call("esc", after_sleep=2.0)] * 3)  # 每次按Esc均等待两秒。
        self.assertEqual(click_relative.call_args_list, [unittest.mock.call(0.967, 0.931, after_sleep=2.0)] * 2)  # 只有主界面命中时才点击菜单位置。
        self.assertEqual(wait_ocr.call_count, 2)  # 确认OCR失败会重新执行。
        click_box.assert_called_once_with(frame, after_sleep=1.0)  # 仅点击成功识别的关键词位置。
        info_set.assert_any_call("返回角色选择状态", "未识别到角色，重新检测主界面")  # 显示OCR失败后的重试状态。

    def test_daxia_road_flow_switch_can_disable_the_whole_flow(self):
        self.task.config = {"启用大侠之路检测": False}
        with patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "info_set") as info_set:
            self.assertFalse(self.task._check_daxia_road_progress())

        send_key.assert_not_called()
        info_set.assert_any_call("大侠之路状态", "大侠之路检测已关闭")
        self.task.config = {"启用大侠之路检测": True}

    def test_run_displays_manual_checkin_progress(self):
        self.task.config = {
            "Daily Tasks": ["Sign-in", "Dungeon"],
            "Completed Tasks": ["Sign-in"],
            "Daily Budget Minutes": 45,
            "Estimated Minutes Per Task": 12,
            "_progress_date": date.today().isoformat(),
        }
        self.task.info.clear()
        with patch.object(self.task, "_run_huaxialou_checkin"), \
                patch.object(self.task, "_run_tea_cake_claim"), \
                patch.object(self.task, "_run_tea_house_daily"), \
                patch.object(self.task, "_run_daxia_until_complete"):
            self.task.run()
        self.assertEqual(self.task.info[self.task._translate("Daily progress")], "1/2")
        self.assertEqual(
            self.task.info[self.task._translate("Time budget / planned")],
            "45 / 24 min",
        )
        self.assertEqual(
            self.task.info[self.task._translate("Estimated time remaining")],
            "12 min",
        )
        self.assertEqual(self.task.info["01. Sign-in"], self.task._translate("Done"))
        self.assertEqual(self.task.info["02. Dungeon"], self.task._translate("Pending"))

    def test_run_executes_flip_tea_leaves_as_separate_step(self):
        self.task.config = {
            "Daily Tasks": [],
            "Completed Tasks": [],
            "_progress_date": date.today().isoformat(),
        }
        call_order = []
        with patch.object(self.task, "_run_huaxialou_checkin", side_effect=lambda: call_order.append("checkin")), \
                patch.object(self.task, "_run_tea_cake_claim", side_effect=lambda: call_order.append("tea_cake")), \
                patch.object(self.task, "_run_tea_house_daily", side_effect=lambda: call_order.append("tea_house")), \
                patch.object(self.task, "_run_first_tea", side_effect=lambda: call_order.append("first_tea")), \
                patch.object(self.task, "_run_flip_tea_leaves", side_effect=lambda: call_order.append("flip_tea_leaves")), \
                patch.object(self.task, "_run_spring_water", side_effect=lambda: call_order.append("spring_water")), \
                patch.object(self.task, "_run_guest", side_effect=lambda: call_order.append("guest")), \
                patch.object(self.task, "_run_bamboo_shoot", side_effect=lambda: call_order.append("bamboo_shoot")), \
                patch.object(self.task, "_run_turn_in_tea_house", side_effect=lambda: call_order.append("turn_in_tea_house")), \
                patch.object(self.task, "_run_flower_tea", side_effect=lambda: call_order.append("flower_tea")), \
                patch.object(self.task, "_run_flower_grass", side_effect=lambda: call_order.append("flower_grass")), \
                patch.object(self.task, "_run_tea_tree", side_effect=lambda: call_order.append("tea_tree")), \
                patch.object(self.task, "_run_daxia_until_complete", side_effect=lambda: call_order.append("daxia")), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.task.run()

        self.assertEqual(call_order, ["checkin", "tea_cake", "daxia"])

    def test_run_executes_only_selected_tea_task(self):
        self.task.config = {
            "茶馆任务列表": "茶树",
            "_progress_date": date.today().isoformat(),
        }
        call_order = []
        with patch.object(self.task, "_run_huaxialou_checkin", side_effect=lambda: call_order.append("checkin")), \
                patch.object(self.task, "_run_tea_cake_claim", side_effect=lambda: call_order.append("tea_cake")), \
                patch.object(self.task, "_run_tea_tree", side_effect=lambda: call_order.append("tea_tree")), \
                patch.object(self.task, "_run_flower_grass", side_effect=lambda: call_order.append("flower_grass")), \
                patch.object(self.task, "_run_daxia_until_complete", side_effect=lambda: call_order.append("daxia")), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.task.run()

        self.assertEqual(call_order, ["checkin", "tea_cake", "tea_tree", "daxia"])

    def test_tea_tree_switch_is_independent_and_off_by_default(self):
        self.task.config = {"茶树": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_tea_tree())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("茶树状态", "已关闭")

    def test_tea_tree_dropdown_enables_task_and_holds_key_one(self):
        self.task.config = {"茶馆任务列表": "茶树"}
        results = [object() for _ in range(6)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["first", "operation", "reply", "child", "tasting", "hand_in"]), \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "send_key_down") as key_down, \
                patch.object(self.task, "send_key_up") as key_up, \
                patch.object(self.task, "send_key") as key_press, \
                patch.object(self.task, "sleep") as sleep, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_tea_tree())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=40.0),
                unittest.mock.call(results[1], after_sleep=5.0),
                unittest.mock.call(results[2], after_sleep=40.0),
                unittest.mock.call(results[3], after_sleep=2.0),
                unittest.mock.call(results[4], after_sleep=2.0),
                unittest.mock.call(results[5], after_sleep=2.0),
            ],
        )
        self.assertEqual(key_down.call_count, 0)
        self.assertEqual(key_up.call_count, 0)
        self.assertEqual(key_press.call_count, 30)
        self.assertTrue(all(call.args == ("1",) for call in key_press.call_args_list))
        self.assertEqual(key_press.call_args_list[0].kwargs, {"after_sleep": 1.0})
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["茶树", "操作", "回复", "茶馆小童", "品茗", "交任务"],
        )

    def test_flower_grass_switch_is_independent_and_off_by_default(self):
        self.task.config = {"花草": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_flower_grass())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("花草状态", "已关闭")

    def test_flower_grass_clicks_each_step_in_order(self):
        self.task.config = {"花草": True}
        results = [object() for _ in range(6)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["first", "second", "reply", "child", "tasting", "hand_in"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_flower_grass())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=40.0),
                unittest.mock.call(results[1], after_sleep=5.0),
                unittest.mock.call(results[2], after_sleep=40.0),
                unittest.mock.call(results[3], after_sleep=2.0),
                unittest.mock.call(results[4], after_sleep=2.0),
                unittest.mock.call(results[5], after_sleep=2.0),
            ],
        )
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["花草", "花草", "回复", "茶馆小童", "品茗", "交任务"],
        )

    def test_flower_tea_switch_is_independent_and_off_by_default(self):
        self.task.config = {"花茶": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_flower_tea())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("花茶状态", "已关闭")

    def test_flower_tea_clicks_each_step_and_presses_f(self):
        self.task.config = {"花茶": True}
        results = [object() for _ in range(8)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["flower", "operation", "reply", "child", "tasting", "hand_in"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_flower_tea())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=7.0),
                unittest.mock.call(results[1], after_sleep=2.0),
                unittest.mock.call(results[2], after_sleep=7.0),
                unittest.mock.call(results[3], after_sleep=2.0),
                unittest.mock.call(results[4], after_sleep=7.0),
                unittest.mock.call(results[5], after_sleep=2.0),
                unittest.mock.call(results[6], after_sleep=2.0),
                unittest.mock.call(results[7], after_sleep=2.0),
            ],
        )
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["花材", "操作", "茶摊", "操作", "回复", "茶馆小童", "品茗", "交任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(0.045, 0.149, to_x=0.196, to_y=0.258),
                unittest.mock.call(0.677, 0.332, to_x=0.809, to_y=0.490),
                unittest.mock.call(0.050, 0.182, to_x=0.152, to_y=0.215),
                unittest.mock.call(0.677, 0.332, to_x=0.823, to_y=0.621),
                unittest.mock.call(0.624, 0.249, to_x=0.956, to_y=0.361),
                unittest.mock.call(0.712, 0.893, to_x=0.861, to_y=0.975),
            ],
        )

    def test_integrated_tea_tasks_dispatches_by_keyword(self):
        self.task.config = {"整合茶馆任务": True}
        tea_house = patch.object(self.task, "_run_tea_house_daily", return_value=True)
        first_tea = patch.object(self.task, "_run_first_tea", return_value=True)
        flip = patch.object(self.task, "_run_flip_tea_leaves", return_value=True)
        with tea_house as tea_house_mock, first_tea as first_tea_mock, flip as flip_mock, \
                patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="task-region"), \
                patch.object(self.task, "wait_ocr", return_value=[SimpleNamespace(name="茶叶")]), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_warning"):
            self.assertTrue(self.task._run_integrated_tea_tasks())

        tea_house_mock.assert_called_once_with()
        first_tea_mock.assert_called_once_with()
        flip_mock.assert_called_once_with()

    def test_integrated_tea_tasks_dispatches_flower_grass_keyword(self):
        self.task.config = {"整合茶馆任务": True}
        tea_house = patch.object(self.task, "_run_tea_house_daily", return_value=True)
        first_tea = patch.object(self.task, "_run_first_tea", return_value=True)
        flower_grass = patch.object(self.task, "_run_flower_grass", return_value=True)
        with tea_house as tea_house_mock, first_tea as first_tea_mock, flower_grass as flower_grass_mock, \
                patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="task-region"), \
                patch.object(self.task, "wait_ocr", return_value=[SimpleNamespace(name="花草")]), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_warning"):
            self.assertTrue(self.task._run_integrated_tea_tasks())

        tea_house_mock.assert_called_once_with()
        first_tea_mock.assert_called_once_with()
        flower_grass_mock.assert_called_once_with()

    def test_integrated_tea_tasks_dispatches_tea_tree_keyword(self):
        self.task.config = {"整合茶馆任务": True}
        tea_house = patch.object(self.task, "_run_tea_house_daily", return_value=True)
        first_tea = patch.object(self.task, "_run_first_tea", return_value=True)
        tea_tree = patch.object(self.task, "_run_tea_tree", return_value=True)
        with tea_house as tea_house_mock, first_tea as first_tea_mock, tea_tree as tea_tree_mock, \
                patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="task-region"), \
                patch.object(self.task, "wait_ocr", return_value=[SimpleNamespace(name="茶树")]), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_warning"):
            self.assertTrue(self.task._run_integrated_tea_tasks())

        tea_house_mock.assert_called_once_with()
        first_tea_mock.assert_called_once_with()
        tea_tree_mock.assert_called_once_with()

    def test_turn_in_tea_house_switch_is_independent_and_off_by_default(self):
        self.task.config = {"交茶馆": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_turn_in_tea_house())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("交茶馆状态", "已关闭")

    def test_turn_in_tea_house_clicks_each_step_in_order(self):
        self.task.config = {"交茶馆": True}
        results = [object() for _ in range(4)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["first", "second", "mountain", "hand_in"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_turn_in_tea_house())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=5.0),
                unittest.mock.call(results[1], after_sleep=2.0),
                unittest.mock.call(results[2], after_sleep=2.0),
                unittest.mock.call(results[3]),
            ],
        )
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["赵云", "赵云", "山城", "交任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(0.045, 0.144, to_x=0.171, to_y=0.236),
                unittest.mock.call(0.673, 0.339, to_x=0.824, to_y=0.585),
                unittest.mock.call(0.623, 0.272, to_x=0.957, to_y=0.418),
                unittest.mock.call(0.714, 0.879, to_x=0.864, to_y=0.976),
            ],
        )

    def test_bamboo_shoot_switch_is_independent_and_off_by_default(self):
        self.task.config = {"竹笋": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_bamboo_shoot())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("竹笋状态", "已关闭")

    def test_bamboo_shoot_clicks_each_step_and_uses_reply_ocr(self):
        self.task.config = {"竹笋": True}
        results = [object() for _ in range(6)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["first", "second", "reply", "child", "tasting", "hand_in"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_bamboo_shoot())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=25.0),
                unittest.mock.call(results[1], after_sleep=5.0),
                unittest.mock.call(results[2], after_sleep=25.0),
                unittest.mock.call(results[3], after_sleep=2.0),
                unittest.mock.call(results[4], after_sleep=2.0),
                unittest.mock.call(results[5], after_sleep=2.0),
            ],
        )
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["春笋", "春笋", "回复", "茶馆小童", "品茗", "交任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(0.045, 0.147, to_x=0.201, to_y=0.278),
                unittest.mock.call(0.673, 0.332, to_x=0.823, to_y=0.567),
                unittest.mock.call(0.046, 0.146, to_x=0.191, to_y=0.231),
                unittest.mock.call(0.677, 0.332, to_x=0.823, to_y=0.621),
                unittest.mock.call(0.624, 0.249, to_x=0.956, to_y=0.361),
                unittest.mock.call(0.712, 0.893, to_x=0.861, to_y=0.975),
            ],
        )

    def test_guest_switch_is_independent_and_off_by_default(self):
        self.task.config = {"客人": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_guest())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("客人状态", "已关闭")

    def test_guest_clicks_each_recognized_step_in_order(self):
        self.task.config = {"客人": True}
        results = [object() for _ in range(7)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["first", "second", "guest", "reply", "child", "tasting", "hand_in"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "click_relative") as click_relative, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_guest())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=7.0),
                unittest.mock.call(results[1], after_sleep=5.0),
                unittest.mock.call(results[2], after_sleep=2.0),
                unittest.mock.call(results[3], after_sleep=7.0),
                unittest.mock.call(results[4], after_sleep=2.0),
                unittest.mock.call(results[5], after_sleep=2.0),
                unittest.mock.call(results[6], after_sleep=2.0),
            ],
        )
        click_relative.assert_called_once_with(0.614, 0.817)
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["神秘", "神秘", "客人", "回复", "茶馆小童", "品茗", "交任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(0.045, 0.147, to_x=0.201, to_y=0.278),
                unittest.mock.call(0.673, 0.331, to_x=0.820, to_y=0.658),
                unittest.mock.call(0.636, 0.589, to_x=0.925, to_y=0.703),
                unittest.mock.call(0.050, 0.182, to_x=0.152, to_y=0.215),
                unittest.mock.call(0.677, 0.332, to_x=0.823, to_y=0.621),
                unittest.mock.call(0.624, 0.249, to_x=0.956, to_y=0.361),
                unittest.mock.call(0.712, 0.893, to_x=0.861, to_y=0.975),
            ],
        )

    def test_spring_water_switch_is_independent_and_off_by_default(self):
        self.task.config = {"山泉": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_spring_water())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("山泉状态", "已关闭")

    def test_spring_water_clicks_each_recognized_step_in_order(self):
        self.task.config = {"山泉": True}
        results = [object() for _ in range(5)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["spring", "number", "child", "tasting", "hand_in"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "click_relative") as click_relative, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_spring_water())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=25.0),
                unittest.mock.call(results[1], after_sleep=7.0),
                unittest.mock.call(results[2], after_sleep=2.0),
                unittest.mock.call(results[3], after_sleep=2.0),
                unittest.mock.call(results[4], after_sleep=2.0),
            ],
        )
        click_relative.assert_called_once_with(0.106, 0.174, after_sleep=23.0)
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["泉水", "8", "茶馆小童", "品茗", "交任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(0.045, 0.147, to_x=0.201, to_y=0.278),
                unittest.mock.call(0.777, 0.504, to_x=0.859, to_y=0.644),
                unittest.mock.call(0.677, 0.332, to_x=0.823, to_y=0.621),
                unittest.mock.call(0.624, 0.249, to_x=0.956, to_y=0.361),
                unittest.mock.call(0.712, 0.893, to_x=0.861, to_y=0.975),
            ],
        )

    def test_tea_house_switch_off_does_not_touch_game(self):
        self.task.config = {"启用茶馆日常": False}
        with patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "wait_ocr") as wait_ocr:
            self.assertFalse(self.task._run_tea_house_daily())

        info_set.assert_called_once_with("茶馆日常状态", "已关闭")
        foreground.assert_not_called()
        send_key.assert_not_called()
        wait_ocr.assert_not_called()

    def test_first_tea_runs_independently_of_tea_house_daily_switch(self):
        self.task.config = {"启用茶馆日常": False, "第一次茶馆": True}
        with patch.object(self.task, "_ensure_game_foreground", return_value=True) as foreground, \
                patch.object(self.task, "_run_tea_house_followup_steps", return_value=True) as followup:
            self.assertTrue(self.task._run_first_tea())

        foreground.assert_called_once_with()
        followup.assert_called_once_with()

    def test_first_tea_disabled_does_not_run_followup_flow(self):
        self.task.config = {"启用茶馆日常": True, "第一次茶馆": False}
        with patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "_run_tea_house_followup_steps") as followup, \
                patch.object(self.task, "info_set") as info_set:
            self.assertFalse(self.task._run_first_tea())

        foreground.assert_not_called()
        followup.assert_not_called()
        info_set.assert_called_once_with("第一次茶馆状态", "已关闭")

    def test_first_tea_followup_recognizes_and_clicks_all_four_steps(self):
        complete_or_commission, tea_keyword, tasting_keyword, accept_keyword = [object() for _ in range(4)]
        events = []
        with patch.object(self.task, "box_of_screen", side_effect=["complete", "tea", "tasting", "accept"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[complete_or_commission, tea_keyword, tasting_keyword, accept_keyword]) as wait_ocr, \
                patch.object(self.task, "click", side_effect=lambda *args, **kwargs: events.append(("click", args, kwargs))), \
                patch.object(self.task, "click_box", side_effect=lambda box, **kwargs: events.append(("click_box", box, kwargs))), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_tea_house_followup_steps())

        self.assertEqual(
            events,
            [
                ("click", (150, 147), {"after_sleep": 5.0}),
                ("click_box", tea_keyword, {"after_sleep": 2.0}),
                ("click_box", tasting_keyword, {"after_sleep": 2.0}),
                ("click_box", accept_keyword, {"after_sleep": 2.0}),
            ],
        )
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["(完成|委托)", "茶馆", "品茗", "接受"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(53 / 1280, 100 / 720, width=213 / 1280, height=81 / 720),
                unittest.mock.call(867 / 1280, 239 / 720, width=156 / 1280, height=137 / 720),
                unittest.mock.call(0.626, 0.244, to_x=0.948, to_y=0.351),
                unittest.mock.call(0.712, 0.893, to_x=0.861, to_y=0.975),
            ],
        )

    def test_flip_tea_leaves_switch_is_independent_and_off_by_default(self):
        self.task.config = {"翻茶叶": False, "启用茶馆日常": False, "第一次茶馆": False}
        with patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "wait_ocr") as wait_ocr, \
                patch.object(self.task, "info_set") as info_set:
            self.assertFalse(self.task._run_flip_tea_leaves())

        foreground.assert_not_called()
        wait_ocr.assert_not_called()
        info_set.assert_called_once_with("翻茶叶状态", "已关闭")

    def test_flip_tea_leaves_clicks_each_recognized_step_in_order(self):
        self.task.config = {"翻茶叶": True, "启用茶馆日常": False, "第一次茶馆": False}
        results = [object() for _ in range(6)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["first", "second", "tasting", "accept"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_flip_tea_leaves())

        self.assertEqual(
            click_box.call_args_list,
            [
                unittest.mock.call(results[0], after_sleep=7.0),
                unittest.mock.call(results[1], after_sleep=5.0),
                unittest.mock.call(results[2], after_sleep=7.0),
                unittest.mock.call(results[3], after_sleep=2.0),
                unittest.mock.call(results[4], after_sleep=2.0),
                unittest.mock.call(results[5], after_sleep=2.0),
            ],
        )
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["茶叶", "茶叶", "回复", "茶馆小童", "品茗", "交任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(0.050, 0.182, to_x=0.152, to_y=0.215),
                unittest.mock.call(0.677, 0.332, to_x=0.823, to_y=0.621),
                unittest.mock.call(0.624, 0.249, to_x=0.956, to_y=0.361),
                unittest.mock.call(0.712, 0.893, to_x=0.861, to_y=0.975),
            ],
        )
        self.assertTrue(all(call.kwargs["time_out"] == 2.0 for call in wait_ocr.call_args_list))

    def test_flip_tea_leaves_retries_each_step_from_the_requested_previous_step(self):
        self.task.config = {"翻茶叶": True}
        tea_entry_a, tea_entry_b, tea_entry_c = [object() for _ in range(3)]
        tea_option_b, tea_option_c = [object() for _ in range(2)]
        reply_a, reply_b = [object() for _ in range(2)]
        child_a, child_b = [object() for _ in range(2)]
        tasting_a, tasting_b = [object() for _ in range(2)]
        hand_in_task = object()
        ocr_results = [
            tea_entry_a, [],                         # 第二步未识别：回第一步。
            tea_entry_b, tea_option_b, [],            # 第三步未识别：回第一步。
            tea_entry_c, tea_option_c, reply_a, [],   # 第四步未识别：回第三步。
            reply_b, child_a, [],                     # 第五步未识别：回第四步。
            child_b, tasting_a, [],                   # 第六步未识别：回第五步。
            tasting_b, hand_in_task,
        ]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="region"), \
                patch.object(self.task, "wait_ocr", side_effect=ocr_results) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_flip_tea_leaves())

        self.assertEqual(wait_ocr.call_count, len(ocr_results))
        self.assertEqual(click_box.call_count, 12)

    def test_first_trade_switch_disabled_does_not_send_input(self):
        self.task.config = {"接受第一次跑商任务": False}  # 明确关闭跑商接取开关。
        with patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "send_key_down") as key_down:
            self.assertFalse(self.task._run_first_trade_accept())  # 关闭时直接跳过。
        foreground.assert_not_called()  # 不抢占游戏窗口。
        key_down.assert_not_called()  # 不发送组合键。

    def test_first_trade_stops_before_calendar_when_foreground_or_main_fails(self):
        self.task.config = {"接受第一次跑商任务": True}  # 开启跑商接取开关。
        for foreground_ready, main_frame in [(False, object()), (True, None)]:  # 覆盖前台和主界面确认失败。
            with self.subTest(foreground=foreground_ready), \
                    patch.object(self.task, "box_of_screen", return_value="quest"), \
                    patch.object(self.task, "wait_ocr", return_value=[]), \
                    patch.object(self.task, "_ensure_game_foreground", return_value=foreground_ready), \
                    patch.object(self.task, "_wait_for_main_interface", return_value=main_frame), \
                    patch.object(self.task, "send_key_down") as key_down:
                self.assertFalse(self.task._run_first_trade_accept())  # 前置条件失败时中止。
            key_down.assert_not_called()  # 未确认主界面前不打开日历。

    def test_first_trade_regions_inputs_and_optional_confirmation(self):
        for has_confirmation in [False, True]:  # 验证没有弹窗和有弹窗两条成功路径。
            with self.subTest(confirmation=has_confirmation):  # 分别记录两种弹窗情况。
                self.task.config = {"接受第一次跑商任务": True}  # 独立启用跑商。
                words = [SimpleNamespace(name=name) for name in ["活动日历", "据点贸易", "阵营沙盘", "确认", "据点总管", "据点贸易", "接受任务"]]  # 构造各步骤的 OCR 结果。
                results = [[word] for word in words]  # 将识别框包装为 OCR 返回列表。
                if not has_confirmation:  # 无确认弹窗时仅第四次 OCR 返回空。
                    results[3] = []  # 其余必需关键词保持命中。
                with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                        patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                        patch.object(self.task, "send_key_down") as key_down, \
                        patch.object(self.task, "send_key_up") as key_up, \
                        patch.object(self.task, "send_key") as send_key, \
                        patch.object(self.task, "box_of_screen", return_value="region") as make_box, \
                        patch.object(self.task, "wait_ocr", side_effect=[[]] + results) as ocr, \
                        patch.object(self.task, "click_box") as click_box, \
                        patch.object(self.task, "out_of_ratio", return_value=False), \
                        patch.object(type(self.task), "width", new_callable=PropertyMock, return_value=1920), \
                        patch.object(type(self.task), "height", new_callable=PropertyMock, return_value=1080), \
                        patch.object(self.task, "click") as click, \
                        patch.object(self.task, "sleep") as sleep, \
                        patch.object(self.task, "info_set") as info_set:
                    self.assertTrue(self.task._run_first_trade_accept())  # 完成整套接取流程。
                key_down.assert_called_once_with("shift")  # 打开日历前按住 Shift。
                send_key.assert_called_once_with("c")  # 只发送组合键 C，NPC 步骤不额外按 F。
                key_up.assert_called_once_with("shift", after_sleep=1.0)  # 释放 Shift 并等待一秒。
                self.assertEqual([c.args[:2] for c in click.call_args_list], [(1695, 904), (1814, 138)])  # 验证前往和沙盘点击在全高清下的实际坐标。
                self.assertEqual([c.kwargs["after_sleep"] for c in click.call_args_list], [2.0, 1.0])  # 前往后等待两秒，沙盘点击后等待一秒。
                self.assertEqual(make_box.call_args_list, [  # 校验每一处识别区域。
                    unittest.mock.call(0.041, 0.147, to_x=0.197, to_y=0.290),  # 原第一步之前的已有任务检测。
                    unittest.mock.call(0.002, 0.007, to_x=0.148, to_y=0.069),  # 活动日历标题。
                    unittest.mock.call(0.005, 0.079, to_x=0.322, to_y=0.849),  # 据点贸易活动。
                    unittest.mock.call(0.009, 0.008, to_x=0.219, to_y=0.081),  # 新增阵营沙盘标题区域。
                    unittest.mock.call(0.341, 0.672, to_x=0.657, to_y=0.790),  # 跑商确认弹窗的新区域。
                    unittest.mock.call(0.668, 0.318, to_x=0.823, to_y=0.615),  # 据点总管。
                    unittest.mock.call(0.625, 0.290, to_x=0.951, to_y=0.411),  # 据点贸易对话。
                    unittest.mock.call(914 / 1280, 645 / 720, to_x=1100 / 1280, to_y=702 / 720),  # 接受任务。
                ])  # 完成区域顺序校验。
                self.assertEqual([c.kwargs["match"].pattern for c in ocr.call_args_list], ["据点", "活动日历", "据点贸易|已完成", "阵营沙盘", "确认", "据点|总管", "据点贸易", "接受任务"])  # 验证完成标记与活动入口在同次OCR中检测。
                npc_pattern = ocr.call_args_list[5].kwargs["match"]  # 检查 NPC 任意关键词匹配。
                self.assertIsNotNone(npc_pattern.search("据点"))  # “据点”单独出现也能命中。
                self.assertIsNotNone(npc_pattern.search("总管"))  # “总管”单独出现也能命中。
                expected_clicks = [unittest.mock.call(words[1], after_sleep=1.0)]  # 首先点击活动入口。
                if has_confirmation:  # 有弹窗时点击确认并等待。
                    expected_clicks.append(unittest.mock.call(words[3], after_sleep=40.0))  # 点击后等待四十秒。
                    sleep.assert_not_called()  # 不重复执行四十秒等待。
                else:  # 无弹窗时直接等待。
                    sleep.assert_called_once_with(40.0)  # 确认仍等待四十秒。
                expected_clicks.extend(unittest.mock.call(words[i], after_sleep=1.0) for i in [4, 5, 6])  # 依次点击 NPC、任务对话和接受按钮。
                self.assertEqual(click_box.call_args_list, expected_clicks)  # 验证所有识别框点击顺序。
                info_set.assert_any_call("跑商接取状态", "第一次跑商任务已接取")  # 成功后显示跑商任务状态。

    def test_first_trade_completed_calendar_stops_accept_and_execution(self):  # 验证完成后不会继续接取或启动跑商循环。
        for names in [["已完成"], ["据点贸易", "已完成"]]:  # 覆盖仅完成标记及两者同时识别。
            with self.subTest(names=names):  # 区分不同OCR结果。
                self.task.config = {"接受第一次跑商任务": True, "第一次跑商任务": True}  # 两个开关开启时仍应结束跑商。
                with patch.object(self.task, "_run_huaxialou_checkin"), \
                        patch.object(self.task, "_run_tea_cake_claim"), \
                        patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                        patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                        patch.object(self.task, "send_key_down"), \
                        patch.object(self.task, "send_key"), \
                        patch.object(self.task, "send_key_up"), \
                        patch.object(self.task, "box_of_screen", return_value="region"), \
                        patch.object(self.task, "wait_ocr", side_effect=[[], [SimpleNamespace(name="活动日历")], [SimpleNamespace(name=name) for name in names]]) as ocr, \
                        patch.object(self.task, "click_box") as click_box, \
                        patch.object(self.task, "click_relative") as click_relative, \
                        patch.object(self.task, "_run_first_trade") as trade, \
                        patch.object(self.task, "_run_daxia_until_complete"), \
                        patch.object(self.task, "_return_to_character_selection"), \
                        patch.object(self.task, "info_set") as info_set:
                    self.task.run()  # 从实际日常入口验证接取与执行之间的控制。
                self.assertEqual(ocr.call_count, 3)  # 完成标记后不再识别沙盘或对话。
                click_box.assert_not_called()  # 不点击活动或完成文字。
                click_relative.assert_not_called()  # 不点击前往。
                trade.assert_not_called()  # 不继续执行跑商循环。
                info_set.assert_any_call("跑商接取状态", "跑商已结束")  # 显示用户要求的状态。

    def test_first_trade_missing_required_keyword_stops_without_success(self):
        for missing in [0, 1, 2, 4, 5, 6]:  # 只有可选确认弹窗允许未命中。
            with self.subTest(missing_step=missing):  # 分别覆盖每个必要关键词失败。
                self.task.config = {"接受第一次跑商任务": True}  # 独立开启跑商任务。
                results = [[]] + [[object()] for _ in range(missing)] + [[]]  # 在目标步骤返回未命中。
                with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                        patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                        patch.object(self.task, "send_key_down"), \
                        patch.object(self.task, "send_key_up"), \
                        patch.object(self.task, "send_key"), \
                        patch.object(self.task, "box_of_screen", return_value="region"), \
                        patch.object(self.task, "wait_ocr", side_effect=results) as ocr, \
                        patch.object(self.task, "click_box"), \
                        patch.object(self.task, "click_relative"), \
                        patch.object(self.task, "sleep"), \
                        patch.object(self.task, "info_set") as info_set:
                    self.assertFalse(self.task._run_first_trade_accept())  # 未识别到必要关键词时停止。
                self.assertEqual(ocr.call_count, missing + 2)  # 不继续识别后续步骤。
                self.assertNotIn(unittest.mock.call("跑商接取状态", "第一次跑商任务已接取"), info_set.call_args_list)  # 失败不显示已接取。

    def test_run_calls_first_trade_before_daxia(self):
        self.task.config = {"接受第一次跑商任务": True, "茶馆任务列表": "不选择"}  # 跑商不依赖茶馆下拉选择。
        order = []  # 收集日常执行顺序。
        with patch.object(self.task, "_run_huaxialou_checkin", side_effect=lambda: order.append("checkin")), \
                patch.object(self.task, "_run_tea_cake_claim", side_effect=lambda: order.append("cake")), \
                patch.object(self.task, "_run_first_trade_accept", side_effect=lambda: order.append("trade")), \
                patch.object(self.task, "_run_daxia_until_complete", side_effect=lambda: order.append("daxia")):
            self.task.run()  # 从实际日常入口执行。
        self.assertEqual(order, ["checkin", "cake", "trade", "daxia"])  # 验证跑商已接入主流程。

    def test_first_trade_accept_existing_quest_redirects_before_main_check(self):
        self.task.config = {"接受第一次跑商任务": True, "第一次跑商任务": False}  # 接取开关开启时可以主动跳转到跑商流程。
        with patch.object(self.task, "box_of_screen", return_value="quest") as make_box, \
                patch.object(self.task, "wait_ocr", return_value=[object()]) as ocr, \
                patch.object(self.task, "_ensure_game_foreground") as foreground, \
                patch.object(self.task, "_wait_for_main_interface") as main, \
                patch.object(self.task, "_run_first_trade", return_value=True) as trade:
            self.assertTrue(self.task._run_first_trade_accept())  # 返回跳转后跑商流程的结果。
        make_box.assert_called_once_with(0.041, 0.147, to_x=0.197, to_y=0.290)  # 使用用户指定的任务追踪区域。
        self.assertEqual(ocr.call_args.kwargs["match"].pattern, "据点")  # 仅检查据点关键词。
        trade.assert_called_once_with(force=True)  # 直接跳转不依赖执行开关。
        foreground.assert_not_called()  # 原第一步窗口检查由跳转后的跑商流程处理。
        main.assert_not_called()  # 已有任务时无需返回主界面或打开日历。

    def test_run_does_not_repeat_trade_after_accept_redirect(self):
        self.task.config = {"接受第一次跑商任务": True, "第一次跑商任务": True}  # 两个开关同时开启也只能执行一次。
        with patch.object(self.task, "_run_huaxialou_checkin"), \
                patch.object(self.task, "_run_tea_cake_claim"), \
                patch.object(self.task, "box_of_screen", return_value="quest"), \
                patch.object(self.task, "wait_ocr", return_value=[object()]), \
                patch.object(self.task, "_run_first_trade", return_value=True) as trade, \
                patch.object(self.task, "_run_daxia_until_complete"):
            self.task.run()  # 验证实际入口的分派去重。
        trade.assert_called_once_with(force=True)  # 不再按执行开关重复调用跑商流程。

    def test_first_trade_execution_switch_is_independent_of_accept_switch(self):
        self.task.config = {"接受第一次跑商任务": True, "第一次跑商任务": False}  # 接取开关不会自动开启执行循环。
        with patch.object(self.task, "_ensure_game_foreground") as foreground:
            self.assertFalse(self.task._run_first_trade())  # 独立开关关闭时直接跳过。
        foreground.assert_not_called()  # 不触发窗口前置。

    def test_first_trade_execution_stops_when_foreground_is_unavailable(self):
        self.task.config = {"第一次跑商任务": True}  # 单独开启执行循环。
        with patch.object(self.task, "_ensure_game_foreground", return_value=False), \
                patch.object(self.task, "wait_ocr") as ocr:
            self.assertFalse(self.task._run_first_trade())  # 窗口确认失败时退出。
        ocr.assert_not_called()  # 不识别或点击其他窗口。

    def test_first_trade_execution_loops_and_retries_requested_steps(self):
        scenarios = [  # 覆盖同帧命中NPC、同帧目的地优先、未命中回第一步和镖师分支。
            (["据点", "总管", None, "据点贸易", "交任务", None], []),  # 同帧识别 NPC 后直接进入后续流程。
            ([None, "总管", None, "据点贸易", "交任务", None], []),  # 第一步OCR超时返回None时直接进入第二步。
            ([[], "总管", None, "据点贸易", "交任务", None], []),  # 第一步OCR返回空列表时直接进入第二步。
            (["据点", ["总管", "南屏山"], "确认", "总管", None, "据点贸易", "交任务", None], []),  # 同帧命中时优先处理目的地，再刷新识别NPC。
            (["据点", None, "据点", "总管", None, "据点贸易", "交任务", None], [8.0]),  # 合并OCR未命中时等待并回第一步。
            (["据点", [], "据点", "总管", None, "据点贸易", "交任务", None], [8.0]),  # 空列表和超时返回None均应走未命中重试分支。
            (["据点", "总管", None, None, "日常", "总管", None, "据点贸易", "交任务", None], []),  # 据点贸易未识别时直接返回第一步重新执行。
            (["据点", "总管", "镖师", "据点", "总管", None, "据点贸易", "交任务", None], []),  # 镖师命中后关闭界面并从第一步重试。
        ]  # 完成测试场景定义。
        combined_pattern = re.compile(r"马嵬驿|龙门|洛道|巴陵|南屏山|浩气|据点|总管")  # 定义单次OCR使用的合并关键词。
        destination_pattern = re.compile(r"马嵬驿|龙门|洛道|巴陵|南屏山|浩气")  # 构造目的地筛选规则。
        for value in ["马嵬驿", "龙门", "洛道", "巴陵", "南屏山", "浩气"]:  # 验证目的地关键词均包含在匹配式中。
            self.assertIsNotNone(combined_pattern.search(value))  # 确认关键词未遗漏。
        self.assertIsNotNone(combined_pattern.search("据点"))  # 确认 NPC 关键词据点可命中。
        self.assertIsNotNone(combined_pattern.search("总管"))  # 确认 NPC 关键词总管可命中。
        for values, delays in scenarios:  # 分别验证主要跑商路径。
            with self.subTest(values=values):  # 标记当前流程场景。
                self.task.config = {"第一次跑商任务": True, "接受第一次跑商任务": False}  # 执行流程不依赖接取开关。
                result_words = [  # 将模拟的 OCR 文本转换成文字框。
                    [SimpleNamespace(name=value) for value in item] if isinstance(item, list) else ([SimpleNamespace(name=item)] if item else None)  # 保留真实OCR超时的None以覆盖回归问题。
                    for item in values  # 按各步骤结果构造文字框列表。
                ]  # 完成 OCR 返回值构造。
                with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                        patch.object(self.task, "box_of_screen", side_effect=["quest", "combined", "confirm", "npc", "escort", "trade", "action"]) as make_box, \
                        patch.object(self.task, "wait_ocr", side_effect=result_words) as ocr, \
                        patch.object(self.task, "click_box") as click_box, \
                        patch.object(self.task, "click_relative") as click_relative, \
                        patch.object(self.task, "sleep") as sleep, \
                        patch.object(self.task, "info_set") as info_set:
                    self.assertTrue(self.task._run_first_trade())  # 最后一次未发现接受任务时正常结束。
                self.assertEqual(make_box.call_args_list, [  # 校验合并后的识别区域与其余流程区域。
                    unittest.mock.call(0.041, 0.147, to_x=0.197, to_y=0.290),  # 第一步任务追踪。
                    unittest.mock.call(0.182, 0.174, to_x=0.823, to_y=0.743),  # 同时覆盖目的地及据点总管区域。
                    unittest.mock.call(0.346, 0.678, to_x=0.676, to_y=0.793),  # 目的地后的确认提示区域。
                    unittest.mock.call(0.668, 0.318, to_x=0.823, to_y=0.615),  # 目的地点击后重新识别 NPC。
                    unittest.mock.call(0.625, 0.383, to_x=0.945, to_y=0.515),  # 镖师识别区域。
                    unittest.mock.call(0.621, 0.239, to_x=0.955, to_y=0.386),  # 据点贸易对话区域。
                    unittest.mock.call(0.717, 0.887, to_x=0.877, to_y=0.974),  # 交任务和接受任务区域。
                ])  # 完成区域顺序校验。
                self.assertEqual(ocr.call_args_list[1].kwargs["match"].pattern, combined_pattern.pattern)  # 第二次 OCR 一次匹配目的地与 NPC。
                self.assertEqual(ocr.call_args_list[1].kwargs["box"], "combined")  # 合并 OCR 使用统一区域。
                self.assertEqual(ocr.call_args_list[1].kwargs["time_out"], 2.0)  # 合并检测仍最多等待两秒。
                self.assertEqual(sleep.call_args_list, [unittest.mock.call(delay) for delay in delays])  # 检查未命中时的等待。
                if not values[0]:  # 第一步未命中时不应点击任务追踪或额外等待三秒。
                    self.assertEqual(click_box.call_args_list[0], unittest.mock.call(result_words[1][0], after_sleep=1.0))  # 首次点击直接来自第二步NPC识别结果。
                if not values[1]:  # 合并OCR无结果时应回到任务追踪识别。
                    self.assertEqual(ocr.call_args_list[2].kwargs["box"], "quest")  # 确认等待八秒后重新执行第一步。
                if values[1] == ["总管", "南屏山"]:  # 同时命中两类文字时检查目的地优先。
                    self.assertEqual(click_box.call_args_list[1], unittest.mock.call(result_words[1][1], after_sleep=1.0))  # 先点击目的地而不是旧帧NPC。
                    self.assertEqual(ocr.call_args_list[3].kwargs["box"], "npc")  # 目的地点击后使用新画面识别 NPC。
                if "镖师" in values:  # 镖师命中场景应点击关闭位置。
                    click_relative.assert_called_once_with(0.959, 0.044, after_sleep=1.0)  # 验证镖师分支回到第一步。
                info_set.assert_any_call("第一次跑商状态", "跑商任务结束")  # 正常结束必须显示状态。

    def test_run_executes_trade_after_acceptance_before_daxia(self):
        self.task.config = {"接受第一次跑商任务": True, "第一次跑商任务": True}  # 同时开启两个独立流程。
        order = []  # 记录执行顺序。
        with patch.object(self.task, "_run_huaxialou_checkin"), \
                patch.object(self.task, "_run_tea_cake_claim"), \
                patch.object(self.task, "_run_first_trade_accept", side_effect=lambda: order.append("accept")), \
                patch.object(self.task, "_run_first_trade", side_effect=lambda: order.append("trade")), \
                patch.object(self.task, "_run_daxia_until_complete", side_effect=lambda: order.append("daxia")):
            self.task.run()  # 从日常入口验证流程接线。
        self.assertEqual(order, ["accept", "trade", "daxia"])  # 先接取、再执行跑商、最后大侠之路。

    def test_tea_house_success_follows_calendar_event_and_accept_order(self):
        self.task.config = {"启用茶馆日常": True, "第一次茶馆": True}
        calendar_title, tea_house_entry, confirm, event_title, accept_task = [object() for _ in range(5)]
        events = []
        with patch.object(self.task, "_ensure_game_foreground", side_effect=lambda: events.append("foreground") or True), \
                patch.object(self.task, "_wait_for_main_interface", side_effect=lambda: events.append("main") or object()), \
                patch.object(self.task, "send_key_down", side_effect=lambda key: events.append(("key_down", key))) as key_down, \
                patch.object(self.task, "send_key", side_effect=lambda key, **kwargs: events.append(("key", key, kwargs))) as send_key, \
                patch.object(self.task, "send_key_up", side_effect=lambda key, **kwargs: events.append(("key_up", key, kwargs))) as key_up, \
                patch.object(self.task, "box_of_screen", side_effect=["calendar-title", "calendar-list", "confirm-area", "event-title", "accept-area"]) as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[calendar_title, tea_house_entry, confirm, event_title, accept_task]) as wait_ocr, \
                patch.object(self.task, "click_box", side_effect=lambda box, **kwargs: events.append(("click_box", box, kwargs))) as click_box, \
                patch.object(self.task, "click_relative", side_effect=lambda *args, **kwargs: events.append(("click", args, kwargs))) as click, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_tea_house_daily())

        self.assertEqual(
            events,
            [
                "foreground",
                "main",
                ("key_down", "shift"),
                ("key", "c", {}),
                ("key_up", "shift", {"after_sleep": 1.0}),
                ("click_box", tea_house_entry, {"after_sleep": 1.0}),
                ("click", (1130 / 1280, 603 / 720), {"after_sleep": 1.0}),
                ("click_box", confirm, {"after_sleep": 40.0}),
                ("key", "f", {"after_sleep": 1.0}),
                ("click_box", event_title, {"after_sleep": 1.0}),
                ("click_box", accept_task, {"after_sleep": 1.0}),
            ],
        )
        self.assertEqual(key_down.call_args.args, ("shift",))
        self.assertEqual(key_up.call_args.args, ("shift",))
        self.assertEqual(click.call_args_list[0].args, (1130 / 1280, 603 / 720))
        self.assertEqual(
            [call.kwargs["match"].pattern for call in wait_ocr.call_args_list],
            ["活动日历", "江湖茶馆", "确认", "山城一盏听风雨", "接受任务"],
        )
        self.assertEqual(
            make_box.call_args_list,
            [
                unittest.mock.call(2 / 1280, 1 / 720, width=192 / 1280, height=53 / 720),
                unittest.mock.call(9 / 1280, 8 / 720, width=413 / 1280, height=711 / 720),
                unittest.mock.call(650 / 1280, 541 / 720, width=187 / 1280, height=55 / 720),
                unittest.mock.call(800 / 1280, 205 / 720, width=410 / 1280, height=80 / 720),
                unittest.mock.call(914 / 1280, 645 / 720, width=186 / 1280, height=57 / 720),
            ],
        )

    def test_tea_house_travel_click_scales_for_game_resolution(self):
        for width, height, expected in [(1280, 720, (1130, 603)), (1920, 1080, (1695, 904))]:  # 验证框架按相对坐标缩放并向下取整。
            with self.subTest(resolution=(width, height)):  # 单独报告不同分辨率的测试结果。
                self.task.config = {"茶馆任务列表": "启用茶馆日常"}  # 启用茶馆日常任务。
                with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                        patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                        patch.object(self.task, "send_key_down"), \
                        patch.object(self.task, "send_key"), \
                        patch.object(self.task, "send_key_up"), \
                        patch.object(self.task, "box_of_screen", return_value="region"), \
                        patch.object(self.task, "wait_ocr", side_effect=[[object()], [object()], [object()], [object()], [object()]]), \
                        patch.object(self.task, "click_box"), \
                        patch.object(self.task, "out_of_ratio", return_value=False), \
                        patch.object(type(self.task), "width", new_callable=PropertyMock, return_value=width), \
                        patch.object(type(self.task), "height", new_callable=PropertyMock, return_value=height), \
                        patch.object(self.task, "click") as click:
                    self.assertTrue(self.task._run_tea_house_daily())  # 执行完整接取流程并保留真实相对坐标转换。
                self.assertEqual(click.call_args.args[:2], expected)  # 验证前往按钮点击的实际像素位置。
                self.assertEqual(click.call_args.kwargs["after_sleep"], 1.0)  # 保持点击后一秒等待。

    def test_tea_house_waits_40_seconds_without_confirmation(self):
        self.task.config = {"启用茶馆日常": True, "第一次茶馆": True}
        calendar_title, tea_house_entry, event_title, accept_task = [object() for _ in range(4)]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                patch.object(self.task, "send_key_down"), \
                patch.object(self.task, "send_key"), \
                patch.object(self.task, "send_key_up"), \
                patch.object(self.task, "box_of_screen", return_value="ocr-region"), \
                patch.object(self.task, "wait_ocr", side_effect=[calendar_title, tea_house_entry, [], event_title, accept_task]), \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "click_relative") as click, \
                patch.object(self.task, "sleep") as sleep, \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_tea_house_daily())

        self.assertEqual(click.call_args_list[0], unittest.mock.call(1130 / 1280, 603 / 720, after_sleep=1.0))
        self.assertEqual(click_box.call_count, 3)
        sleep.assert_called_once_with(40.0)

    def test_tea_house_restarts_at_first_step_when_tea_keyword_is_missing(self):
        first_complete, second_complete, tea_keyword, tasting_keyword, accept_keyword = [object() for _ in range(5)]
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "box_of_screen", return_value="ocr-region"), \
                patch.object(self.task, "wait_ocr", side_effect=[first_complete, [], second_complete, tea_keyword, tasting_keyword, accept_keyword]), \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep"), \
                patch.object(self.task, "info_set"), \
                patch.object(self.task, "log_info"):
            self.assertTrue(self.task._run_tea_house_followup_steps())

        self.assertEqual(
            click.call_args_list,
            [
                unittest.mock.call(150, 147, after_sleep=5.0),
                unittest.mock.call(150, 147, after_sleep=5.0),
            ],
        )
        self.assertEqual(click_box.call_count, 3)

    def test_tea_house_stops_if_calendar_title_is_not_found(self):
        self.task.config = {"启用茶馆日常": True}
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                patch.object(self.task, "send_key_down"), \
                patch.object(self.task, "send_key"), \
                patch.object(self.task, "send_key_up"), \
                patch.object(self.task, "box_of_screen", return_value="calendar-title"), \
                patch.object(self.task, "wait_ocr", return_value=[]) as wait_ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "log_warning"):
            self.assertFalse(self.task._run_tea_house_daily())

        self.assertEqual(wait_ocr.call_count, 1)
        click_box.assert_not_called()
        click.assert_not_called()
        info_set.assert_any_call("茶馆日常状态", "未识别到活动日历")

    def test_tea_house_stops_if_accept_task_is_not_found(self):
        self.task.config = {"启用茶馆日常": True}
        recognized = [object(), object(), object()]
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "_wait_for_main_interface", return_value=object()), \
                patch.object(self.task, "send_key_down"), \
                patch.object(self.task, "send_key"), \
                patch.object(self.task, "send_key_up"), \
                patch.object(self.task, "box_of_screen", side_effect=["calendar-title", "calendar-list", "confirm-area", "event-title", "accept-area"]), \
                patch.object(self.task, "wait_ocr", side_effect=[recognized[0], recognized[1], [], recognized[2], []]), \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "click_relative") as click, \
                patch.object(self.task, "sleep") as sleep, \
                patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "log_warning"):
            self.assertFalse(self.task._run_tea_house_daily())

        self.assertEqual(click_box.call_count, 2)
        click.assert_called_once_with(1130 / 1280, 603 / 720, after_sleep=1.0)
        sleep.assert_called_once_with(40.0)
        info_set.assert_any_call("茶馆日常状态", "未识别到接受任务")

    def test_daxia_flow_returns_to_main_and_repeats_until_completed(self):
        self.task.config = {"启用大侠之路检测": True}
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "_check_daxia_road_progress", side_effect=[False, False, True]) as check, \
                patch.object(self.task, "_wait_for_main_interface", side_effect=[None, np.zeros((720, 1280, 3), dtype=np.uint8)]) as wait_main, \
                patch.object(self.task, "sleep") as sleep:
            self.assertTrue(self.task._run_daxia_until_complete())

        self.assertEqual(check.call_count, 3)
        self.assertEqual(wait_main.call_count, 2)
        self.assertEqual(sleep.call_args_list, [unittest.mock.call(1.0), unittest.mock.call(1.0)])

    def test_huaxialou_checkin_opens_with_n_then_clicks_center_when_unfinished(self):
        self.task.config = {}
        first_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        first_frame[37:45, 90:112] = (0, 0, 255)
        first_frame[123, 246] = (0, 0, 221)
        second_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        second_frame[123, 246] = (0, 0, 221)
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "next_frame", side_effect=[first_frame, first_frame, second_frame]), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "sleep") as sleep, \
                patch.object(self.task, "click_relative") as click_center, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "_check_daxia_road_progress") as check_daxia:
            self.assertTrue(self.task._run_huaxialou_checkin())

        send_key.assert_called_once_with("n", after_sleep=1.0)
        self.assertEqual(click_center.call_args_list[0].args, (0.5, 0.5))
        self.assertEqual(click_center.call_args_list[1].args, (0.5, 0.75))
        self.assertEqual(click_center.call_count, 2)
        sleep.assert_called_once_with(5.0)
        check_daxia.assert_not_called()

    def test_huaxialou_checkin_opens_with_n_then_escapes_when_completed(self):
        self.task.config = {}
        check_in_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        check_in_frame[37:45, 90:112] = (0, 0, 255)
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "next_frame", side_effect=[check_in_frame, check_in_frame]), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "click_relative") as click_center, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "_check_daxia_road_progress") as check_daxia:
            self.assertFalse(self.task._run_huaxialou_checkin())

        click_center.assert_not_called()
        self.assertEqual(send_key.call_args_list[0].args, ("n",))
        self.assertEqual(send_key.call_args_list[1].args, ("esc",))
        check_daxia.assert_not_called()

    def test_huaxialou_checkin_r_value_equal_to_220_is_completed(self):
        self.task.config = {}
        check_in_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        check_in_frame[37:45, 90:112] = (0, 0, 255)
        check_in_frame[123, 246] = (0, 0, 220)
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "next_frame", side_effect=[check_in_frame, check_in_frame]), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "click_relative") as click_center, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "info_set") as info_set, \
                patch.object(self.task, "_check_daxia_road_progress") as check_daxia:
            self.assertFalse(self.task._run_huaxialou_checkin())

        info_set.assert_any_call("日常签到状态", "日常签到已完成")
        click_center.assert_not_called()
        self.assertEqual(send_key.call_args_list[0].args, ("n",))
        self.assertEqual(send_key.call_args_list[1].args, ("esc",))
        check_daxia.assert_not_called()

    def test_main_interface_detection_requires_r_strictly_over_160(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[37, 90] = (0, 0, 160)
        with patch.object(self.task, "ocr", return_value=[]) as ocr:
            self.assertFalse(self.task._is_main_interface(frame))
            ocr.assert_not_called()
            frame[37, 90] = (0, 0, 161)
            self.assertTrue(self.task._is_main_interface(frame))
        ocr.assert_called_once_with(x=805 / 1280, y=209 / 720, width=75, height=36, match=ANY, frame=frame)
        self.assertIsNotNone(ocr.call_args.kwargs["match"].search("角色"))

    def test_main_interface_detection_rejects_role_text(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[37, 90] = (0, 0, 200)
        with patch.object(self.task, "ocr", return_value=[object()]):
            self.assertFalse(self.task._is_main_interface(frame))

    def test_main_interface_detection_scales_pixel_and_role_region(self):
        for width, height, pixel, region in [
            (1920, 1080, (135, 56), (1208, 314, 112, 54)),
            (2560, 1440, (180, 74), (1610, 418, 150, 72)),
        ]:
            with self.subTest(resolution=(width, height)):
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                frame[pixel[1], pixel[0]] = (0, 0, 161)
                with patch.object(self.task, "ocr", return_value=[]) as ocr:
                    self.assertTrue(self.task._is_main_interface(frame))
                x, y, w, h = region
                ocr.assert_called_once_with(x=x / width, y=y / height, width=w, height=h, match=ANY, frame=frame)

    def test_main_interface_detection_rejects_invalid_frame_without_ocr(self):
        with patch.object(self.task, "ocr") as ocr:
            self.assertFalse(self.task._is_main_interface(None))
        ocr.assert_not_called()

    def test_main_interface_retry_sends_esc_and_waits_two_seconds(self):
        invalid = np.zeros((720, 1280, 3), dtype=np.uint8)
        valid = invalid.copy()
        valid[37, 90] = (0, 0, 161)  # 重试后的截图通过R值检测。
        with patch.object(self.task, "next_frame", side_effect=[invalid, valid]), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "sleep") as sleep:
            self.assertIs(self.task._wait_for_main_interface(attempts=2), valid)
        send_key.assert_called_once_with("esc", after_sleep=2.0)
        sleep.assert_not_called()

    def test_main_interface_retry_stops_at_attempt_limit(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(self.task, "next_frame", return_value=frame) as next_frame, \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key:
            self.assertIsNone(self.task._wait_for_main_interface(attempts=2))
        self.assertEqual(next_frame.call_count, 2)
        self.assertEqual(send_key.call_args_list, [unittest.mock.call("esc", after_sleep=2.0)] * 2)

    def test_tea_cake_pixel_rgb_reader(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[261, 1173] = (58, 94, 229)
        self.assertEqual(DailyChecklistTask._sample_pixel_rgb(frame, 1173, 261), (229, 94, 58))

    def test_tea_cake_claimed_path_escapes_and_confirms_main(self):
        main = np.zeros((720, 1280, 3), dtype=np.uint8)
        main[37:45, 90:112] = (0, 0, 255)
        page = main.copy()
        page[261, 1173] = (0, 0, 0)
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "next_frame", side_effect=[main, page, main]), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "info_set") as info_set:
            self.assertFalse(self.task._run_tea_cake_claim())
        self.assertEqual(send_key.call_count, 2)
        info_set.assert_any_call("茶饼状态", "茶饼已领")

    def test_tea_cake_unclaimed_claims_red_dust_shadow(self):
        main = np.zeros((720, 1280, 3), dtype=np.uint8)
        main[37:45, 90:112] = (0, 0, 255)
        page = main.copy()
        page[261, 1173] = (58, 94, 229)
        final = main.copy()
        with patch.object(self.task, "_ensure_game_foreground", return_value=True), \
                patch.object(self.task, "next_frame", side_effect=[main, page, final]), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [object()]]), \
                patch.object(self.task, "box_of_screen", side_effect=["hero", "claim"]), \
                patch.object(self.task, "info_set") as info_set:
            self.assertTrue(self.task._run_tea_cake_claim())
        self.assertEqual(click.call_args_list[0].args, (1124, 288))
        self.assertEqual(click.call_args_list[1].args, (1121, 670))
        self.assertEqual(send_key.call_count, 2)
        info_set.assert_any_call("茶饼状态", "茶饼未领")

    def test_daxia_road_reports_incomplete_when_100_is_missing(self):
        self.task.config = {"启用大侠之路检测": True}
        with patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "_is_daxia_road_page", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="progress-box") as make_box, \
                patch.object(self.task, "wait_ocr", return_value=[]), \
                patch.object(self.task, "next_frame", return_value=np.zeros((720, 1280, 3), dtype=np.uint8)), \
                patch.object(self.task, "info_set") as info_set:
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(send_key.call_args_list[0].args, ("h",))
        self.assertEqual(send_key.call_args_list[1].args, ("esc",))
        self.assertEqual(make_box.call_args.args, (617 / 1280, 617 / 720))
        info_set.assert_any_call("大侠之路状态", "大侠之路未完成")

    def test_daxia_road_reports_completed_when_100_is_found(self):
        self.task.config = {"启用大侠之路检测": True}
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        frame[969, 1456] = (149, 255, 149)
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "_is_daxia_road_page", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["progress", "completion"]), \
                patch.object(self.task, "wait_ocr", return_value=[object()]), \
                patch.object(self.task, "next_frame", return_value=frame), \
                patch.object(self.task, "info_set") as info_set:
            self.assertTrue(self.task._check_daxia_road_progress())

        info_set.assert_any_call("大侠之路状态", "大侠之路已完成")

    def test_daxia_road_processes_keyword_after_retry_and_rechecks_page(self):
        marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker[205, 600] = (255, 247, 216)
        with patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "_is_daxia_road_page", side_effect=[True, True]), \
                patch.object(self.task, "box_of_screen", return_value="task") as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [], [object()]]), \
                patch.object(self.task, "next_frame", return_value=marker), \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep") as sleep:
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(click.call_args_list[0].args, (600, 215))
        self.assertEqual(click.call_args_list[1].args, (530, 360))
        self.assertEqual(click.call_count, 2)
        self.assertEqual(make_box.call_args.args, (450 / 1280, 495 / 720))
        self.assertEqual(make_box.call_args.kwargs, {"width": 174 / 1280, "height": 48 / 720})
        send_key.assert_any_call("h", after_sleep=1.0)
        send_key.assert_any_call("esc", after_sleep=1.0)
        sleep.assert_called_once_with(5.0)

    def test_daxia_marker_checks_second_pixel_only_after_first_misses(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[205, 600] = (0, 0, 0)  # BGR 对应的 RGB 不匹配指定颜色。
        frame[205, 800] = (255, 247, 216)  # BGR 对应目标 RGB (216,247,255)。
        self.assertTrue(DailyChecklistTask._is_daxia_retry_marker(frame))

    def test_daxia_marker_returns_false_when_both_pixels_miss(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertFalse(DailyChecklistTask._is_daxia_retry_marker(frame))

    def test_first_daxia_marker_uses_online_keyword_region_and_retry_click(self):
        marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker[205, 400] = (255, 247, 216)
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "_is_daxia_road_page", side_effect=[True, True]), \
                patch.object(self.task, "box_of_screen", return_value="task") as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [], [object()]]), \
                patch.object(self.task, "next_frame", return_value=marker), \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep"):
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(click.call_args_list[0].args, (400, 215))
        self.assertEqual(click.call_count, 2)
        self.assertEqual(click.call_args_list[1].args, (330, 360))
        self.assertEqual(make_box.call_args.args, (250 / 1280, 495 / 720))
        self.assertEqual(make_box.call_args.kwargs, {"width": 174 / 1280, "height": 48 / 720})

    def test_second_daxia_marker_uses_updated_keyword_region_and_retry_click(self):
        marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker[205, 600] = (255, 247, 216)
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "_is_daxia_road_page", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="task") as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [], [SimpleNamespace(name="沙盘")]]) as wait_ocr, \
                patch.object(self.task, "next_frame", return_value=marker), \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep"):
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(click.call_args_list[0].args, (600, 215))
        self.assertEqual(click.call_args_list[1].args, (530, 360))
        self.assertEqual(make_box.call_args.args, (450 / 1280, 495 / 720))
        self.assertEqual(make_box.call_args.kwargs, {"width": 174 / 1280, "height": 48 / 720})
        self.assertEqual(wait_ocr.call_args_list[1].kwargs["match"].pattern, "(在线|一分钟|沙盘|外观|奇遇|茶饼|好友装备)")

    def test_third_daxia_marker_uses_its_own_keyword_region_and_retry_click(self):
        marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker[205, 1000] = (255, 247, 216)
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "_is_daxia_road_page", side_effect=[True, True]), \
                patch.object(self.task, "box_of_screen", return_value="task") as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [], [object()]]), \
                patch.object(self.task, "next_frame", return_value=marker), \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep"):
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(click.call_args_list[0].args, (1000, 215))
        self.assertEqual(click.call_count, 2)
        self.assertEqual(click.call_args_list[1].args, (930, 360))
        self.assertEqual(make_box.call_args.args, (850 / 1280, 495 / 720))
        self.assertEqual(make_box.call_args.kwargs, {"width": 174 / 1280, "height": 48 / 720})

    def test_fifth_daxia_marker_uses_tea_keyword_region_and_retry_click(self):
        marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker[205, 1200] = (255, 247, 216)
        self.task.config = {"Daxia Road Retry Limit": 1}
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "_is_daxia_road_page", side_effect=[True, True]), \
                patch.object(self.task, "box_of_screen", return_value="task") as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [], [SimpleNamespace(name="茶饼")]]), \
                patch.object(self.task, "next_frame", return_value=marker), \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep"):
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(click.call_count, 1)
        self.assertEqual(click.call_args.args, (1200, 215))
        self.assertEqual(make_box.call_args.args, (1050 / 1280, 495 / 720))
        self.assertEqual(make_box.call_args.kwargs, {"width": 174 / 1280, "height": 48 / 720})

    def test_detected_tea_keyword_returns_to_pixel_detection(self):
        tea_marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        tea_marker[205, 1200] = (255, 247, 216)
        no_marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.task.config = {"Daxia Road Retry Limit": 2}
        with patch.object(self.task, "send_key"), \
                patch.object(self.task, "_is_daxia_road_page", return_value=True), \
                patch.object(self.task, "box_of_screen", side_effect=["progress1", "task", "progress2"]), \
                patch.object(self.task, "wait_ocr", side_effect=[[], [SimpleNamespace(name="茶饼")], []]) as wait_ocr, \
                patch.object(self.task, "next_frame", side_effect=[tea_marker, no_marker]) as next_frame, \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep"):
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(next_frame.call_count, 2)
        self.assertIn("茶饼", wait_ocr.call_args_list[1].kwargs["match"].pattern)
        click.assert_not_called()

    def test_tea_keyword_is_included_for_first_four_detection_branches(self):
        markers = [400, 600, 1000]
        expected_patterns = ["茶饼", "茶饼", "茶饼"]
        for x, expected in zip(markers, expected_patterns):
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame[205, x] = (255, 247, 216)
            self.task.config = {"Daxia Road Retry Limit": 1}
            with patch.object(self.task, "send_key"), \
                    patch.object(self.task, "_is_daxia_road_page", side_effect=[True, True]), \
                patch.object(self.task, "box_of_screen", return_value="task"), \
                patch.object(self.task, "wait_ocr", side_effect=[[], [SimpleNamespace(name="茶饼")]]) as wait_ocr, \
                    patch.object(self.task, "next_frame", return_value=frame), \
                    patch.object(self.task, "click") as click, \
                    patch.object(self.task, "sleep"):
                self.assertFalse(self.task._check_daxia_road_progress())
            self.assertIn(expected, wait_ocr.call_args_list[1].kwargs["match"].pattern)
            click.assert_not_called()

    def test_friend_equipment_clicks_stage_action_then_followup_and_restarts(self):
        marker = np.zeros((720, 1280, 3), dtype=np.uint8)
        marker[205, 600] = (255, 247, 216)
        self.task.config = {"Daxia Road Retry Limit": 1}
        with patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "_is_daxia_road_page", return_value=True), \
                patch.object(self.task, "box_of_screen", return_value="task") as make_box, \
                patch.object(self.task, "wait_ocr", side_effect=[[object()], [SimpleNamespace(name="好友装备")]]) as wait_ocr, \
                patch.object(self.task, "next_frame", return_value=marker), \
                patch.object(self.task, "click") as click, \
                patch.object(self.task, "sleep") as sleep:
            self.assertFalse(self.task._check_daxia_road_progress())

        self.assertEqual(click.call_args_list[0].args, (530, 360))
        self.assertEqual(click.call_args_list[1].args, (300, 260))
        self.assertEqual(sleep.call_args_list[0].args, (5.0,))
        self.assertEqual(sleep.call_args_list[1].args, (2.0,))
        send_key.assert_any_call("esc", after_sleep=1.0)
        self.assertIn("好友装备", wait_ocr.call_args.kwargs["match"].pattern)
        self.assertEqual(make_box.call_args.args, (450 / 1280, 495 / 720))

    def test_daxia_task_retry_action_and_friend_clicks_scale_with_resolution(self):
        for width, height in [(1280, 720), (1920, 1080)]:  # 覆盖基准分辨率和用户指定的全高清分辨率。
            for marker_x, action_x in [(400, 330), (600, 530), (800, 730), (1000, 930), (1200, 1130)]:  # 验证五个阶段的点击位置。
                with self.subTest(resolution=(width, height), stage=marker_x):  # 单独报告失败的分辨率和阶段。
                    frame = np.zeros((height, width, 3), dtype=np.uint8)  # 构造当前分辨率的截图。
                    frame[round(205 * height / 720), round(marker_x * width / 1280)] = (255, 247, 216)  # 在缩放后的颜色点写入目标 BGR。
                    self.task.config = {"启用大侠之路检测": True}  # 开启本次检测，避免其他测试配置影响。
                    with patch.object(self.task, "send_key"), \
                            patch.object(self.task, "_is_daxia_road_page", return_value=True), \
                            patch.object(self.task, "box_of_screen", return_value="region"), \
                            patch.object(self.task, "wait_ocr", side_effect=[[], [], [SimpleNamespace(name="好友装备")]]), \
                            patch.object(self.task, "next_frame", return_value=frame), \
                            patch.object(self.task, "click") as click, \
                            patch.object(self.task, "sleep"):
                        self.assertFalse(self.task._check_daxia_road_progress())  # 完成当前任务后应返回继续下一轮。
                    self.assertEqual(click.call_args_list, [  # 验证重试、任务及好友装备点击均使用实际画面坐标。
                        unittest.mock.call(round(marker_x * width / 1280), round(215 * height / 720), after_sleep=0.5),  # 关键词未命中时点击阶段顶部。
                        unittest.mock.call(round(action_x * width / 1280), round(360 * height / 720), after_sleep=0),  # 关键词命中后点击当前任务。
                        unittest.mock.call(round(300 * width / 1280), round(260 * height / 720), after_sleep=0),  # 点击好友装备的后续位置。
                    ])  # 完成三次点击的顺序和坐标校验。

    def test_check_in_red_value_reads_requested_pixel(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[123, 246] = (0, 0, 221)
        self.assertEqual(DailyChecklistTask._get_check_in_red_value(frame), 221)

    def test_check_in_red_value_scales_coordinates_for_other_resolution(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
        frame[246, 492] = (0, 0, 230)
        self.assertEqual(DailyChecklistTask._get_check_in_red_value(frame), 230)


if __name__ == "__main__":
    unittest.main()
