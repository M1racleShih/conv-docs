"""安全原语：路径沙箱、文件分类、token 校验、认证失败限速。"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
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
# 纯文本文档与数据表：默认可见
TEXT_EXTS = {"txt", "text", "log", "rst", "adoc", "org", "csv", "tsv"}
# 源代码与结构化数据/配置：默认被代码过滤挡住（--allow-code 放行）
CODE_EXTS = {
    "json", "yaml", "yml", "toml", "ini", "cfg", "conf", "properties", "env.example",
    "py", "pyi", "js", "mjs", "cjs", "ts", "tsx", "jsx", "css", "scss", "less",
    "java", "kt", "kts", "go", "rs", "rb", "php", "swift", "m", "mm", "cs", "fs",
    "c", "h", "cc", "cpp", "hpp", "hh", "sh", "bash", "zsh", "fish", "ps1", "bat",
    "sql", "xml", "svgz", "vue", "svelte", "lua", "pl", "r", "dart", "gradle",
    "cmake", "mk", "make", "nix", "zig", "proto", "graphql", "gql", "ipynb",
}
# 无扩展名的特殊文件名：文档类（text）
SPECIAL_DOC_NAMES = {"license", "copying", "notice", "readme", "changelog"}
# 无扩展名的特殊文件名：构建/代码类（code）
SPECIAL_CODE_NAMES = {
    "makefile", "dockerfile", "jenkinsfile", "procfile", "gemfile",
    "rakefile", "cmakelists.txt", "codeowners", "vagrantfile",
}


def classify(name: str) -> str | None:
    """返回文件渲染类别：markdown / html / text / code / image / pdf；不支持则 None。

    code = 源代码与结构化数据/配置，受代码过滤管控（默认不可见）。
    """
    base = os.path.basename(name)
    lowered = base.lower()
    if lowered in SPECIAL_DOC_NAMES:
        return "text"
    if lowered in SPECIAL_CODE_NAMES:
        return "code"
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
    if ext in CODE_EXTS:
        return "code"
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


# ---------- exclude 规则（发布/预览时显式排除敏感路径） ----------


def _glob_seg(seg: str) -> str:
    """单个路径段转 regex：** → .*，* → [^/]*，? → [^/]，其余转义。"""
    out: list[str] = []
    i = 0
    while i < len(seg):
        ch = seg[i]
        if ch == "*":
            if i + 1 < len(seg) and seg[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
            continue
        if ch == "?":
            out.append("[^/]")
            i += 1
            continue
        out.append(re.escape(ch))
        i += 1
    return "".join(out)


def compile_excludes(patterns: list[str]) -> list[tuple[re.Pattern, bool, str]]:
    """把 exclude 模式编译为 (regex, 含路径分隔符, 规范化模式)。

    语义（类 .gitignore 简化版）：
    - 模式不含 "/"：匹配任意层级的文件名（如 ``*.env`` 挡住所有层级的 .env）；
    - 模式含 "/"：相对发布根的整体路径匹配（如 ``secrets/**``、``build/*``）。
    """
    compiled: list[tuple[re.Pattern, bool, str]] = []
    for pattern in patterns or []:
        pat = (pattern or "").strip().replace("\\", "/").strip("/")
        if not pat or pat == ".":
            continue
        has_sep = "/" in pat
        regex = "/".join(_glob_seg(seg) for seg in pat.split("/"))
        compiled.append((re.compile("^(?:" + regex + ")$"), has_sep, pat))
    return compiled


def excluded(rel: str, compiled: list[tuple[re.Pattern, bool, str]], *, is_dir: bool = False) -> bool:
    """判断相对路径 rel 是否被 exclude 规则命中。

    - 含分隔符模式：整体路径匹配（``secrets/**``、``build/*``）；
    - 不含分隔符模式：匹配任意一段（``data`` 命中 data、data/x、a/data/y
      ——同名目录整棵子树被剪；``*.env`` 命中任意层 .env 文件）；
    - ``secrets/**`` 额外剪掉 secrets 目录本身；``build/*`` 只过滤一级条目，
      不剪 build 目录（二级内容仍可见）。
    """
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel or not compiled:
        return False
    segments = rel.split("/")
    for regex, has_sep, pat in compiled:
        if regex.match(rel):
            return True
        if not has_sep and any(regex.match(seg) for seg in segments):
            return True
    if is_dir:
        for _regex, _has_sep, pat in compiled:
            if pat.endswith("/**") and rel == pat[: -len("/**")].rstrip("/"):
                return True
    return False


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
