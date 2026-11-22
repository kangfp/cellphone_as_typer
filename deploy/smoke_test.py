#!/usr/bin/env python3
"""注入冒烟测试（Phase 1 门禁，不依赖服务）。

在 RDP 会话内的 GNOME Terminal 里运行（自带正确 Wayland 环境）：
    python3 deploy/smoke_test.py             # 3 秒内把焦点点到 Text Editor
    python3 deploy/smoke_test.py --terminal  # 焦点放 GNOME Terminal，走 Ctrl+Shift+V
    python3 deploy/smoke_test.py --text "自定义文本" --delay 5
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from injector import Injector, uinput_available  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="cellphone-mic 注入冒烟测试")
    ap.add_argument("--text", default="你好，世界 🌍 cellphone-mic 冒烟测试")
    ap.add_argument("--terminal", action="store_true", help="终端模式 Ctrl+Shift+V")
    ap.add_argument("--delay", type=int, default=3, help="倒计时秒数，用来切换焦点")
    args = ap.parse_args()

    print("WAYLAND_DISPLAY =", os.environ.get("WAYLAND_DISPLAY", "(未设置！wl-copy 会失败)"))
    print("/dev/uinput 可写:", uinput_available())
    if not uinput_available():
        print("!! /dev/uinput 不可写：装 udev 规则 + 加入 input 组 + 注销重登")
    target = "GNOME Terminal" if args.terminal else "Text Editor（文本编辑器）"
    print(f"{args.delay} 秒后注入，请现在把焦点点到 {target} 的输入位置…")
    for i in range(args.delay, 0, -1):
        print(i, flush=True)
        time.sleep(1)

    inj = Injector()
    inj.start()
    print("常驻键盘就绪:", inj.ready)
    try:
        inj.inject(args.text, terminal_mode=args.terminal)
        print("注入调用完成。光标处出现文字 = 链路通；")
        print("没出现但剪贴板里有文本 = 查 uinput 权限 / GRD 剪贴板方向设置。")
    except Exception as exc:
        print("注入失败:", exc)
        sys.exit(1)
    finally:
        inj.stop()


if __name__ == "__main__":
    main()