#!/usr/bin/env python3
"""D-Bus 剪贴板所有权 + Ctrl+V 注入（带 SelectionTransfer 完整处理）。

用法：inject_paste.py [要粘贴的文本]
"""

import os
import sys
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

TEXT = sys.argv[1] if len(sys.argv) > 1 else "粘贴测试 clipboard OK 🌍"
MIMES = ["text/plain;charset=utf-8", "text/plain", "UTF8_STRING"]

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
s.EnableClipboard({})
print("session:", path, "| clipboard enabled", flush=True)


def on_transfer(mime, serial):
    print("SelectionTransfer: mime=%s serial=%s" % (mime, serial), flush=True)
    try:
        fd = s.SelectionWrite(serial)
        fd = fd.take() if hasattr(fd, "take") else int(fd)
        os.write(fd, TEXT.encode("utf-8"))
        os.close(fd)
        s.SelectionWriteDone(serial, True)
        print("SelectionWriteDone OK", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("transfer 失败:", exc, flush=True)
        try:
            s.SelectionWriteDone(serial, False)
        except Exception:  # noqa: BLE001
            pass


s.connect_to_signal("SelectionTransfer", on_transfer)
s.SetSelection({"mime-types": MIMES})  # 注意：mutter 源码用连字符 "mime-types"，下划线会被静默忽略！
print("SetSelection OK（剪贴板所有权到手）", flush=True)

loop = GLib.MainLoop()


def inject():
    for sym, st in [(0xFFE3, True), (0x76, True), (0x76, False), (0xFFE3, False)]:
        s.NotifyKeyboardKeysym(sym, st)
        time.sleep(0.04)
    print("Ctrl+V injected", flush=True)
    GLib.timeout_add(4000, loop.quit)
    return False


GLib.timeout_add(1000, inject)
GLib.timeout_add(15000, loop.quit)
loop.run()
try:
    s.Stop()
except Exception:  # noqa: BLE001
    pass
print("done", flush=True)