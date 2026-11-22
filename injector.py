"""文本注入：wl-copy 写剪贴板 → uinput 虚拟键盘按粘贴快捷键。

搬运自 kangfp/voice-type 的 inject.py + uinput.py（Ubuntu 24.04 GNOME Wayland
已端到端验证），改造点：
  1. 常驻虚拟键盘：启动时创建一次（付 0.3s libinput 注册等待），后续粘贴毫秒级；
     创建失败时回退 voice-type 的每次临时创建模式。
  2. 删除 ydotool 备用路径（Ubuntu 24.04 仓库 0.1.8 不可用）。
  3. 删除剪贴板恢复路径（发来的文本留在剪贴板，可手动再粘贴）。

零第三方依赖。系统要求：wl-clipboard；/dev/uinput 可写（input 组 + udev 规则）。
"""

from __future__ import annotations

import fcntl
import os
import shutil
import struct
import subprocess
import sys
import threading
import time

UINPUT_PATH = "/dev/uinput"

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0

KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_V = 47

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

# struct input_event：timeval(2x long) + type(u16) + code(u16) + value(s32)
_EVENT = struct.Struct("@llHHi")
# struct uinput_user_dev：name[80] + input_id(4x u16) + ff_effects_max(u32)
# + absmax/absmin/absfuzz/absflat[64]（各 64x s32）
_UINPUT_DEV = struct.Struct("@80sHHHHi" + "i" * 64 * 4)

_SHORTCUT_KEYS = {
    "ctrl+v": (KEY_LEFTCTRL, KEY_V),
    "ctrl+shift+v": (KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V),
}


class InjectError(RuntimeError):
    """copied=True 表示剪贴板已写入但按键失败——文本不丢，可手动粘贴。"""

    def __init__(self, message: str, copied: bool = False) -> None:
        super().__init__(message)
        self.copied = copied


def uinput_available() -> bool:
    return os.path.exists(UINPUT_PATH) and os.access(UINPUT_PATH, os.W_OK)


