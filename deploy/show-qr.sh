#!/usr/bin/env bash
# 在 VM 上生成访问二维码并打开到桌面（RDP 里扫码）。零依赖：用项目自带 qr.py。
# 用法：./deploy/show-qr.sh user@vm-ip
# token 轮换后重跑一次即可刷新二维码。需先完成部署（qr.py 在 ~/.local/share/cellphone-as-typer/）。
set -euo pipefail
TARGET="${1:?用法: show-qr.sh user@vm-ip}"

ssh "$TARGET" 'python3 - <<PY
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.expanduser("~/.local/share/cellphone-as-typer"))
import qr
cfg = json.load(open(os.path.expanduser("~/.config/cellphone-as-typer/config.json")))
out = subprocess.run(["ip", "-4", "route", "get", "1.1.1.1"],
                     capture_output=True, text=True).stdout
m = re.search(r"src ([0-9.]+)", out)
url = "http://%s:%s/?k=%s" % (m.group(1) if m else "127.0.0.1", cfg.get("port", 8765), cfg["token"])
open("/tmp/cm_qr.png", "wb").write(qr.png_bytes(qr.make(url), scale=12))
print(url)
PY'

ssh "$TARGET" 'export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus WAYLAND_DISPLAY=wayland-0; nohup xdg-open /tmp/cm_qr.png >/dev/null 2>&1 & sleep 1; echo 二维码已在桌面打开'