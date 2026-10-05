"""安全原语：路径沙箱、文件分类、token 校验、认证失败限速。"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time


class PathViolation(Exception):
    """请求的路径越出了发布根，或格式非法。"""


# ---------- token ----------

def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    if not token_hash:
        return False
    return hmac.compare_digest(hash_token(token or ""), token_hash)


# ---------- 文件分类 ----------

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "avif", "ico", "svg"}
MARKDOWN_EXTS = {"md", "markdown", "mdown", "mkd"}
HTML_EXTS = {"html", "htm"}
PDF_EXTS = {"pdf"}
TEXT_EXTS = {
    "txt", "rst", "adoc", "org", "text", "log", "csv", "tsv",
    "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "properties", "env.example",
    "py", "pyi", "js", "mjs", "cjs", "ts", "tsx", "jsx", "css", "scss", "less",
    "java", "kt", "kts", "go", "rs", "rb", "php", "swift", "m", "mm", "cs", "fs",
    "c", "h", "cc", "cpp", "hpp", "hh", "sh", "bash", "zsh", "fish", "ps1", "bat",
    "sql", "xml", "svgz", "vue", "svelte", "lua", "pl", "r", "dart", "gradle",
    "cmake", "mk", "make", "nix", "zig", "proto", "graphql", "gql", "ipynb",
}
SPECIAL_TEXT_NAMES = {
    "makefile", "dockerfile", "jenkinsfile", "license", "copying", "notice",
    "procfile", "gemfile", "rakefile", "cmakelists.txt", "readme", "changelog",
    "codeowners", "vagrantfile",
}


def classify(name: str) -> str | None:
    """返回文件渲染类别：markdown / html / text / image / pdf；不支持则 None。"""
    base = os.path.basename(name)
    if base.lower() in SPECIAL_TEXT_NAMES:
        return "text"
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if not ext:
        return None
    if ext in MARKDOWN_EXTS:
        return "markdown"
    if ext in HTML_EXTS:
        return "html"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in TEXT_EXTS:
        return "text"
    return None


def raw_content_type(name: str, kind: str) -> str:
    """原始字节接口的内容类型。

    关键不变量：用户内容永远不以 text/html 返回（html 类也按 text/plain，
    渲染由前端清洗后进行）；图片/PDF 按二进制类型返回。
    """
    if kind == "image":
        ext = name.rsplit(".", 1)[-1].lower()
        return {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
            "avif": "image/avif", "ico": "image/x-icon", "svg": "image/svg+xml",
        }.get(ext, "application/octet-stream")
    if kind == "pdf":
        return "application/pdf"
    return "text/plain; charset=utf-8"


# ---------- 路径沙箱 ----------

def is_hidden(rel: str) -> bool:
    return any(part.startswith(".") for part in rel.replace("\\", "/").split("/") if part)


def resolve_within(root: str, rel: str, *, skip_hidden: bool = True) -> str:
    """把 rel 解析为 root 内的真实路径；任何逃逸尝试都抛 PathViolation。

    - 拒绝 NUL、绝对路径；
    - realpath 之后必须仍包含在 root 的 realpath 之内（挡住 ../ 与符号链接逃逸）；
    - 默认跳过隐藏文件/目录（.git、.env 等）。
    """
    rel = (rel or "").strip()
    if "\x00" in rel:
        raise PathViolation("非法路径")
    rel = rel.replace("\\", "/")
    if rel.startswith("/"):
        raise PathViolation("只接受相对路径")
    if skip_hidden and is_hidden(rel):
        raise PathViolation("隐藏路径不可访问")
    root_real = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root_real, rel))
    try:
        common = os.path.commonpath([root_real, full])
    except ValueError as exc:
        raise PathViolation("非法路径") from exc
    if common != root_real:
        raise PathViolation("路径越界")
    return full


def safe_rel(full: str, root: str) -> str:
    return os.path.relpath(full, os.path.realpath(root)).replace(os.sep, "/")


# ---------- 认证失败限速 ----------

class AuthRateLimiter:
    """按来源键（IP）记录认证失败，超阈值后封禁一段时间。

    另有全局失败计数做兜底：即使来源键可伪造，也无法无限试探 token。
    """

    def __init__(self, max_failures: int = 10, window: float = 900.0, lockout: float = 900.0,
                 global_max_failures: int = 200):
        self.max_failures = max_failures
        self.window = window
        self.lockout = lockout
        self.global_max_failures = global_max_failures
        self._failures: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._global_failures: list[float] = []
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> float:
        """剩余封禁秒数；0 表示未封禁。"""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            until = self._blocked_until.get(key, 0.0)
            return max(0.0, until - now)

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            fails = self._failures.setdefault(key, [])
            fails.append(now)
            self._global_failures.append(now)
            if len(fails) >= self.max_failures or len(self._global_failures) >= self.global_max_failures:
                self._blocked_until[key] = now + self.lockout

    def record_success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._blocked_until.pop(key, None)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        for k in list(self._failures):
            self._failures[k] = [t for t in self._failures[k] if t > cutoff]
            if not self._failures[k]:
                del self._failures[k]
        self._global_failures = [t for t in self._global_failures if t > cutoff]
        for k in list(self._blocked_until):
            if self._blocked_until[k] <= now:
                del self._blocked_until[k]
