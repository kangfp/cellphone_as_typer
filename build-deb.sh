#!/usr/bin/env bash
# 构建 cellphone-as-typer 的 deb 包（Architecture: all，纯 Python，无 venv）。
# 在 Debian/Ubuntu 上运行（需要 dpkg-deb）；Mac 上可经 SSH 到目标机构建。
# 用法：bash build-deb.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(sed -n 's/^Version: //p' "$PROJECT_DIR/packaging/control")"
ARCH="all"
BUILD_DIR="$PROJECT_DIR/build/deb"
PKG_ROOT="$BUILD_DIR/cellphone-as-typer_${VERSION}_${ARCH}"

echo "==> [1/4] 清理并创建打包目录"
rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/DEBIAN" \
    "$PKG_ROOT/usr/lib/cellphone-as-typer/static" \
    "$PKG_ROOT/usr/lib/cellphone-as-typer/third_party" \
    "$PKG_ROOT/usr/lib/systemd/user" \
    "$PKG_ROOT/usr/lib/udev/rules.d" \
    "$PKG_ROOT/usr/bin" \
    "$PKG_ROOT/usr/share/applications" \
    "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$PKG_ROOT/usr/share/doc/cellphone-as-typer"

echo "==> [2/4] 安装应用文件（/usr/lib/cellphone-as-typer）"
cd "$PROJECT_DIR"
install -m 0644 server.py injector.py headless.py qr.py "$PKG_ROOT/usr/lib/cellphone-as-typer/"
install -m 0644 static/index.html "$PKG_ROOT/usr/lib/cellphone-as-typer/static/"
install -m 0644 third_party/qrcodegen.py third_party/LICENSE-nayuki.txt \
    "$PKG_ROOT/usr/lib/cellphone-as-typer/third_party/"
install -m 0755 deploy/run.sh "$PKG_ROOT/usr/lib/cellphone-as-typer/"
install -m 0644 packaging/cellphone-as-typer.service "$PKG_ROOT/usr/lib/systemd/user/"
install -m 0644 deploy/99-cellphone-as-typer-uinput.rules "$PKG_ROOT/usr/lib/udev/rules.d/"
install -m 0755 packaging/cellphone-as-typer-qr "$PKG_ROOT/usr/bin/"
install -m 0755 packaging/cellphone-as-typer "$PKG_ROOT/usr/bin/"
install -m 0644 packaging/cellphone-as-typer.desktop "$PKG_ROOT/usr/share/applications/"
install -m 0644 icons/cellphone-as-typer.svg "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps/"

echo "==> [3/4] 文档与控制文件"
install -m 0644 packaging/copyright README.md "$PKG_ROOT/usr/share/doc/cellphone-as-typer/"
gzip -9n -c packaging/changelog > "$PKG_ROOT/usr/share/doc/cellphone-as-typer/changelog.gz"
install -m 0644 packaging/control "$PKG_ROOT/DEBIAN/"
for script in postinst prerm postrm; do
    install -m 0755 "packaging/$script" "$PKG_ROOT/DEBIAN/"
done
# control 末尾若无换行，追加字段会粘进 Description——先补换行
[ -n "$(tail -c1 "$PKG_ROOT/DEBIAN/control")" ] && echo >> "$PKG_ROOT/DEBIAN/control"
echo "Installed-Size: $(du -sk "$PKG_ROOT" | cut -f1)" >> "$PKG_ROOT/DEBIAN/control"

echo "==> [4/4] 构建 deb"
dpkg-deb --build --root-owner-group "$PKG_ROOT" "$BUILD_DIR/" >/dev/null
DEB="$BUILD_DIR/cellphone-as-typer_${VERSION}_${ARCH}.deb"
echo
echo "✓ 构建完成：$DEB"
ls -lh "$DEB" | awk '{print "  大小:", $5}'
echo "  安装（自动配依赖）：sudo apt install $DEB"
echo "  或：sudo dpkg -i $DEB && sudo apt-get install -f"