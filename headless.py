"""headless GRD 会话注入后端：Mutter RemoteDesktop D-Bus。

适用场景：GNOME 远程登录（headless）会话——无 seat 归属，wl-clipboard 报
"This seat has no keyboard"，uinput 设备不被 headless mutter 消费。
此时走 GRD 自己使用的 compositor 层通道：

  剪贴板：EnableClipboard → SetSelection({"mime-types": [...]}) 成为所有者
          → 应用粘贴时 mutter 发 SelectionTransfer(mime, serial)
          → SelectionWrite(serial) 拿 fd 写文本 → SelectionWriteDone(serial, True)
  按键：  NotifyKeyboardKeysym（keysym 与键盘布局无关）

血泪坑（mutter 46 源码 meta-remote-desktop-session.c:1511 核实）：
  选项键名是 **"mime-types"（连字符）**！传 "mime_types" 会被静默忽略，
  SetSelection 走 else 分支清空所有权还返回 OK——永远等不到 SelectionTransfer。

依赖：python3-dbus、python3-gi（Ubuntu 桌面版预装，无需 pip/venv）。
已在 Ubuntu 24.04.4 / GNOME 46 / VirtualBox headless GRD 会话实测：
  X11（XWayland）与 Wayland 原生窗口均粘贴成功，中文/emoji 无损。
"""

from __future__ import annotations

import os
import threading
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from injector import InjectError

MIMES = ["text/plain;charset=utf-8", "text/plain", "UTF8_STRING"]
XK_Control_L = 0xFFE3
XK_Shift_L = 0xFFE1
XK_v = 0x0076
XK_Return = 0xFF0D

RD_BUS = "org.gnome.Mutter.RemoteDesktop"
RD_PATH = "/org/gnome/Mutter/RemoteDesktop"
RD_IFACE = "org.gnome.Mutter.RemoteDesktop"
RD_SESSION_IFACE = "org.gnome.Mutter.RemoteDesktop.Session"


class HeadlessInjector:
    """D-Bus 剪贴板所有权 + keysym 粘贴。线程安全（内部串行锁）。

    GLib 主循环跑在守护线程里分发 SelectionTransfer 信号；
    HTTP 线程调用 inject()（python3-dbus 方法调用线程安全）。
    """

    backend_name = "headless-dbus"

    def __init__(self, paste_delay_ms: int = 150) -> None:
        self.paste_delay = paste_delay_ms / 1000.0
        self._lock = threading.Lock()
        self._text = ""
        self._ready = False
        self._s = None
        self._loop = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()
        rd = dbus.Interface(bus.get_object(RD_BUS, RD_PATH), RD_IFACE)
        path = rd.CreateSession()
        self._s = dbus.Interface(bus.get_object(RD_BUS, path), RD_SESSION_IFACE)
        self._s.Start()
        self._s.EnableClipboard({})
        self._s.connect_to_signal("SelectionTransfer", self._on_transfer)
        self._loop = GLib.MainLoop()
        threading.Thread(target=self._loop.run, daemon=True).start()
        self._ready = True

    def stop(self) -> None:
        self._ready = False
        if self._s is not None:
            try:
                self._s.Stop()
            except Exception:  # noqa: BLE001
                pass
        if self._loop is not None:
            self._loop.quit()

    @property
    def ready(self) -> bool:
        return self._ready

    # ---------- 剪贴板信号 ----------

    def _on_transfer(self, mime_type, serial) -> None:
        # mutter 代表粘贴方索要数据。可能在 SetSelection 后立即发生（预取），
        # 也可能在任意时刻（应用粘贴）——始终回当前文本。
        try:
            fd = self._s.SelectionWrite(serial)
            fd = fd.take() if hasattr(fd, "take") else int(fd)
            os.write(fd, self._text.encode("utf-8"))
            os.close(fd)
            self._s.SelectionWriteDone(serial, True)
        except Exception:  # noqa: BLE001
            try:
                self._s.SelectionWriteDone(serial, False)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 注入 ----------

    def inject(self, text: str, terminal_mode: bool = False, enter: bool = False) -> None:
        if not text.strip():
            return
        if not self._ready:
            raise InjectError("headless D-Bus 会话未就绪")
        if not self._lock.acquire(timeout=5):
            raise InjectError("注入排队繁忙，请稍后重试")
        try:
            self._text = text
            # 键名必须是连字符 "mime-types"（见模块 docstring 的血泪坑）
            self._s.SetSelection({"mime-types": MIMES})
            time.sleep(self.paste_delay)
            try:
                self._press_paste(terminal_mode, enter)
            except Exception as exc:  # noqa: BLE001
                raise InjectError(
                    f"按键注入失败：{exc}（文本已在剪贴板，可手动粘贴）", copied=True
                ) from exc
        finally:
            self._lock.release()

    def _press_paste(self, terminal_mode: bool, enter: bool) -> None:
        keys = [XK_Control_L] + ([XK_Shift_L] if terminal_mode else []) + [XK_v]
        for sym in keys:
            self._s.NotifyKeyboardKeysym(sym, True)
            time.sleep(0.04)
        for sym in reversed(keys):
            self._s.NotifyKeyboardKeysym(sym, False)
            time.sleep(0.04)
        if enter:
            time.sleep(0.05)
            self._s.NotifyKeyboardKeysym(XK_Return, True)
            time.sleep(0.05)
            self._s.NotifyKeyboardKeysym(XK_Return, False)
        time.sleep(0.05)