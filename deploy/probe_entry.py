#!/usr/bin/env python3
"""GTK Entry 记录器：焦点/按键/粘贴结果全记录。

用法：probe_entry.py <日志路径>
后端由 GDK_BACKEND 环境变量决定（x11 需 DISPLAY+XAUTHORITY；wayland 需 WAYLAND_DISPLAY）。
Entry 内容变化（含粘贴）写 ENTRY 行。30 秒后自动退出。
"""

import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

log = open(sys.argv[1], "w", buffering=1)
win = Gtk.Window(title="cm-probe-entry")
win.set_default_size(360, 120)
entry = Gtk.Entry()
win.add(entry)


def on_key(w, e):
    log.write("KEY %s\n" % Gdk.keyval_name(e.keyval))
    return False


def on_focus_in(w, e):
    log.write("FOCUS_IN\n")
    return False


def on_changed(e):
    log.write("ENTRY %s\n" % e.get_text())


win.connect("key-press-event", on_key)
win.connect("focus-in-event", on_focus_in)
entry.connect("changed", on_changed)
win.connect("destroy", Gtk.main_quit)
win.show_all()
GLib.timeout_add(30000, Gtk.main_quit)
Gtk.main()
log.write("EXIT\n")