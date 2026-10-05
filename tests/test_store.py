"""配置存储测试：发布生命周期、token 哈希、文件权限。"""

import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conv_docs.store import ConfigStore, StoreError  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
