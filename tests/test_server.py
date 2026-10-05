"""HTTP 服务测试：认证、只读约束、发布范围、路径沙箱、响应头、HTML ticket。"""

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conv_doc.server import DocgateServer  # noqa: E402
from conv_doc.store import ConfigStore  # noqa: E402

TOKEN = "test-token-abcdefgh-12345678"


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.config_path = os.path.join(cls.tmp.name, "config.json")
        cls.store = ConfigStore(cls.config_path)
        cls.store.set_token(TOKEN)

        # 发布根 1：含 markdown / html / 文本 / 图片 / 隐藏文件 / 不支持类型
        cls.root_dir = os.path.join(cls.tmp.name, "ws")
        os.makedirs(os.path.join(cls.root_dir, "sub"))
        os.makedirs(os.path.join(cls.root_dir, ".git"))
        files = {
            "readme.md": "# 标题\n\n```python\nprint(1)\n```\n\n[链接](sub/note.md)\n",
            "sub/note.md": "## note\n\n![图](img.png)\n",
            "sub/page.html": "<html><head><style>h1{color:red}</style></head>"
                             "<body><h1 onclick=\"x()\">hi</h1><script>bad()</script></body></html>",
            "sub/img.png": b"\x89PNG\r\n\x1a\nfakepng",
            "data.json": "{\"a\": 1}",
            "notes.yaml": "key: value",
            "tool.exe": "binary-ish",
            ".git/config": "secret",
            ".env": "KEY=1",
        }
        for rel, content in files.items():
            full = os.path.join(cls.root_dir, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            mode = "wb" if isinstance(content, bytes) else "w"
            with open(full, mode) as fh:
                fh.write(content)

        # 发布根 2：另一个 workspace
        cls.root2_dir = os.path.join(cls.tmp.name, "ws2")
        os.makedirs(cls.root2_dir)
        with open(os.path.join(cls.root2_dir, "only.md"), "w") as fh:
            fh.write("ws2")

        cls.store.publish(cls.root_dir, name="ws")
        cls.store.publish(cls.root2_dir, name="ws2")

        cls.server = DocgateServer(("127.0.0.1", 0), cls.store,
                                   audit=__import__("conv_doc.server", fromlist=["AuditLog"]).AuditLog(
                                       os.path.join(cls.tmp.name, "audit.log")))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    # ---------- 辅助 ----------

    def request(self, path, method="GET", headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        res = conn.getresponse()
        data = res.read()
        out = (res.status, dict(res.getheaders()), data)
        conn.close()
        return out

    def authed(self, path, token=TOKEN, method="GET"):
        return self.request(path, method=method, headers={"Authorization": "Bearer " + token})

    def json_of(self, data):
        return json.loads(data.decode("utf-8"))

    # ---------- 认证（R4） ----------

    def test_health_no_auth(self):
        status, headers, data = self.request("/api/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(self.json_of(data)["ok"])
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_api_requires_token(self):
        for path in ["/api/v1/roots", "/api/v1/tree?root=ws", "/api/v1/raw?root=ws&path=readme.md"]:
            status, headers, _ = self.request(path)
            self.assertEqual(status, 401, path)
            self.assertEqual(headers.get("WWW-Authenticate"), "Bearer")

    def test_wrong_token_rejected(self):
        status, _, _ = self.authed("/api/v1/roots", token="wrong-token-12345678")
        self.assertEqual(status, 401)

    def test_auth_failure_rate_limit(self):
        # 专用来源键触发封禁
        for _ in range(11):
            self.request("/api/v1/roots", headers={
                "Authorization": "Bearer nope-nope-nope", "Cf-Connecting-Ip": "9.9.9.9"})
        status, _, _ = self.request("/api/v1/roots", headers={
            "Authorization": "Bearer " + TOKEN, "Cf-Connecting-Ip": "9.9.9.9"})
        self.assertEqual(status, 429)
        # 其他来源不受影响
        status, _, _ = self.authed("/api/v1/roots")
        self.assertEqual(status, 200)

    def test_config_hot_reload_publish_and_unpublish(self):
        # 服务持有的 store 是启动时加载的；CLI（另一进程）修改配置后应自动生效
        hot_dir = os.path.join(self.tmp.name, "ws-hot")
        os.makedirs(hot_dir, exist_ok=True)
        with open(os.path.join(hot_dir, "hot.md"), "w") as fh:
            fh.write("# hot")
        cli_store = ConfigStore(self.config_path)
        cli_store.publish(hot_dir, name="ws-hot")
        try:
            status, _, data = self.authed("/api/v1/roots")
            self.assertEqual(status, 200)
            self.assertIn("ws-hot", {r["name"] for r in self.json_of(data)["roots"]})
        finally:
            cli_store.unpublish("ws-hot")
        status, _, data = self.authed("/api/v1/roots")
        self.assertNotIn("ws-hot", {r["name"] for r in self.json_of(data)["roots"]})

    # ---------- 明确授权（R1） ----------

    def test_roots_lists_only_published(self):
        status, _, data = self.authed("/api/v1/roots")
        self.assertEqual(status, 200)
        names = {r["name"] for r in self.json_of(data)["roots"]}
        self.assertEqual(names, {"ws", "ws2"})

    def test_unpublished_root_hidden(self):
        status, _, _ = self.authed("/api/v1/tree?root=not-published")
        self.assertEqual(status, 404)

    def test_tree_hides_hidden_and_unsupported(self):
        status, _, data = self.authed("/api/v1/tree?root=ws&path=")
        self.assertEqual(status, 200)
        names = {e["name"] for e in self.json_of(data)["entries"]}
        self.assertIn("readme.md", names)
        self.assertIn("sub", names)
        self.assertNotIn(".git", names)
        self.assertNotIn(".env", names)
        self.assertNotIn("tool.exe", names)  # 不支持的类型不出现在列表

    def test_hidden_file_not_readable(self):
        for path in [".env", ".git/config"]:
            status, _, _ = self.authed(f"/api/v1/raw?root=ws&path={path}")
            self.assertEqual(status, 404, path)

    def test_unsupported_type_not_readable(self):
        status, _, _ = self.authed("/api/v1/raw?root=ws&path=tool.exe")
        self.assertEqual(status, 404)

    def test_traversal_rejected(self):
        for path in ["../ws2/only.md", "..%2F..%2Fetc%2Fpasswd", "sub/../../ws2/only.md"]:
            status, _, _ = self.authed(f"/api/v1/raw?root=ws&path={path}")
            self.assertIn(status, (400, 404), path)

    def test_symlink_escape_not_readable(self):
        os.symlink(os.path.join(self.tmp.name, "outside.md"), os.path.join(self.root_dir, "escape.md"))
        try:
            status, _, _ = self.authed("/api/v1/raw?root=ws&path=escape.md")
            self.assertEqual(status, 404)
        finally:
            os.unlink(os.path.join(self.root_dir, "escape.md"))

    # ---------- 只读（R2） ----------

    def test_write_methods_rejected(self):
        for method in ["POST", "PUT", "PATCH", "DELETE", "MKCOL", "PROPFIND", "MOVE", "COPY", "LOCK"]:
            status, headers, _ = self.request("/api/v1/roots", method=method,
                                              headers={"Authorization": "Bearer " + TOKEN},
                                              body=b"x")
            self.assertEqual(status, 405, method)
            self.assertEqual(headers.get("Allow"), "GET, HEAD")

    # ---------- 渲染与内容类型（R3） ----------

    def test_raw_markdown_is_plain_text(self):
        status, headers, data = self.authed("/api/v1/raw?root=ws&path=readme.md")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertIn(b"# \xe6\xa0\x87\xe9\xa2\x98", data)  # 原文，不带渲染
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_raw_html_never_served_as_html(self):
        status, headers, data = self.authed("/api/v1/raw?root=ws&path=sub/page.html")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertNotIn("text/html", headers["Content-Type"])
        self.assertIn(b"<script>bad()</script>", data)

    def test_raw_image_content_type(self):
        status, headers, _ = self.authed("/api/v1/raw?root=ws&path=sub/img.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")

    def test_meta_endpoint(self):
        status, _, data = self.authed("/api/v1/meta?root=ws&path=sub/page.html")
        self.assertEqual(status, 200)
        meta = self.json_of(data)
        self.assertEqual(meta["kind"], "html")
        self.assertIn("max_render_bytes", meta)

    def test_no_cors_headers(self):
        status, headers, _ = self.authed("/api/v1/roots")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    # ---------- HTML 完整模式 ticket ----------

    def test_html_ticket_flow(self):
        # ticket 只能由持 token 的调用方换取
        status, _, data = self.authed("/api/v1/html-ticket?root=ws&path=sub/page.html")
        self.assertEqual(status, 200)
        ticket = self.json_of(data)["ticket"]

        # 沙箱 iframe 是浏览器导航，不带 Authorization 头；ticket 即凭证
        status, headers, body = self.request(
            f"/api/v1/rawhtml?root=ws&path=sub/page.html&ticket={ticket}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("sandbox", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertIn(b"<script>bad()</script>", body)

        # ticket 单次使用
        status, _, _ = self.request(
            f"/api/v1/rawhtml?root=ws&path=sub/page.html&ticket={ticket}")
        self.assertEqual(status, 403)

    def test_html_ticket_requires_auth(self):
        status, _, _ = self.request("/api/v1/html-ticket?root=ws&path=sub/page.html")
        self.assertEqual(status, 401)

    def test_rawhtml_rejects_missing_ticket(self):
        status, _, _ = self.request("/api/v1/rawhtml?root=ws&path=sub/page.html")
        self.assertEqual(status, 403)

    def test_ticket_bound_to_file(self):
        status, _, data = self.authed("/api/v1/html-ticket?root=ws&path=sub/page.html")
        ticket = self.json_of(data)["ticket"]
        status, _, _ = self.request(f"/api/v1/rawhtml?root=ws&path=readme.md&ticket={ticket}")
        self.assertEqual(status, 403)

    def test_ticket_expires(self):
        status, _, data = self.authed("/api/v1/html-ticket?root=ws&path=sub/page.html")
        ticket = self.json_of(data)["ticket"]
        time.sleep(31)
        status, _, _ = self.request(f"/api/v1/rawhtml?root=ws&path=sub/page.html&ticket={ticket}")
        self.assertEqual(status, 403)

    def test_rawhtml_only_for_html(self):
        status, _, data = self.authed("/api/v1/html-ticket?root=ws&path=readme.md")
        self.assertEqual(status, 404)

    # ---------- viewer 静态资源 ----------

    def test_viewer_served_with_csp(self):
        status, headers, data = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("conv-doc", data.decode("utf-8"))

    def test_vendor_served(self):
        for name in ["marked.umd.js", "purify.min.js", "highlight.min.js", "github.min.css"]:
            status, _, _ = self.request("/vendor/" + name)
            self.assertEqual(status, 200, name)


if __name__ == "__main__":
    unittest.main()
