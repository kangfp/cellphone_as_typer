#!/usr/bin/env python3
"""零依赖二维码输出器：终端 ANSI 二维码 + PNG。

编码核心为 third_party/qrcodegen.py（Project Nayuki，MIT，见该目录许可证）。
本文件只做输出层，纯标准库（zlib/struct），任何有 python3 的设备装完即用，
不需要 qrencode / pip / sudo。

用法：
    python3 qr.py "http://host:8765/?k=token"            # 终端二维码（白底黑块）
    python3 qr.py "URL" --png /tmp/qr.png --scale 12     # 存 PNG
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "third_party"))
import qrcodegen  # noqa: E402


def make(text: str):
    """字节模式 UTF-8、纠错等级 M、自动选版本与掩码。"""
    return qrcodegen.QrCode.encode_text(text, qrcodegen.QrCode.Ecc.MEDIUM)


def terminal_str(qr, border: int = 4) -> str:
    """半块字符 + ANSI 白底黑字——不依赖终端配色，深色终端下也是白底黑块。"""
    n = qr.get_size()  # v1.8.0 API（新版为 .size 属性）
    size = n + 2 * border

    def dark(x: int, y: int) -> bool:
        x -= border
        y -= border
        return 0 <= x < n and 0 <= y < n and qr.get_module(x, y)

    lines = []
    for y in range(0, size, 2):
        row = []
        for x in range(size):
            top, bottom = dark(x, y), dark(x, y + 1)
            row.append("█" if top and bottom else "▀" if top else "▄" if bottom else " ")
        lines.append("\x1b[47;30m" + "".join(row) + "\x1b[0m")
    return "\n".join(lines)


def png_bytes(qr, scale: int = 10, border: int = 4) -> bytes:
    """8-bit 灰度 PNG，纯 zlib/struct 手写（无 PIL）。"""
    n = qr.get_size()
    size = n + 2 * border
    px = size * scale
    raw = bytearray()
    for y in range(px):
        raw.append(0)  # filter: none
        my = y // scale - border
        for x in range(px):
            mx = x // scale - border
            dark = 0 <= mx < n and 0 <= my < n and qr.get_module(mx, my)
            raw.append(0 if dark else 255)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", px, px, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="cellphone-as-typer 零依赖二维码生成器")
    ap.add_argument("url", help="要编码的文本/URL")
    ap.add_argument("--png", metavar="PATH", help="输出 PNG 而非终端二维码")
    ap.add_argument("--scale", type=int, default=10, help="PNG 每模块像素数")
    args = ap.parse_args()
    qr = make(args.url)
    if args.png:
        Path(args.png).write_bytes(png_bytes(qr, args.scale))
        print("PNG 已写入: %s" % args.png)
    else:
        print(terminal_str(qr))


if __name__ == "__main__":
    main()