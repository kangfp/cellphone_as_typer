#!/usr/bin/env bash
# cellphone-as-typer 一键安装（在 Ubuntu 虚拟机上运行）
# 用法：bash setup.sh [--rotate-token]
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/.local/share/cellphone-as-typer"
CFG_DIR="$HOME/.config/cellphone-as-typer"
ROTATE=0
[ "${1:-}" = "--rotate-token" ] && ROTATE=1

echo "== 1/6 系统依赖 =="
sudo apt-get update -qq
sudo apt-get install -y wl-clipboard

echo "== 2/6 uinput 权限 =="
sudo install -m 0644 "$SRC_DIR/deploy/99-cellphone-as-typer-uinput.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --name-match=uinput || true
NEED_RELOGIN=0
if ! id -nG "$USER" | grep -qw input; then
  sudo usermod -aG input "$USER"
  NEED_RELOGIN=1
fi

echo "== 3/6 应用文件 =="
mkdir -p "$APP_DIR/static" "$CFG_DIR"
install -m 0644 "$SRC_DIR/server.py" "$SRC_DIR/injector.py" "$SRC_DIR/headless.py" "$SRC_DIR/qr.py" "$APP_DIR/"
mkdir -p "$APP_DIR/third_party"
install -m 0644 "$SRC_DIR/third_party/qrcodegen.py" "$SRC_DIR/third_party/LICENSE-nayuki.txt" "$APP_DIR/third_party/"
install -m 0644 "$SRC_DIR/static/index.html" "$APP_DIR/static/"
install -m 0755 "$SRC_DIR/deploy/run.sh" "$APP_DIR/"

echo "== 4/6 配置与 token =="
python3 - "$CFG_DIR/config.json" "$ROTATE" <<'PY'
import json, os, secrets, sys
path, rotate = sys.argv[1], sys.argv[2] == "1"
cfg = {"token": "", "port": 8765, "bind": "0.0.0.0", "paste_delay_ms": 150}
if os.path.exists(path):
    try:
        cfg.update(json.load(open(path, encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        pass
if rotate or not cfg.get("token"):
    cfg["token"] = secrets.token_urlsafe(16)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
PY

echo "== 5/6 systemd 用户服务 =="
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 "$SRC_DIR/deploy/cellphone-as-typer.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable cellphone-as-typer.service
systemctl --user restart cellphone-as-typer.service || true

echo "== 6/6 访问地址 =="
IP=$(hostname -I | awk '{print $1}')
TOKEN=$(python3 -c "import json;print(json.load(open('$CFG_DIR/config.json'))['token'])")
URL="http://$IP:8765/?k=$TOKEN"
echo
echo "手机访问 URL: $URL"
python3 "$SRC_DIR/qr.py" "$URL"
echo
if [ "$NEED_RELOGIN" = 1 ]; then
  echo "!! 已加入 input 组：必须注销并重新登录，然后 systemctl --user restart cellphone-as-typer"
fi
if [ ! -w /dev/uinput ]; then
  echo "!! 当前 /dev/uinput 不可写：注入会降级为仅剪贴板。完成注销重登后重启服务。"
fi
echo "冒烟测试：在 RDP 会话的 GNOME Terminal 里运行 python3 $SRC_DIR/deploy/smoke_test.py"