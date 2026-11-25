import re  # 导入正则模块，用于匹配“百脉”。
import time  # 导入单调时钟，用于控制按键间隔。

from ok import TriggerTask  # 导入可独立启停并循环运行的任务基类。


class GatherBaimaiTriggerTask(TriggerTask):  # 定义独立循环采集任务。
    def __init__(self, *args, **kwargs):  # 初始化任务名称和循环间隔。
        super().__init__(*args, **kwargs)  # 初始化触发任务基类。
        self.name = "采集"  # 设置任务列表中的显示名称。
        self.description = "每 0.2 秒持续识别指定区域；未识别到时每 2 秒按 1，识别到后点击并继续识别。"  # 说明任务行为。
        self.trigger_interval = 0.2  # 每 0.2 秒尝试触发一次 OCR 检查。
        self.default_config.update({"每0.5秒按F": False})  # 增加默认关闭的周期按 F 开关。
        self.config_description.update({"每0.5秒按F": "开启后，每轮 0.2 秒检测时额外按一次 F。"})  # 说明周期按 F 开关。
        self._next_key_at = 0.0  # 初始化下一次按键的允许时间。

    def run(self):  # 执行一轮 OCR 检测。
        target_region = self.box_of_screen(0.673, 0.332, to_x=0.823, to_y=0.567)  # 转换指定区域为当前屏幕坐标框。
        baimai = self.ocr(  # 在本轮触发时检查目标区域一次。
            box=target_region,  # 限定 OCR 检测范围。
            match=re.compile(r"百脉"),  # 匹配包含“百脉”的文字。
        )  # 完成本轮 OCR 检测。
        if not baimai:  # 如果本轮没有识别到“百脉”。
            if self.config.get("每0.5秒按F", False):  # 未识别到目标且开关开启时才按 F。
                self.send_key("f")  # 每次未命中的检测轮按一次 F。
            now = time.monotonic()  # 读取当前单调时间，避免系统时间调整影响节奏。
            if now >= self._next_key_at:  # 到达下一次按键时间时发送按键。
                self.send_key("1")  # 未识别到目标时按下数字 1。
                self._next_key_at = time.monotonic() + 2.0  # 安排两秒后再次允许按键。
            return False  # 返回未处理状态，保持触发任务继续运行。
        self.log_info("识别到‘百脉’，点击对应 OCR 位置。")  # 记录成功识别状态。
        self.click_box(baimai[0])  # 点击首个识别框后立即返回，使下一轮仍按半秒间隔识别。
        self._next_key_at = time.monotonic() + 2.0  # 点击后留出两秒再允许恢复按键。
        return True  # 返回本轮已处理。
