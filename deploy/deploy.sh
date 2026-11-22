#!/usr/bin/env bash
# Mac 侧部署：rsync 源码到虚拟机 + 触发安装
# 用法：./deploy/deploy.sh <user@vm-ip> [--rotate-token]
set -euo pipefail
TARGET="${1:?用法: deploy.sh user@vm-ip [--rotate-token]}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
rsync -av --exclude '.git' --exclude '__pycache__' --exclude '.DS_Store' \
  "$SRC/" "$TARGET:~/cellphone-mic-src/"
ssh "$TARGET" "bash ~/cellphone-mic-src/deploy/setup.sh ${2:-}"