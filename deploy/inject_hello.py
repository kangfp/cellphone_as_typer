#!/usr/bin/env python3
"""只注入 hello + 回车（不开任何窗口），配合 probe_x11.py / 手动焦点目标使用。"""

import time

import dbus

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
for sym in [0x68, 0x65, 0x6C, 0x6C, 0x6F]:  # h e l l o
    s.NotifyKeyboardKeysym(sym, True)
    time.sleep(0.03)
    s.NotifyKeyboardKeysym(sym, False)
    time.sleep(0.03)
time.sleep(0.2)
s.NotifyKeyboardKeysym(0xFF0D, True)
time.sleep(0.05)
s.NotifyKeyboardKeysym(0xFF0D, False)
print("injected hello + Return", flush=True)
time.sleep(1)
s.Stop()