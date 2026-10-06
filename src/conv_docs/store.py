"""Config store: publish list + token hash.

配置文件（默认 ~/.config/conv_docs/config.json）以 0600 权限原子写入。
服务端只保存 token 的 SHA-256 哈希，明文只在 rotate 时打印一次。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

DEFAULT_PREVIEW_TTL = 24 * 3600  # 预览默认存活 24 小时
MAX_TTL = 30 * 24 * 3600        # 预览最长 30 天
_TTL_RE = re.compile(r"^(\d+)([smhd]?)$", re.IGNORECASE)


class StoreError(Exception):
    """配置或发布操作错误。"""


def parse_ttl(spec: str | int) -> int:
    """解析 TTL：'30s'/'5m'/'2h'/'7d' 或纯秒数；返回秒。"""
    if isinstance(spec, int):
        seconds = spec
    else:
        m = _TTL_RE.match((spec or "").strip())
        if not m:
            raise StoreError(f"invalid --ttl value {spec!r} (examples: 30m, 2h, 7d)")
        seconds = int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2).lower()]
    if seconds <= 0:
        raise StoreError("--ttl must be positive")
    if seconds > MAX_TTL:
        raise StoreError("--ttl too large (max 30d)")
    return seconds


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
    project: str = ""            # 项目分组（空 = 未分组）
    excludes: list[str] = field(default_factory=list)  # exclude glob 模式
    allow_code: bool = False      # 放行 code 类（源代码+数据配置）
    # 临时预览（阅后即焚）：expires_at 为 epoch 秒；once 首次内容访问后起算宽限窗
    expires_at: float = 0.0
    once: bool = False
    burned_at: float = 0.0

    @property
    def is_preview(self) -> bool:
        return bool(self.expires_at) or self.once


class ConfigStore:
    """发布清单与 token 哈希的持久化。

    配置文件被其他进程（CLI）修改后，maybe_reload 会按 mtime 自动重载，
    保证 publish / unpublish / token rotate 即时生效。服务端线程也会
    调用 mark_burned / purge_expired 写入，变更路径均有锁保护。
    """

    def __init__(self, path: str | None = None):
        self.path = path or default_config_path()
        self.data = self._load()
        self._mtime = self._stat_mtime()
        self._lock = threading.Lock()

    def _stat_mtime(self) -> float:
        try:
            return os.stat(self.path).st_mtime_ns
        except OSError:
            return 0.0

    def maybe_reload(self) -> None:
        """配置文件变化时重载（原子替换写入，读到的总是完整内容）。"""
        with self._lock:
            mtime = self._stat_mtime()
            if mtime != self._mtime:
                self.data = self._load()
                self._mtime = mtime
        self.purge_expired()

    # ---------- 持久化 ----------

    def _load(self) -> dict:
        default_settings = {
            "skip_hidden": True,
            "max_render_bytes": 2 * 1024 * 1024,
            "filter_code": True,  # code 类（源代码+数据配置）默认不可见
        }
        if not os.path.exists(self.path):
            return {
                "schema_version": SCHEMA_VERSION,
                "token_sha256": "",
                "publishes": {},
                "settings": dict(default_settings),
            }
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"cannot read config file {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise StoreError(f"invalid config file format: {self.path}")
        data.setdefault("publishes", {})
        data.setdefault("settings", {})
        for key, value in default_settings.items():
            data["settings"].setdefault(key, value)
        data.setdefault("token_sha256", "")
        # 旧条目补新字段（向后兼容）
        for item in data["publishes"].values():
            item.setdefault("project", "")
            item.setdefault("excludes", [])
            item.setdefault("allow_code", False)
            item.setdefault("expires_at", 0.0)
            item.setdefault("once", False)
            item.setdefault("burned_at", 0.0)
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
            raise StoreError("token too short — at least 16 characters")
        self.data["token_sha256"] = hash_token(token)
        self.save()

    def verify_token(self, token: str) -> bool:
        import hmac

        stored = self.token_hash
        if not stored:
            return False
        return hmac.compare_digest(hash_token(token or ""), stored)

    # ---------- 发布清单 ----------

    @staticmethod
    def _validate_excludes(excludes: list[str]) -> list[str]:
        cleaned: list[str] = []
        for pattern in excludes or []:
            pat = (pattern or "").strip()
            if not pat:
                continue
            if len(pat) > 256:
                raise StoreError(f"exclude pattern too long (max 256 chars): {pat[:32]!r}…")
            cleaned.append(pat)
        if len(cleaned) > 32:
            raise StoreError("too many exclude patterns (max 32)")
        return cleaned

    @staticmethod
    def _validate_project(project: str | None) -> str:
        project = (project or "").strip()
        if project and not _NAME_RE.match(project):
            raise StoreError(
                f"project name may contain only letters, digits, dots, underscores and hyphens (1-64 chars): {project!r}"
            )
        return project

    def publish(self, path: str, name: str | None = None, docs_only: bool = False,
                project: str | None = None, excludes: list[str] | None = None,
                allow_code: bool = False) -> Publish:
        real = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(real):
            raise StoreError(f"directory does not exist: {path}")
        name = name or os.path.basename(real.rstrip(os.sep)) or "root"
        if not _NAME_RE.match(name):
            raise StoreError(f"name may contain only letters, digits, dots, underscores and hyphens (1-64 chars): {name!r}")
        project = self._validate_project(project)
        excludes = self._validate_excludes(excludes or [])
        with self._lock:
            for existing in self.data["publishes"].values():
                if existing["path"] == real:
                    raise StoreError(f"this directory is already published as {existing['name']!r}")
            if name in self.data["publishes"]:
                raise StoreError(f"the name {name!r} is already in use; choose another --as name or unpublish first")
            pub = Publish(
                name=name, path=real,
                published_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                docs_only=docs_only, project=project, excludes=excludes,
                allow_code=allow_code,
            )
            self.data["publishes"][name] = asdict(pub)
            self.save()
            return pub

    def preview(self, path: str, name: str | None = None, ttl: int = DEFAULT_PREVIEW_TTL,
                once: bool = False, docs_only: bool = False, project: str | None = None,
                excludes: list[str] | None = None, allow_code: bool = False) -> Publish:
        """临时预览：支持单文件或目录；同路径的旧预览被替换并重置计时。"""
        real = os.path.realpath(os.path.expanduser(path))
        if not (os.path.isfile(real) or os.path.isdir(real)):
            raise StoreError(f"file or directory does not exist: {path}")
        project = self._validate_project(project)
        excludes = self._validate_excludes(excludes or [])
        base = os.path.basename(real.rstrip(os.sep)) or "root"
        with self._lock:
            existing = next((e for e in self.data["publishes"].values() if e["path"] == real), None)
            if existing is not None and not (existing.get("expires_at") or existing.get("once")):
                raise StoreError(
                    f"this path is permanently published as {existing['name']!r}; unpublish it first or preview a different path"
                )
            if name is None:
                base_name = base
                occupied = self.data["publishes"].get(base_name)
                if occupied is not None and occupied.get("path") != real:
                    # 名字被其他路径占用：加随机后缀而不是覆盖
                    base_name = f"{base}-{secrets.token_hex(2)}"
                    while base_name in self.data["publishes"]:
                        base_name = f"{base}-{secrets.token_hex(2)}"
                name = base_name
            elif name in self.data["publishes"] and self.data["publishes"][name].get("path") != real:
                raise StoreError(f"the name {name!r} is already in use; choose another --as name or unpublish first")
            if not _NAME_RE.match(name):
                raise StoreError(f"name may contain only letters, digits, dots, underscores and hyphens (1-64 chars): {name!r}")
            pub = Publish(
                name=name, path=real,
                published_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                docs_only=docs_only, project=project, excludes=excludes,
                allow_code=allow_code,
                expires_at=time.time() + ttl, once=once,
            )
            self.data["publishes"][name] = asdict(pub)  # 同路径旧预览（可能不同名）→ 先清理
            for other in [n for n, e in self.data["publishes"].items() if e["path"] == real and n != name]:
                del self.data["publishes"][other]
            self.save()
            return pub

    def unpublish(self, name: str) -> bool:
        with self._lock:
            if name not in self.data["publishes"]:
                return False
            del self.data["publishes"][name]
            self.save()
            return True

    # ---------- 临时预览：过期与阅后即焚 ----------

    BURN_GRACE = 600  # once 预览首次访问后的宽限窗（秒）：一次阅读含内嵌图片够用

    @classmethod
    def is_entry_expired(cls, item: dict, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if item.get("expires_at") and now >= float(item["expires_at"]):
            return True
        if item.get("once") and item.get("burned_at") and now >= float(item["burned_at"]) + cls.BURN_GRACE:
            return True
        return False

    def purge_expired(self) -> int:
        """删除已过期/已烧尽的预览条目；返回清理数量。持久化在锁内完成。"""
        with self._lock:
            stale = [name for name, item in self.data["publishes"].items()
                     if self.is_entry_expired(item)]
            if not stale:
                return 0
            for name in stale:
                del self.data["publishes"][name]
            self.save()
            return len(stale)

    def mark_burned(self, name: str) -> bool:
        """once 预览首次内容访问时打时间戳；返回是否新点燃。"""
        with self._lock:
            item = self.data["publishes"].get(name)
            if not item or not item.get("once") or item.get("burned_at"):
                return False
            item["burned_at"] = time.time()
            self.save()
            return True

    def preview_remaining(self, pub: Publish, now: float | None = None) -> int | None:
        """预览制余秒数（非预览返回 None）；once 已点燃时返回宽限窗制余。"""
        now = time.time() if now is None else now
        if not (pub.expires_at or pub.once):
            return None
        limits = []
        if pub.expires_at:
            limits.append(max(0, int(pub.expires_at - now)))
        if pub.once and pub.burned_at:
            limits.append(max(0, int(pub.burned_at + self.BURN_GRACE - now)))
        return min(limits) if limits else None

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

    @property
    def filter_code(self) -> bool:
        """全局代码过滤开关（默认 True）；条目级 allow_code 可覆盖。"""
        return bool(self.data.get("settings", {}).get("filter_code", True))

    def code_allowed(self, pub: Publish) -> bool:
        return (not self.filter_code) or bool(pub.allow_code)