class Injector:
    """常驻 uinput 虚拟键盘 + wl-copy 粘贴流水线。线程安全（内部串行锁）。"""

    backend_name = "native-uinput"

    def __init__(self, paste_delay_ms: int = 150, device_name: str = "cellphone-as-typer-keyboard") -> None:
        self.paste_delay = paste_delay_ms / 1000.0
        self.device_name = device_name
        self._lock = threading.Lock()
        self._fd: int | None = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """服务启动时调用一次。失败不抛异常（粘贴时回退临时设备）。"""
        if self._fd is not None:
            return
        try:
            self._fd = self._create_device()
            # 给 libinput/mutter 时间注册新设备，否则首批按键被丢弃
            time.sleep(0.3)
        except OSError:
            self._fd = None

    def stop(self) -> None:
        if self._fd is not None:
            try:
                fcntl.ioctl(self._fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(self._fd)
            self._fd = None

    @property
    def ready(self) -> bool:
        return self._fd is not None

    def _create_device(self) -> int:
        fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            for key in (KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_V, KEY_ENTER):
                fcntl.ioctl(fd, UI_SET_KEYBIT, key)
            # BUS_USB=0x03；abs 数组全 0（纯键盘设备）
            dev = _UINPUT_DEV.pack(
                self.device_name.encode()[:80], 0x03, 0x1234, 0x5678, 1, 0, *([0] * 256)
            )
            os.write(fd, dev)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError:
            os.close(fd)
            raise
        return fd

    # ---------- 注入 ----------

    def inject(self, text: str, terminal_mode: bool = False, enter: bool = False) -> None:
        if not text.strip():
            return
        keys = _SHORTCUT_KEYS["ctrl+shift+v" if terminal_mode else "ctrl+v"]
        if not self._lock.acquire(timeout=5):
            raise InjectError("注入排队繁忙，请稍后重试")
        try:
            # 先写剪贴板：即使按键注入失败，用户也能手动粘贴，不丢字
            self._copy(text)
            # 给剪贴板管理器一点时间拿到 selection，再发按键
            time.sleep(self.paste_delay)
            try:
                self._press(keys, enter)
            except OSError as exc:
                raise InjectError(
                    f"按键注入失败：{exc}（文本已在剪贴板，可手动粘贴）", copied=True
                ) from exc
        finally:
            self._lock.release()

    def _copy(self, text: str) -> None:
        wl_copy = shutil.which("wl-copy")
        if not wl_copy:
            raise InjectError("找不到 wl-copy，请先安装 wl-clipboard")
        try:
            # 关键坑：wl-copy 会 fork 常驻进程持有 selection，stdout/stderr 必须
            # 指到 DEVNULL，否则继承的管道让 subprocess.run 一直等 EOF 不返回。
            proc = subprocess.run(
                [wl_copy, "--type", "text/plain;charset=utf-8"],
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )
        except subprocess.TimeoutExpired as exc:
            raise InjectError("写入剪贴板超时") from exc
        if proc.returncode != 0:
            raise InjectError(f"wl-copy 执行失败（退出码 {proc.returncode}）")

    def _press(self, keys: tuple[int, ...], enter: bool) -> None:
        if self._fd is not None:
            self._send_keys(self._fd, keys, enter)
            return
        # 回退：每次临时创建（voice-type 原方案，已验证）
        fd = self._create_device()
        try:
            time.sleep(0.3)
            self._send_keys(fd, keys, enter)
        finally:
            try:
                fcntl.ioctl(fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(fd)

    def _send_keys(self, fd: int, keys: tuple[int, ...], enter: bool) -> None:
        for key in keys:
            self._event(fd, EV_KEY, key, 1)
            self._event(fd, EV_SYN, SYN_REPORT, 0)
        time.sleep(0.05)
        for key in reversed(keys):
            self._event(fd, EV_KEY, key, 0)
            self._event(fd, EV_SYN, SYN_REPORT, 0)
        if enter:
            time.sleep(0.05)
            self._event(fd, EV_KEY, KEY_ENTER, 1)
            self._event(fd, EV_SYN, SYN_REPORT, 0)
            time.sleep(0.05)
            self._event(fd, EV_KEY, KEY_ENTER, 0)
            self._event(fd, EV_SYN, SYN_REPORT, 0)
        time.sleep(0.05)

    @staticmethod
    def _event(fd: int, etype: int, code: int, value: int) -> None:
        os.write(fd, _EVENT.pack(0, 0, etype, code, value))


def _graphical_session_seat() -> str | None:
    """本用户活动图形会话的 Seat 值。""（空串）= headless 无 seat；None = 查不到。

    注意：不能用 wl-paste 是否报 "no keyboard" 判别 headless——D-Bus 注入创建过
    clutter 虚拟键盘后 seat 会获得 keyboard 能力，wl-paste 恢复正常，但 uinput
    事件依然不被 headless mutter 消费（无 seat 就没有 libinput 路由）。
    """
    import pwd

    try:
        out = subprocess.run(
            ["loginctl", "list-sessions", "--no-legend"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    user = pwd.getpwuid(os.getuid()).pw_name
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            props = subprocess.run(
                ["loginctl", "show-session", parts[0],
                 "-p", "Name", "-p", "Type", "-p", "Seat", "-p", "State"],
                capture_output=True, text=True, timeout=3,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        d = dict(kv.split("=", 1) for kv in props.splitlines() if "=" in kv)
        if d.get("Name") == user and d.get("Type") in ("wayland", "x11") and d.get("State") == "active":
            return d.get("Seat", "")
    return None


def make_injector(paste_delay_ms: int = 150):
    """自动选择注入后端。

    headless GRD 远程登录会话（图形会话 Seat 为空）：uinput 不被消费 →
    改用 Mutter RemoteDesktop D-Bus 后端（GRD 自己的 compositor 层通道）。
    正常本地会话（Seat=seat0）→ 原生 wl-copy + uinput 后端（voice-type 已验证）。
    """
    native_ok = shutil.which("wl-copy") is not None
    seat = _graphical_session_seat()
    headless = seat == ""
    if seat is None and shutil.which("wl-paste"):
        # 查不到会话时的兜底信号：wl-paste 的 seat 报错
        try:
            probe = subprocess.run(
                ["wl-paste", "--no-newline", "--type", "text"],
                capture_output=True, timeout=3,
            )
            headless = b"no keyboard" in probe.stderr
        except (OSError, subprocess.TimeoutExpired):
            pass
    if headless or not native_ok:
        try:
            from headless import HeadlessInjector  # 延迟导入：Mac/无 dbus 环境不炸

            h = HeadlessInjector(paste_delay_ms=paste_delay_ms)
            h.start()
            if h.ready:
                return h
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("headless D-Bus 后端不可用（%s），回退原生后端\n" % exc)
    inj = Injector(paste_delay_ms=paste_delay_ms)
    inj.start()
    return inj