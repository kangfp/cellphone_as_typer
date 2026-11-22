#!/usr/bin/env python3
"""headless GRD 注入探针 v2：程序化闭环验证（无需人眼确认）。

流程：Mutter RemoteDesktop D-Bus 剪贴板所有权 → 打开 GNOME Terminal（等 5s 焦点）
→ Ctrl+Shift+V 粘贴命令 + 回车 → 命令写 /tmp/cm_probe.txt → 文件存在 = 全链路通。
顺带验证终端模式（Ctrl+Shift+V）。所有 print 带 flush（SSH 管道缓冲）。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

MARK = "/tmp/cm_probe.txt"
TEXT = "echo HEADLESS_INJECT_OK > /tmp/cm_probe.txt"
MIMES = ["text/plain;charset=utf-8", "text/plain", "UTF8_STRING"]
XK_Control_L = 0xFFE3
XK_Shift_L = 0xFFE1
XK_v = 0x0076
XK_Return = 0xFF0D


def take_fd(f) -> int:
    return f.take() if hasattr(f, "take") else int(f)


def main() -> None:
    if os.path.exists(MARK):
        os.unlink(MARK)
    bus = dbus.SessionBus()
    rd = dbus.Interface(
        bus.get_object("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop"),
        "org.gnome.Mutter.RemoteDesktop",
    )
    path = rd.CreateSession()
    print("session:", path, flush=True)
    s = dbus.Interface(
        bus.get_object("org.gnome.Mutter.RemoteDesktop", path),
        "org.gnome.Mutter.RemoteDesktop.Session",
    )
    s.Start()
    s.EnableClipboard({})
    print("Start + EnableClipboard OK", flush=True)

    state = {"text": TEXT}
    transfers: list[str] = []

    def on_transfer(mime_type, serial):
        transfers.append(str(mime_type))
        print("SelectionTransfer: mime=%s serial=%s" % (mime_type, serial), flush=True)
        try:
            fd = take_fd(s.SelectionWrite(serial))
            os.write(fd, state["text"].encode("utf-8"))
            os.close(fd)
            s.SelectionWriteDone(serial, True)
            print("SelectionWriteDone OK", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("transfer 处理失败:", exc, flush=True)
            try:
                s.SelectionWriteDone(serial, False)
            except Exception:  # noqa: BLE001
                pass

    s.connect_to_signal("SelectionTransfer", on_transfer)
    s.SetSelection({"mime-types": MIMES})  # mutter 源码键名是连字符 "mime-types"
    print("SetSelection OK（剪贴板所有权到手）", flush=True)

    loop = GLib.MainLoop()

    def read_back():
        try:
            fd = take_fd(s.SelectionRead("text/plain"))
            data = os.read(fd, 4096)
            os.close(fd)
            ok = data.decode("utf-8") == TEXT
            print("回读验证:", "通过 ✓" if ok else "不一致 ✗", flush=True)
        except Exception as exc:  # noqa: BLE001
            print("回读失败（不影响主验证）:", exc, flush=True)

    threading.Thread(target=read_back, daemon=True).start()

    def launch():
        subprocess.run(
            ["gtk-launch", "org.gnome.Terminal"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, check=False,
        )
        print("Terminal 已启动，等 5 秒拿焦点…", flush=True)
        GLib.timeout_add(5000, inject)
        return False

    def inject():
        print("注入 Ctrl+Shift+V + 回车…", flush=True)
        try:
            for sym, st in [
                (XK_Control_L, True), (XK_Shift_L, True), (XK_v, True),
                (XK_v, False), (XK_Shift_L, False), (XK_Control_L, False),
            ]:
                s.NotifyKeyboardKeysym(sym, st)
                time.sleep(0.04)
            time.sleep(0.3)
            s.NotifyKeyboardKeysym(XK_Return, True)
            time.sleep(0.05)
            s.NotifyKeyboardKeysym(XK_Return, False)
            print("按键注入完成", flush=True)
        except dbus.exceptions.DBusException as exc:
            print("按键注入失败:", exc, flush=True)
        GLib.timeout_add(2500, check)
        return False

    def check():
        ok = os.path.exists(MARK)
        print("RESULT:", "全链路通过 ✓✓✓" if ok else "文件未生成 ✗",
              "| transfers:", transfers, flush=True)
        loop.quit()
        return False

    GLib.timeout_add(1500, launch)
    GLib.timeout_add(30000, loop.quit)
    loop.run()
    try:
        s.Stop()
    except Exception:  # noqa: BLE001
        pass
    print("探针结束", flush=True)


if __name__ == "__main__":
    main()