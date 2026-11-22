#!/usr/bin/env python3
"""cellphone-as-typer 服务：手机网页输入 → 剪贴板 → 光标处粘贴。纯 stdlib，零第三方依赖。

路由：
  GET  /        移动端网页（?k=token 由前端存 localStorage 后抹掉）
  POST /send    JSON {text, terminal_mode?, enter?}，鉴权只走 X-Token 头
                （自定义头强制 CORS preflight，不响应 OPTIONS → 跨站伪造被拦）
  GET  /health  无鉴权、无锁状态（永不碰注入锁）

纪律：HTTP/1.1 每个响应必须带 Content-Length；日志不落 token、不落文本内容。
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from injector import InjectError, Injector, make_injector, uinput_available

VERSION = "1.2.0"
MAX_TEXT_BYTES = 64 * 1024
DEFAULT_CONFIG = {"token": "", "port": 8765, "bind": "0.0.0.0", "paste_delay_ms": 150}
CONFIG_PATH = Path.home() / ".config" / "cellphone-as-typer" / "config.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def load_or_create_config(path: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text("utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30  # 防手机浏览器 keep-alive 空闲连接泄漏线程
    server_version = "cellphone-as-typer/" + VERSION

    def log_message(self, fmt, *args):
        # requestline 可能含 ?k=token → 剥掉 query，防 token 进 journald
        if args and isinstance(args[0], str):
            args = (args[0].split("?", 1)[0],) + tuple(args[1:])
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------- 响应助手 ----------

    def _reply(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._reply(
            code,
            "application/json; charset=utf-8",
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        )

    # ---------- 路由 ----------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            try:
                body = (STATIC_DIR / "index.html").read_bytes()
            except OSError:
                self._json(500, {"ok": False, "error": "index.html missing"})
                return
            self._reply(200, "text/html; charset=utf-8", body)
        elif path == "/health":
            self._json(200, {
                "ok": True,
                "injector_ready": self.server.injector.ready,
                "backend": getattr(self.server.injector, "backend_name", "unknown"),
                "uinput_writable": uinput_available(),
                "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
                "version": VERSION,
            })
        elif path == "/qr.png":
            # 二维码分享端点：必须带 token，防访问 URL 泄漏给未鉴权者
            tok = parse_qs(urlparse(self.path).query).get("k", [""])[0]
            got = tok.encode("utf-8", "replace")
            want = self.server.cfg["token"].encode("utf-8")
            if not hmac.compare_digest(got, want):
                self._json(401, {"ok": False, "error": "invalid token"})
                return
            import qr as qrmod

            url = "http://%s/?k=%s" % (self.headers.get("Host", "localhost"), tok)
            self._reply(200, "image/png", qrmod.png_bytes(qrmod.make(url), scale=8))
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/send":
            self._json(404, {"ok": False, "error": "not found"})
            return
        got = self.headers.get("X-Token", "").encode("utf-8", "replace")
        want = self.server.cfg["token"].encode("utf-8")
        if not hmac.compare_digest(got, want):
            self._json(401, {"ok": False, "error": "invalid token"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length <= 0:
            self._json(400, {"ok": False, "error": "empty body"})
            return
        if length > MAX_TEXT_BYTES + 8192:
            self._json(413, {"ok": False, "error": "text too large"})
            return
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "invalid json"})
            return
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"ok": False, "error": "text is empty"})
            return
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            self._json(413, {"ok": False, "error": "text too large"})
            return
        terminal = bool(data.get("terminal_mode", False))
        enter = bool(data.get("enter", False))
        t0 = time.monotonic()
        try:
            self.server.injector.inject(text, terminal_mode=terminal, enter=enter)
        except InjectError as exc:
            if exc.copied:
                # 剪贴板已写入、按键失败：不丢字，提示手动粘贴
                self._json(200, {"ok": False, "copied": True, "error": str(exc)})
            else:
                self._json(503, {"ok": False, "copied": False, "error": str(exc)})
            return
        ms = round((time.monotonic() - t0) * 1000)
        # 只记长度与耗时，不记内容
        sys.stderr.write("send ok: %d chars, %d ms, terminal=%s\n" % (len(text), ms, terminal))
        self._json(200, {"ok": True, "ms": ms})


def make_server(cfg: dict, injector, bind: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(
        (bind if bind is not None else cfg["bind"], port if port is not None else cfg["port"]),
        Handler,
    )
    httpd.daemon_threads = True
    httpd.cfg = cfg
    httpd.injector = injector
    return httpd


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("1.1.1.1", 80))  # UDP connect 不发包，只选路由
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def main() -> None:
    ap = argparse.ArgumentParser(description="cellphone-as-typer: 手机 → Ubuntu 光标处输入服务")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--port", type=int)
    ap.add_argument("--bind")
    args = ap.parse_args()
    cfg = load_or_create_config(Path(args.config))
    if args.port:
        cfg["port"] = args.port
    if args.bind:
        cfg["bind"] = args.bind

    injector = make_injector(paste_delay_ms=int(cfg.get("paste_delay_ms", 150)))
    print("注入后端: %s (ready=%s)" % (getattr(injector, "backend_name", "?"), injector.ready), flush=True)
    if not injector.ready:
        sys.stderr.write(
            "警告：注入后端未就绪——原生后端检查 input 组 + udev 规则（注销重登生效）；"
            "headless 后端检查 DBUS_SESSION_BUS_ADDRESS 与 GNOME 会话\n"
        )
    httpd = make_server(cfg, injector)
    print("cellphone-as-typer %s 监听 %s:%d" % (VERSION, cfg["bind"], cfg["port"]), flush=True)
    if os.environ.get("INVOCATION_ID"):
        # systemd 下 stdout 进 journald：token 不落日志
        print("手机访问 URL: http://%s:%d/?k=<token 见 %s>" % (lan_ip(), cfg["port"], args.config), flush=True)
    else:
        print("手机访问 URL: http://%s:%d/?k=%s" % (lan_ip(), cfg["port"], cfg["token"]), flush=True)

    def shutdown(signum, frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        httpd.serve_forever()
    finally:
        injector.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()