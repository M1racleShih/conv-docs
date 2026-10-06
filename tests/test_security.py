"""安全原语测试：路径沙箱、文件分类、限速器。"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conv_docs.security import (  # noqa: E402
    AuthRateLimiter,
    PathViolation,
    classify,
    compile_excludes,
    excluded,
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
        self.assertEqual(classify("a.py"), "code")
        self.assertEqual(classify("Makefile"), "code")
        self.assertEqual(classify("a.png"), "image")
        self.assertEqual(classify("a.svg"), "image")
        self.assertEqual(classify("a.pdf"), "pdf")
        self.assertIsNone(classify("a.exe"))
        self.assertIsNone(classify("noext"))

    def test_code_vs_text_split(self):
        # 源代码与结构化数据/配置 → code（默认被过滤）
        for name in ["a.py", "x.js", "m.ts", "y.go", "z.rs", "c.cpp", "s.sh",
                     "d.json", "c.yaml", "t.toml", "i.ini", "x.xml", "notebook.ipynb",
                     "Dockerfile", "Jenkinsfile", "CODEOWNERS"]:
            self.assertEqual(classify(name), "code", name)
        # 纯文本文档与数据表 → text（默认可见）
        for name in ["a.txt", "notes.log", "r.rst", "b.adoc", "o.org",
                     "data.csv", "t.tsv", "README", "LICENSE", "CHANGELOG"]:
            self.assertEqual(classify(name), "text", name)


class ExcludeTests(unittest.TestCase):
    def test_basename_pattern_matches_any_level(self):
        c = compile_excludes(["*.env"])
        self.assertTrue(excluded(".env", c))
        self.assertTrue(excluded("config/prod.env", c))
        self.assertFalse(excluded("docs/readme.md", c))

    def test_path_pattern_root_relative(self):
        c = compile_excludes(["secrets/**", "build/*"])
        self.assertTrue(excluded("secrets/key.pem", c))
        self.assertTrue(excluded("secrets/deep/k.json", c))
        self.assertTrue(excluded("build/x.py", c))
        self.assertFalse(excluded("build/sub/y.py", c))  # 只挡一级

    def test_dir_pruning(self):
        c = compile_excludes(["secrets/**"])
        self.assertTrue(excluded("secrets", c, is_dir=True))  # 整树剪枝
        c2 = compile_excludes(["build/*"])
        self.assertFalse(excluded("build", c2, is_dir=True))  # 二级仍可见，不剪

    def test_bare_name_prunes_subtree(self):
        c = compile_excludes(["data"])
        self.assertTrue(excluded("data", c))
        self.assertTrue(excluded("a/data", c))
        self.assertTrue(excluded("data/x.csv", c))
        self.assertTrue(excluded("a/data/y", c))

    def test_question_mark_and_empty(self):
        c = compile_excludes(["a?.conf"])
        self.assertTrue(excluded("ab.conf", c))
        self.assertFalse(excluded("abc.conf", c))
        self.assertFalse(excluded("anything", compile_excludes([])))
        self.assertFalse(excluded("anything", compile_excludes(["", "  ", "/"])))

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
