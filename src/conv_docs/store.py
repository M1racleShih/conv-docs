"""配置存储：发布清单 + token 哈希。

配置文件（默认 ~/.config/conv_docs/config.json）以 0600 权限原子写入。
服务端只保存 token 的 SHA-256 哈希，明文只在 rotate 时打印一次。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass

SCHEMA_VERSION = 1

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class StoreError(Exception):
    """配置或发布操作错误。"""


def default_config_path() -> str:
    return os.environ.get("CONV_DOCS_CONFIG") or os.path.join(
        os.path.expanduser("~"), ".config", "conv-docs", "config.json"
    )


def default_state_dir() -> str:
    return os.environ.get("CONV_DOCS_STATE_DIR") or os.path.join(
        os.environ.get("XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state")),
        "conv-docs",
    )


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


@dataclass
class Publish:
    name: str
    path: str
    published_at: str
    docs_only: bool = False


class ConfigStore:
    """发布清单与 token 哈希的持久化。

    配置文件被其他进程（CLI）修改后，maybe_reload 会按 mtime 自动重载，
    保证 publish / unpublish / token rotate 即时生效。
    """

    def __init__(self, path: str | None = None):
        self.path = path or default_config_path()
        self.data = self._load()
        self._mtime = self._stat_mtime()

    def _stat_mtime(self) -> float:
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return 0.0

    def maybe_reload(self) -> None:
        """配置文件变化时重载（原子替换写入，读到的总是完整内容）。"""
        mtime = self._stat_mtime()
        if mtime != self._mtime:
            self.data = self._load()
            self._mtime = mtime

    # ---------- 持久化 ----------

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {
                "schema_version": SCHEMA_VERSION,
                "token_sha256": "",
                "publishes": {},
                "settings": {"skip_hidden": True, "max_render_bytes": 2 * 1024 * 1024},
            }
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"无法读取配置文件 {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise StoreError(f"配置文件格式错误: {self.path}")
        data.setdefault("publishes", {})
        data.setdefault("settings", {"skip_hidden": True, "max_render_bytes": 2 * 1024 * 1024})
        data.setdefault("token_sha256", "")
        return data

    def save(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".config.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            self._mtime = self._stat_mtime()
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ---------- token ----------

    @property
    def token_hash(self) -> str:
        return self.data.get("token_sha256", "")

    def has_token(self) -> bool:
        return bool(self.token_hash)

    def set_token(self, token: str) -> None:
        if not token or len(token) < 16:
            raise StoreError("token 太短，至少 16 个字符")
        self.data["token_sha256"] = hash_token(token)
        self.save()

    def verify_token(self, token: str) -> bool:
        import hmac

        stored = self.token_hash
        if not stored:
            return False
        return hmac.compare_digest(hash_token(token or ""), stored)

    # ---------- 发布清单 ----------

    def publish(self, path: str, name: str | None = None, docs_only: bool = False) -> Publish:
        real = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(real):
            raise StoreError(f"目录不存在: {path}")
        name = name or os.path.basename(real.rstrip(os.sep)) or "root"
        if not _NAME_RE.match(name):
            raise StoreError(f"名字只允许字母、数字、点、下划线和连字符（1-64 位）: {name!r}")
        for existing in self.data["publishes"].values():
            if existing["path"] == real:
                raise StoreError(f"该目录已以名字 {existing['name']!r} 发布")
        pub = Publish(name=name, path=real, published_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), docs_only=docs_only)
        self.data["publishes"][name] = asdict(pub)
        self.save()
        return pub

    def unpublish(self, name: str) -> bool:
        if name not in self.data["publishes"]:
            return False
        del self.data["publishes"][name]
        self.save()
        return True

    def publishes(self) -> list[Publish]:
        out = []
        for item in self.data["publishes"].values():
            out.append(Publish(**item))
        out.sort(key=lambda p: p.name)
        return out

    def get(self, name: str) -> Publish | None:
        item = self.data["publishes"].get(name)
        return Publish(**item) if item else None

    @property
    def max_render_bytes(self) -> int:
        return int(self.data.get("settings", {}).get("max_render_bytes", 2 * 1024 * 1024))

    @property
    def skip_hidden(self) -> bool:
        return bool(self.data.get("settings", {}).get("skip_hidden", True))
