import re  # 导入正则模块，用于匹配“花萼楼”和“大侠之路”。
import time  # 导入时间模块，用于防止重复触发按键。

from ok import TriggerTask  # 导入 ok-script 的循环触发任务基类。


class DaxiaRoadTriggerTask(TriggerTask):  # 定义持续检测并打开大侠之路的任务。
    def __init__(self, *args, **kwargs):  # 初始化循环任务配置和运行状态。
        super().__init__(*args, **kwargs)  # 初始化 ok-script 的触发任务环境。
        self.name = "花萼楼进入大侠之路"  # 设置任务列表显示名称。
        self.description = "持续检测“花萼楼”，发现后置前台并按 H 打开大侠之路。"  # 设置任务说明。
        self.trigger_interval = 1.0  # 每秒最多检查一次，避免高频 OCR。
        self._cooldown_until = 0.0  # 初始化按键后的冷却结束时间。
        self.default_config.update({  # 增加循环任务的可配置项。
            "检测超时": 0.5,  # 设置单次 OCR 检测最长等待时间。
            "按键冷却": 5.0,  # 设置按 H 后的最短再次触发间隔。
        })  # 完成默认配置更新。
        self.config_description.update({  # 增加配置项说明。
            "检测超时": "每次循环查找“花萼楼”的最长 OCR 等待时间，单位为秒。",  # 说明检测超时配置。
            "按键冷却": "按 H 后等待多少秒再允许下一次触发，单位为秒。",  # 说明按键冷却配置。
        })  # 完成配置说明更新。

    def _ensure_game_foreground(self):  # 将游戏置前并确认输入目标仍是游戏窗口。
        foreground = self.wait_until(lambda: bool(self.hwnd and self.hwnd.is_foreground()), time_out=3, pre_action=self.ensure_in_front, raise_if_not_found=False)  # 尝试置前并轮询前台状态。
        if not foreground:  # 判断窗口是否仍未进入前台。
            self.log_warning("游戏窗口未进入前台。")  # 记录前台状态失败。
        return bool(foreground)  # 返回前台确认结果。

    def run(self):  # 执行一次循环检测。
        now = time.monotonic()  # 获取当前单调时间。
        if now < self._cooldown_until:  # 如果仍处于按键冷却期，就跳过本轮检测。
            return False  # 返回未触发，让循环继续运行。
        if not self._ensure_game_foreground():  # 首次检测前确认游戏窗口处于前台。
            self.log_warning("本轮跳过 OCR 检测。")  # 记录本轮跳过原因。
            return False  # 等待下一轮重新尝试。
        detected = self.wait_ocr(match=re.compile("花萼楼"), time_out=float(self.config.get("检测超时", 0.5)), raise_if_not_found=False)  # OCR 检查当前界面是否出现“花萼楼”。
        if not detected:  # 如果当前界面没有目标文字，就等待下一轮检测。
            return False  # 返回未触发，让循环继续运行。
        if not self._ensure_game_foreground():  # OCR 完成后再次确认前台，防止检测期间焦点发生变化。
            self.log_warning("检测到“花萼楼”，但游戏窗口失去前台，本轮不发送 H。")  # 记录按键跳过原因。
            return False  # 等待下一轮重新尝试。
        self.log_info("检测到“花萼楼”，按 H 进入大侠之路。")  # 记录检测成功。
        self.send_key("h", after_sleep=0.5)  # 按下 H 并等待页面切换。
        self._cooldown_until = time.monotonic() + max(1.0, float(self.config.get("按键冷却", 5.0)))  # 设置按键后的冷却时间。
        page = self.wait_ocr(match=re.compile("大侠之路"), time_out=5, raise_if_not_found=False)  # 等待确认已经进入大侠之路页面。
        if page:  # 如果 OCR 识别到了大侠之路页面。
            self.log_info("已进入大侠之路页面。")  # 记录进入页面成功。
        else:  # 如果暂时没有识别到页面标题。
            self.log_warning("已发送 H，但 5 秒内未识别到“大侠之路”。")  # 记录页面确认超时。
        return True  # 返回已处理，交给执行器继续循环调度。
