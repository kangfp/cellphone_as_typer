#!/usr/bin/env bash
# 免 sudo 安装：用于 udev 规则 / input 组 / wl-clipboard 均已就绪的机器。
# 系统级步骤（apt/udev/usermod）见 setup.sh；本脚本只做用户级部署。
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/.local/share/cellphone-mic"
CFG_DIR="$HOME/.config/cellphone-mic"

# 前置检查（只警告，不阻断）
[ -w /dev/uinput ] || echo "!! /dev/uinput 不可写：注入会降级为仅剪贴板（需 udev 规则 + input 组 + 重登）"
command -v wl-copy >/dev/null || echo "!! 缺 wl-copy：sudo apt install wl-clipboard"

mkdir -p "$APP_DIR/static" "$CFG_DIR" "$HOME/.config/systemd/user"
install -m 0644 "$SRC_DIR/server.py" "$SRC_DIR/injector.py" "$SRC_DIR/headless.py" "$SRC_DIR/qr.py" "$APP_DIR/"
mkdir -p "$APP_DIR/third_party"
install -m 0644 "$SRC_DIR/third_party/qrcodegen.py" "$SRC_DIR/third_party/LICENSE-nayuki.txt" "$APP_DIR/third_party/"
install -m 0644 "$SRC_DIR/static/index.html" "$APP_DIR/static/"
install -m 0755 "$SRC_DIR/deploy/run.sh" "$APP_DIR/"
install -m 0644 "$SRC_DIR/deploy/cellphone-mic.service" "$HOME/.config/systemd/user/"

python3 - "$CFG_DIR/config.json" <<'PY'
import json, os, secrets, sys
path = sys.argv[1]
cfg = {"token": "", "port": 8765, "bind": "0.0.0.0", "paste_delay_ms": 150}
if os.path.exists(path):
    try:
        cfg.update(json.load(open(path, encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        pass
if not cfg.get("token"):
    cfg["token"] = secrets.token_urlsafe(16)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
PY

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
systemctl --user daemon-reload
systemctl --user enable cellphone-mic.service
systemctl --user restart cellphone-mic.service
sleep 1
systemctl --user --no-pager -l status cellphone-mic.service | head -12 || true

IP=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p')
[ -n "$IP" ] || IP=$(hostname -I | awk '{print $1}')
TOKEN=$(python3 -c "import json;print(json.load(open('$CFG_DIR/config.json'))['token'])")
URL="http://$IP:8765/?k=$TOKEN"
echo
echo "手机访问 URL: $URL"
python3 "$SRC_DIR/qr.py" "$URL" || true