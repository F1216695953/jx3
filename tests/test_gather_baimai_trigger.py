import re  # 导入正则模块，用于验证 OCR 匹配规则。
import unittest  # 导入单元测试框架。
from unittest.mock import call, patch  # 导入 mock 工具以隔离游戏输入并检查调用顺序。

from ok.test.TaskTestCase import TaskTestCase  # 导入项目任务测试基类。

from src.config import config as app_config  # 导入应用配置供测试环境初始化。
from src.tasks.GatherBaimaiTriggerTask import GatherBaimaiTriggerTask  # 导入待测循环任务。


class GatherBaimaiTriggerTaskTests(TaskTestCase):  # 定义采集任务测试集。
    task_class = GatherBaimaiTriggerTask  # 指定本测试使用的任务类。
    config = app_config  # 使用项目默认应用配置。

    def setUp(self):  # 在每个用例前重置任务运行状态。
        super().setUp()  # 初始化 TaskTestCase 环境。
        self.task._next_key_at = 0.0  # 清除上个用例留下的按键时间。
        self.task.config["每0.5秒按F"] = False  # 重置开关，避免测试间共享配置状态。

    def test_task_is_registered_as_a_separately_toggleable_trigger(self):  # 验证任务可独立启停。
        self.assertEqual(self.task.name, "采集")  # 确认任务显示名称。
        self.assertEqual(self.task.trigger_interval, 0.2)  # 确认每 0.2 秒轮询一次。
        self.assertFalse(self.task.default_config["_enabled"])  # 确认任务默认关闭。
        self.assertFalse(self.task.default_config["每0.5秒按F"])  # 确认周期按 F 开关默认关闭。

    def test_enabled_f_switch_presses_f_once_per_poll(self):  # 验证启用后每轮触发都按一次 F。
        self.task.config["每0.5秒按F"] = True  # 开启每轮按 F。
        with patch.object(self.task, "box_of_screen", return_value="region"), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key, \
                patch("src.tasks.GatherBaimaiTriggerTask.time.monotonic", return_value=10.0):
            self.task.run()  # 执行一轮采集检测。

        self.assertEqual(send_key.call_args_list, [call("f"), call("1")])  # 确认本轮按 F 且原有按 1 行为保留。

    def test_detected_baimai_is_clicked_without_blocking_next_poll(self):  # 验证识别成功后不阻塞下一轮轮询。
        match = object()  # 构造一个模拟 OCR 结果框。
        with patch.object(self.task, "box_of_screen", return_value="region") as box_of_screen, \
                patch.object(self.task, "ocr", return_value=[match]) as ocr, \
                patch.object(self.task, "click_box") as click_box, \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "log_info"), \
                patch("src.tasks.GatherBaimaiTriggerTask.time.monotonic", return_value=10.0):
            self.assertTrue(self.task.run())  # 执行一轮并验证成功返回。

        box_of_screen.assert_called_once_with(0.673, 0.332, to_x=0.823, to_y=0.567)  # 验证 OCR 区域坐标。
        self.assertIs(ocr.call_args.kwargs["box"], "region")  # 确认 OCR 使用指定区域。
        self.assertEqual(ocr.call_args.kwargs["match"].pattern, "百脉")  # 确认 OCR 关键词。
        click_box.assert_called_once_with(match)  # 确认点击首个识别框且不等待五秒。
        send_key.assert_not_called()  # 命中百脉时本轮不发送 F 或 1。

    def test_enabled_f_switch_does_not_press_f_when_baimai_is_detected(self):  # 验证识别到百脉后停止按键。
        self.task.config["每0.5秒按F"] = True  # 开启每轮按 F 的开关。
        with patch.object(self.task, "box_of_screen", return_value="region"), \
                patch.object(self.task, "ocr", return_value=[object()]), \
                patch.object(self.task, "click_box"), \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "log_info"), \
                patch("src.tasks.GatherBaimaiTriggerTask.time.monotonic", return_value=10.0):
            self.assertTrue(self.task.run())  # 执行一轮并命中目标文字。
        send_key.assert_not_called()  # 命中后不会再发出 F 或 1。

    def test_missing_baimai_presses_one_immediately(self):  # 验证未识别时按键 1。
        with patch.object(self.task, "box_of_screen", return_value="region"), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key, \
                patch.object(self.task, "click_box") as click_box, \
                patch("src.tasks.GatherBaimaiTriggerTask.time.monotonic", side_effect=[10.0, 10.0]):
            self.assertFalse(self.task.run())  # 执行一轮并验证没有识别到目标。

        send_key.assert_called_once_with("1")  # 确认未识别到时按下 1。
        click_box.assert_not_called()  # 确认未识别时不点击。

    def test_missing_baimai_does_not_press_one_before_two_seconds(self):  # 验证按键间隔不少于两秒。
        self.task._next_key_at = 12.0  # 设置下一次按键时间为未来两秒。
        with patch.object(self.task, "box_of_screen", return_value="region"), \
                patch.object(self.task, "ocr", return_value=[]), \
                patch.object(self.task, "send_key") as send_key, \
                patch("src.tasks.GatherBaimaiTriggerTask.time.monotonic", return_value=10.0):
            self.assertFalse(self.task.run())  # 执行一轮空检测。

        send_key.assert_not_called()  # 确认未满一秒时不会重复按键。


if __name__ == "__main__":  # 判断是否直接运行本测试文件。
    unittest.main()  # 启动单元测试执行器。
