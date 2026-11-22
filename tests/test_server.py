"""server.py 路由/鉴权/并发测试（Mac 可跑，fake injector，不碰真实注入）。

运行：python3 tests/test_server.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from injector import InjectError  # noqa: E402
from server import make_server  # noqa: E402

TOKEN = "test-token-123"


class FakeInjector:
    def __init__(self, fail: InjectError | None = None):
        self.calls: list[tuple[str, bool, bool]] = []
        self.ready = True
        self.fail = fail
        self._lock = threading.Lock()

    def inject(self, text: str, terminal_mode: bool = False, enter: bool = False) -> None:
        if self.fail:
            raise self.fail
        with self._lock:
            time.sleep(0.01)
            self.calls.append((text, terminal_mode, enter))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = {"token": TOKEN, "port": 0, "bind": "127.0.0.1", "paste_delay_ms": 0}
        cls.fake = FakeInjector()
        cls.httpd = make_server(cls.cfg, cls.fake, bind="127.0.0.1", port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.httpd.injector = self.fake
        self.fake.calls.clear()
        self.fake.fail = None

    def req(self, method: str, path: str, body: bytes | None = None, token: str | None = None):
        r = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), method=method, data=body)
        if token is not None:
            r.add_header("X-Token", token)
        if body is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def send_json(self, obj, token=TOKEN):
        return self.req("POST", "/send", json.dumps(obj).encode(), token)

    # ---------- 路由与鉴权 ----------

    def test_health_no_auth(self):
        code, body = self.req("GET", "/health")
        self.assertEqual(code, 200)
        j = json.loads(body)
        self.assertTrue(j["ok"])
        self.assertIn("injector_ready", j)
        self.assertIn("backend", j)
        self.assertIn("version", j)

    def test_index_served(self):
        code, body = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"<textarea", body)

    def test_unknown_404(self):
        self.assertEqual(self.req("GET", "/nope")[0], 404)
        self.assertEqual(self.req("POST", "/nope", b"{}", TOKEN)[0], 404)

    def test_send_no_token_401(self):
        code, _ = self.req("POST", "/send", json.dumps({"text": "hi"}).encode())
        self.assertEqual(code, 401)

    def test_send_wrong_token_401(self):
        self.assertEqual(self.send_json({"text": "hi"}, token="wrong")[0], 401)

    def test_send_non_ascii_token_no_crash(self):
        # latin-1 范围内的非 ASCII token（http.client 只允许 latin-1 头）：
        # 服务端 encode 防护路径不应崩溃，应正常 401
        self.assertEqual(self.send_json({"text": "hi"}, token="tökén")[0], 401)

    def test_options_not_supported(self):
        # 不响应 OPTIONS → 跨站自定义头 preflight 失败 → CSRF 被浏览器拦下
        code, _ = self.req("OPTIONS", "/send")
        self.assertEqual(code, 501)

    # ---------- /send 行为 ----------

    def test_send_ok(self):
        code, body = self.send_json({"text": "你好，世界"})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.fake.calls, [("你好，世界", False, False)])

    def test_send_flags_passthrough(self):
        code, _ = self.send_json({"text": "ls -la", "terminal_mode": True, "enter": True})
        self.assertEqual(code, 200)
        self.assertEqual(self.fake.calls, [("ls -la", True, True)])

    def test_empty_text_400(self):
        self.assertEqual(self.send_json({"text": ""})[0], 400)
        self.assertEqual(self.send_json({"text": "   \n"})[0], 400)
        self.assertEqual(self.send_json({})[0], 400)

    def test_invalid_json_400(self):
        self.assertEqual(self.req("POST", "/send", b"not json", TOKEN)[0], 400)

    def test_empty_body_400(self):
        self.assertEqual(self.req("POST", "/send", b"", TOKEN)[0], 400)

    def test_oversize_413(self):
        self.assertEqual(self.send_json({"text": "a" * 70000})[0], 413)

    def test_copied_degradation_200(self):
        self.httpd.injector = FakeInjector(fail=InjectError("按键失败", copied=True))
        code, body = self.send_json({"text": "不丢字"})
        self.assertEqual(code, 200)
        j = json.loads(body)
        self.assertFalse(j["ok"])
        self.assertTrue(j["copied"])

    def test_hard_fail_503(self):
        self.httpd.injector = FakeInjector(fail=InjectError("wl-copy 挂了"))
        code, body = self.send_json({"text": "hi"})
        self.assertEqual(code, 503)
        self.assertFalse(json.loads(body)["copied"])

    # ---------- 后端工厂 ----------

    def test_make_injector_fallback(self):
        # Mac 无 wl-copy / dbus / uinput → 应回退原生 Injector 且不抛异常
        from injector import Injector, make_injector

        inj = make_injector()
        self.assertIsInstance(inj, Injector)
        self.assertEqual(inj.backend_name, "native-uinput")

    # ---------- 并发 ----------

    def test_concurrent_sends_no_loss(self):
        texts = ["并发测试 %d 号" % i for i in range(8)]
        errors: list[Exception] = []

        def worker(t: str):
            try:
                code, body = self.send_json({"text": t})
                if code != 200 or not json.loads(body)["ok"]:
                    errors.append(AssertionError("bad reply for %r: %s" % (t, body)))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in texts]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(c[0] for c in self.fake.calls), sorted(texts))


if __name__ == "__main__":
    unittest.main(verbosity=2)