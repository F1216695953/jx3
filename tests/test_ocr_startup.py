import unittest  # 提供真实 OCR 启动和推理检查。

import cv2  # 在测试图片上绘制固定文字。
import numpy as np  # 创建测试图片。
from onnxocr.onnx_paddleocr import ONNXPaddleOcr  # 使用安装包实际调用的 OCR 引擎。

from src.config import config  # 使用应用实际的 OCR 参数。


class OCRStartupTests(unittest.TestCase):  # 验证模型真实初始化及识别而非模拟返回值。
    def test_cpu_backend_initializes_and_recognizes_text(self):  # 覆盖已报告的启动失败路径。
        params = config['ocr']['params']  # 读取实际后端选择。
        self.assertFalse(params['use_openvino'])  # 确认不走已崩溃的 OpenVINO 路径。
        self.assertFalse(params['use_npu'])  # 确认不探测 NPU。
        engine = ONNXPaddleOcr(use_angle_cls=False, **params)  # 实际加载检测和识别模型。
        self.assertEqual(engine.text_detector.session.get_providers(), ['CPUExecutionProvider'])  # 确认检测模型只使用 CPU。
        self.assertEqual(engine.text_recognizer.session.get_providers(), ['CPUExecutionProvider'])  # 确认识别模型只使用 CPU。
        frame = np.full((160, 640, 3), 255, dtype=np.uint8)  # 创建白色测试背景。
        cv2.putText(frame, 'okscript', (24, 110), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 0, 0), 5, cv2.LINE_AA)  # 绘制可核对的英文文字。
        words = [text[0] for _, text in engine.ocr(frame)[0]]  # 执行完整检测和识别推理。
        self.assertTrue(any('okscript' in word.lower() for word in words), words)  # 验证真实识别结果。
