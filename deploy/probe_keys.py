#!/usr/bin/env python3
"""探针 v3：隔离验证按键注入 + 焦点（不涉及剪贴板）。

开一个 gnome-terminal 跑 `read` 等输入 → 注入 hello 的 keysym + 回车
→ /tmp/cm_keys.txt 内容 == "hello" 即按键链路与焦点全通。
"""

from __future__ import annotations

import os
import subprocess
import time

import dbus

MARK = "/tmp/cm_keys.txt"
HELLO = [0x68, 0x65, 0x6C, 0x6C, 0x6F]  # h e l l o
XK_Return = 0xFF0D


def main() -> None:
    if os.path.exists(MARK):
        os.unlink(MARK)
    subprocess.run(
        ["gnome-terminal", "--", "bash", "-c",
         "bind 'set enable-bracketed-paste off'; read -r line; printf '%s' \"$line\" > " + MARK],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
    )
    print("terminal(read) 已启动，等 5 秒…", flush=True)
    time.sleep(5)

    bus = dbus.SessionBus()
    rd = dbus.Interface(
        bus.get_object("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop"),
        "org.gnome.Mutter.RemoteDesktop",
    )
    path = rd.CreateSession()
    s = dbus.Interface(
        bus.get_object("org.gnome.Mutter.RemoteDesktop", path),
        "org.gnome.Mutter.RemoteDesktop.Session",
    )
    s.Start()
    print("session:", path, flush=True)
    for sym in HELLO:
        s.NotifyKeyboardKeysym(sym, True)
        time.sleep(0.03)
        s.NotifyKeyboardKeysym(sym, False)
        time.sleep(0.03)
    time.sleep(0.2)
    s.NotifyKeyboardKeysym(XK_Return, True)
    time.sleep(0.05)
    s.NotifyKeyboardKeysym(XK_Return, False)
    print("hello + 回车 注入完成，等 2 秒…", flush=True)
    time.sleep(2)
    try:
        with open(MARK, encoding="utf-8") as f:
            content = f.read()
        print("RESULT:", "按键+焦点通过 ✓" if content == "hello" else "内容异常 ✗",
              "| 文件内容:", repr(content), flush=True)
    except FileNotFoundError:
        print("RESULT: 文件未生成 ✗（按键没到达终端 / 焦点不在终端）", flush=True)
    try:
        s.Stop()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()