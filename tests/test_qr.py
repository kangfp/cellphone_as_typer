"""qr.py 测试：PNG/终端输出结构 + 独立解码器回环验证。

opencv-python-headless 是可选开发依赖（python3 -m pip install --user
opencv-python-headless），缺省跳过回环测试。
运行：python3 tests/test_qr.py
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import qr  # noqa: E402

URL = "http://192.0.2.1:8765/?k=ExampleToken123"  # 文档专用地址/示例 token，勿放真实凭据


class QrTest(unittest.TestCase):
    def test_png_signature_and_dimensions(self):
        code = qr.make(URL)
        data = qr.png_bytes(code, scale=4)
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        width = struct.unpack(">I", data[16:20])[0]
        self.assertEqual(width, (code.get_size() + 8) * 4)
        self.assertIn(b"IEND", data)

    def test_terminal_white_bg_blocks(self):
        s = qr.terminal_str(qr.make("hello"))
        self.assertIn("█", s)
        self.assertIn("\x1b[47;30m", s)  # 白底黑字，深色终端下仍可扫
        self.assertIn("\x1b[0m", s)

    def test_opencv_decode_roundtrip(self):
        """独立解码器回环验证（OpenCV 自己的 QR 实现，本地解码不联网）。

        历史教训：曾与 segno 逐模块对照，发现 segno 在 terminator 后多插一个
        全零填充字节（与规范手算不符），矩阵相等不是可靠的正确性判据；
        独立解码器能还原原文才是铁证。Nayuki 数据前缀与规范手算逐字节一致。
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("opencv-python-headless 未安装（可选开发依赖）")
        det = cv2.QRCodeDetector()
        for text in ["hello", URL, "中文测试 你好 🌍", "x" * 200]:
            png = qr.png_bytes(qr.make(text), scale=8)
            img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
            decoded, _, _ = det.detectAndDecode(img)
            self.assertEqual(decoded, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)