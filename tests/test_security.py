"""安全原语测试：路径沙箱、文件分类、限速器。"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conv_doc.security import (  # noqa: E402
    AuthRateLimiter,
    PathViolation,
    classify,
    raw_content_type,
    resolve_within,
    verify_token,
    hash_token,
)


class PathSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(self.tmp.name, "root")
        os.makedirs(os.path.join(self.root, "sub"))
        with open(os.path.join(self.root, "sub", "doc.md"), "w") as fh:
            fh.write("hi")
        with open(os.path.join(self.root, ".secret"), "w") as fh:
            fh.write("token=abc")
        os.makedirs(os.path.join(self.root, ".git"))

    def test_normal_paths(self):
        self.assertEqual(resolve_within(self.root, "sub/doc.md"),
                         os.path.realpath(os.path.join(self.root, "sub/doc.md")))
        self.assertEqual(resolve_within(self.root, ""), os.path.realpath(self.root))

    def test_traversal_rejected(self):
        for bad in ["../outside", "sub/../../outside", "..", "sub/../../etc/passwd"]:
            with self.assertRaises(PathViolation, msg=bad):
                resolve_within(self.root, bad)

    def test_absolute_path_rejected(self):
        with self.assertRaises(PathViolation):
            resolve_within(self.root, "/etc/passwd")

    def test_nul_rejected(self):
        with self.assertRaises(PathViolation):
            resolve_within(self.root, "a\x00b")

    def test_hidden_rejected(self):
        for bad in [".secret", ".git/config", "sub/.hidden"]:
            with self.assertRaises(PathViolation, msg=bad):
                resolve_within(self.root, bad)

    def test_symlink_escape_rejected(self):
        outside = os.path.join(self.tmp.name, "outside.md")
        with open(outside, "w") as fh:
            fh.write("outside")
        os.symlink(outside, os.path.join(self.root, "escape.md"))
        with self.assertRaises(PathViolation):
            resolve_within(self.root, "escape.md")

    def test_symlink_inside_allowed(self):
        os.symlink(os.path.join(self.root, "sub", "doc.md"), os.path.join(self.root, "inner.md"))
        resolved = resolve_within(self.root, "inner.md")
        self.assertTrue(resolved.startswith(os.path.realpath(self.root)))


class ClassifyTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(classify("a.md"), "markdown")
        self.assertEqual(classify("a.markdown"), "markdown")
        self.assertEqual(classify("a.html"), "html")
        self.assertEqual(classify("a.htm"), "html")
        self.assertEqual(classify("a.txt"), "text")
        self.assertEqual(classify("a.py"), "text")
        self.assertEqual(classify("Makefile"), "text")
        self.assertEqual(classify("a.png"), "image")
        self.assertEqual(classify("a.svg"), "image")
        self.assertEqual(classify("a.pdf"), "pdf")
        self.assertIsNone(classify("a.exe"))
        self.assertIsNone(classify("noext"))

    def test_raw_content_type_never_html_for_user_text(self):
        self.assertEqual(raw_content_type("a.html", "html"), "text/plain; charset=utf-8")
        self.assertEqual(raw_content_type("a.md", "markdown"), "text/plain; charset=utf-8")
        self.assertEqual(raw_content_type("a.txt", "text"), "text/plain; charset=utf-8")
        self.assertEqual(raw_content_type("a.png", "image"), "image/png")
        self.assertEqual(raw_content_type("a.svg", "image"), "image/svg+xml")
        self.assertEqual(raw_content_type("a.pdf", "pdf"), "application/pdf")


class TokenTests(unittest.TestCase):
    def test_verify(self):
        h = hash_token("hello-token-1234")
        self.assertTrue(verify_token("hello-token-1234", h))
        self.assertFalse(verify_token("hello-token-1235", h))
        self.assertFalse(verify_token("hello-token-1234", ""))
        self.assertFalse(verify_token("", h))


class RateLimiterTests(unittest.TestCase):
    def test_lockout_after_failures(self):
        lim = AuthRateLimiter(max_failures=3, window=60, lockout=0.2)
        for _ in range(3):
            lim.record_failure("1.2.3.4")
        self.assertGreater(lim.retry_after("1.2.3.4"), 0)
        self.assertEqual(lim.retry_after("5.6.7.8"), 0)
        time.sleep(0.25)
        self.assertEqual(lim.retry_after("1.2.3.4"), 0)

    def test_success_clears(self):
        lim = AuthRateLimiter(max_failures=3, window=60, lockout=60)
        lim.record_failure("ip")
        lim.record_failure("ip")
        lim.record_success("ip")
        self.assertEqual(lim.retry_after("ip"), 0)

    def test_global_cap(self):
        lim = AuthRateLimiter(max_failures=100, window=60, lockout=0.2, global_max_failures=5)
        for i in range(5):
            lim.record_failure(f"ip-{i}")
        self.assertGreater(lim.retry_after("ip-4"), 0)  # 触发全局上限的那个键被封禁

    def test_locked_key_still_blocked_until_expiry(self):
        lim = AuthRateLimiter(max_failures=1, window=60, lockout=0.3)
        lim.record_failure("ip")
        self.assertGreater(lim.retry_after("ip"), 0)
        time.sleep(0.35)
        self.assertEqual(lim.retry_after("ip"), 0)


if __name__ == "__main__":
    unittest.main()
