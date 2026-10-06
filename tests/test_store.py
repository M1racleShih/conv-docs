"""配置存储测试：发布/预览生命周期、token 哈希、文件权限。"""

import json
import os
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conv_docs.store import DEFAULT_PREVIEW_TTL, ConfigStore, StoreError, parse_ttl  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "config.json")
        self.store = ConfigStore(self.config)

    def test_publish_unpublish_roundtrip(self):
        target = os.path.join(self.tmp.name, "ws1")
        os.makedirs(target)
        pub = self.store.publish(target, name="ws1")
        self.assertEqual(pub.name, "ws1")
        self.assertEqual(pub.path, os.path.realpath(target))

        reloaded = ConfigStore(self.config)
        self.assertEqual([p.name for p in reloaded.publishes()], ["ws1"])
        self.assertTrue(reloaded.unpublish("ws1"))
        self.assertFalse(reloaded.unpublish("ws1"))
        self.assertEqual(ConfigStore(self.config).publishes(), [])

    def test_publish_missing_dir_rejected(self):
        with self.assertRaises(StoreError):
            self.store.publish(os.path.join(self.tmp.name, "nope"))

    def test_publish_duplicate_path_rejected(self):
        target = os.path.join(self.tmp.name, "ws")
        os.makedirs(target)
        self.store.publish(target, name="a")
        with self.assertRaises(StoreError):
            self.store.publish(target, name="b")

    def test_publish_bad_name_rejected(self):
        target = os.path.join(self.tmp.name, "ws")
        os.makedirs(target)
        with self.assertRaises(StoreError):
            self.store.publish(target, name="../evil")
        with self.assertRaises(StoreError):
            self.store.publish(target, name="name with space")

    def test_token_stored_as_hash_only(self):
        token = "s3cret-token-value-123456"
        self.store.set_token(token)
        with open(self.config, "r", encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn(token, raw)
        self.assertIn("token_sha256", raw)

        self.assertTrue(self.store.verify_token(token))
        self.assertFalse(self.store.verify_token(token + "x"))
        self.assertFalse(self.store.verify_token(""))
        self.assertFalse(ConfigStore(self.config).verify_token("wrong"))

    def test_short_token_rejected(self):
        with self.assertRaises(StoreError):
            self.store.set_token("short")

    def test_config_file_mode_0600(self):
        self.store.set_token("s3cret-token-value-123456")
        mode = stat.S_IMODE(os.stat(self.config).st_mode)
        self.assertEqual(mode, 0o600)

    def test_no_token_means_no_auth(self):
        self.assertFalse(self.store.has_token())
        self.assertFalse(self.store.verify_token("anything"))

    def test_hot_reload_picks_up_external_changes(self):
        target = os.path.join(self.tmp.name, "external")
        os.makedirs(target)
        other = ConfigStore(self.config)
        other.publish(target, name="ext")
        # self.store 早于外部修改创建，maybe_reload 后应看到
        self.assertEqual(self.store.publishes(), [])
        self.store.maybe_reload()
        self.assertEqual([p.name for p in self.store.publishes()], ["ext"])


class TtlTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_ttl("90"), 90)
        self.assertEqual(parse_ttl("30s"), 30)
        self.assertEqual(parse_ttl("30m"), 1800)
        self.assertEqual(parse_ttl("2h"), 7200)
        self.assertEqual(parse_ttl("7d"), 604800)
        self.assertEqual(parse_ttl("2H"), 7200)
        self.assertEqual(parse_ttl(120), 120)

    def test_invalid(self):
        for bad in ["xx", "", "-5", "0", "1y", str(60 * 60 * 24 * 31)]:
            with self.assertRaises(StoreError, msg=bad):
                parse_ttl(bad)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "config.json")
        self.store = ConfigStore(self.config)
        self.dir = os.path.join(self.tmp.name, "report")
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "a.md"), "w") as fh:
            fh.write("hi")
        self.file = os.path.join(self.tmp.name, "note.md")
        with open(self.file, "w") as fh:
            fh.write("note")

    def test_preview_single_file_and_defaults(self):
        pub = self.store.preview(self.file)
        self.assertTrue(pub.is_preview)
        self.assertEqual(pub.name, "note.md")
        self.assertAlmostEqual(pub.expires_at - time.time(), DEFAULT_PREVIEW_TTL, delta=5)
        self.assertFalse(pub.once)

    def test_preview_directory(self):
        pub = self.store.preview(self.dir, ttl=60, once=True, project="p1", excludes=["*.env"])
        self.assertTrue(pub.once)
        self.assertEqual(pub.project, "p1")
        self.assertEqual(pub.excludes, ["*.env"])
        self.assertAlmostEqual(pub.expires_at - time.time(), 60, delta=5)

    def test_same_path_replaces_and_resets(self):
        first = self.store.preview(self.file, name="p", ttl=60)
        time.sleep(0.02)
        second = self.store.preview(self.file, name="p", ttl=3600)
        self.assertEqual(second.name, "p")
        self.assertGreater(second.expires_at, first.expires_at)
        self.assertEqual(len([e for e in self.store.publishes() if e.path == first.path]), 1)

    def test_auto_name_suffix_on_conflict(self):
        self.store.preview(self.file, name="taken", ttl=60)
        other = self.store.preview(self.dir, ttl=60)  # basename report 空闲
        self.assertEqual(other.name, "report")
        # 同名占用：另一路径自动加后缀
        conflict = tempfile.mkdtemp(dir=self.tmp.name, prefix="report")
        fourth = self.store.preview(conflict, ttl=60)
        self.assertTrue(fourth.name.startswith("report"))
        self.assertNotEqual(fourth.name, "report")

    def test_preview_over_permanent_publish_rejected(self):
        self.store.publish(self.dir, name="perm")
        with self.assertRaises(StoreError):
            self.store.preview(self.dir)

    def test_publish_name_conflict_rejected(self):
        self.store.publish(self.dir, name="a")
        other_dir = os.path.join(self.tmp.name, "other")
        os.makedirs(other_dir)
        with self.assertRaises(StoreError):
            self.store.publish(other_dir, name="a")

    def test_ttl_expiry_purged(self):
        self.store.preview(self.file, name="gone", ttl=1)
        self.store.data["publishes"]["gone"]["expires_at"] = time.time() - 1
        self.assertEqual(self.store.purge_expired(), 1)
        self.assertIsNone(self.store.get("gone"))

    def test_once_burn_grace_window(self):
        pub = self.store.preview(self.file, name="burn", ttl=3600, once=True)
        self.assertFalse(ConfigStore.is_entry_expired(self.store.data["publishes"]["burn"]))
        self.assertTrue(self.store.mark_burned("burn"))
        self.assertFalse(self.store.mark_burned("burn"))  # 幂等
        remaining = self.store.preview_remaining(self.store.get("burn"))
        self.assertTrue(0 < remaining <= ConfigStore.BURN_GRACE)
        # 宽限窗过后过期
        self.store.data["publishes"]["burn"]["burned_at"] = time.time() - ConfigStore.BURN_GRACE - 1
        self.assertTrue(ConfigStore.is_entry_expired(self.store.data["publishes"]["burn"]))
        self.assertEqual(self.store.purge_expired(), 1)

    def test_maybe_reload_also_purges(self):
        self.store.preview(self.file, name="gone2", ttl=3600)
        # 直接把磁盘上的过期时间改为过去，再触发重载
        with open(self.config, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["publishes"]["gone2"]["expires_at"] = time.time() - 1
        with open(self.config, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.utime(self.config)  # 确保 mtime 变化被察觉
        self.store.maybe_reload()
        self.assertIsNone(self.store.get("gone2"))

    def test_backward_compat_old_config(self):
        # 旧版 config（无新字段）应可加载并补默认值
        self.store.publish(self.dir, name="old")
        with open(self.config, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ["project", "excludes", "allow_code", "expires_at", "once", "burned_at"]:
            del data["publishes"]["old"][key]
        del data["settings"]["filter_code"]
        with open(self.config, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        reloaded = ConfigStore(self.config)
        pub = reloaded.get("old")
        self.assertEqual(pub.project, "")
        self.assertEqual(pub.excludes, [])
        self.assertFalse(pub.allow_code)
        self.assertTrue(reloaded.filter_code)  # 新默认

    def test_publish_new_fields(self):
        pub = self.store.publish(self.dir, name="full", project="demo",
                                 excludes=["*.env", "secrets/**"], allow_code=True)
        self.assertEqual(pub.project, "demo")
        self.assertEqual(pub.excludes, ["*.env", "secrets/**"])
        self.assertTrue(pub.allow_code)
        self.assertFalse(pub.is_preview)
        # 重建后字段保留
        again = ConfigStore(self.config).get("full")
        self.assertEqual(again.project, "demo")
        self.assertEqual(again.excludes, ["*.env", "secrets/**"])
        self.assertTrue(again.allow_code)

    def test_bad_project_and_excludes_rejected(self):
        with self.assertRaises(StoreError):
            self.store.publish(self.dir, project="../evil")
        with self.assertRaises(StoreError):
            self.store.publish(self.dir, project="has space")
        with self.assertRaises(StoreError):
            self.store.publish(self.dir, excludes=["x" * 300])
        with self.assertRaises(StoreError):
            self.store.publish(self.dir, excludes=[f"e{i}" for i in range(40)])


if __name__ == "__main__":
    unittest.main()
