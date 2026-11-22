#!/usr/bin/env python3
"""X11（XWayland）按键/焦点记录器：判定 keysym 注入是否到达窗口、窗口是否拿到焦点。

需环境变量：DISPLAY=:0 XAUTHORITY=/run/user/1000/.mutter-Xwaylandauth.* GDK_BACKEND=x11
日志写 /tmp/cm_x11.log（MAP / FOCUS_IN / FOCUS_OUT / KEY xxx），25 秒后自动退出。
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

log = open("/tmp/cm_x11.log", "w", buffering=1)
win = Gtk.Window(title="cm-probe-x11")
win.set_default_size(320, 120)
win.add(Gtk.Label(label="cm-probe: waiting for keys…"))


def on_key(w, e):
    log.write("KEY %s\n" % Gdk.keyval_name(e.keyval))
    return False


def on_focus_in(w, e):
    log.write("FOCUS_IN\n")
    return False


def on_focus_out(w, e):
    log.write("FOCUS_OUT\n")
    return False


def on_map(w, e):
    log.write("MAP\n")


win.connect("key-press-event", on_key)
win.connect("focus-in-event", on_focus_in)
win.connect("focus-out-event", on_focus_out)
win.connect("map-event", on_map)
win.connect("destroy", Gtk.main_quit)
win.show_all()
GLib.timeout_add(25000, Gtk.main_quit)
Gtk.main()
log.write("EXIT\n")