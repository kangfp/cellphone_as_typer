#!/bin/sh
# cellphone-mic 启动脚本：WAYLAND_DISPLAY 三级兜底
# （环境变量 → systemd 用户环境 → 扫 XDG_RUNTIME_DIR 下的 wayland socket）
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "$WAYLAND_DISPLAY" ]; then
  WAYLAND_DISPLAY=$(systemctl --user show-environment 2>/dev/null | sed -n 's/^WAYLAND_DISPLAY=//p')
fi
if [ -z "$WAYLAND_DISPLAY" ]; then
  for s in "$XDG_RUNTIME_DIR"/wayland-*; do
    [ -S "$s" ] && WAYLAND_DISPLAY=$(basename "$s") && break
  done
fi
export WAYLAND_DISPLAY
# headless D-Bus 后端需要会话总线地址
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
exec /usr/bin/python3 "$HOME/.local/share/cellphone-mic/server.py"