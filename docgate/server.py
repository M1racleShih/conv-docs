"""docgate 只读 HTTP 服务。

只提供 GET/HEAD；除 /api/v1/health 外全部要求 Bearer token。
用户内容永远不以 text/html 返回（HTML 完整模式除外，且强制 CSP sandbox）。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from .security import (
    AuthRateLimiter,
    PathViolation,
    classify,
    raw_content_type,
    resolve_within,
)
from .store import ConfigStore, Publish, default_state_dir

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
VENDOR_RE = re.compile(r"^[A-Za-z0-9._-]+$")

VIEWER_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' blob: data: https:; font-src 'self'; connect-src 'self'; "
    "frame-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
# 完整模式：沙箱 + 不透明源（无 allow-same-origin）。脚本可运行，
# 但拿不到 viewer 的 token / localStorage / DOM。
RAWHTML_CSP = "sandbox allow-scripts allow-modals allow-forms; frame-ancestors 'self'"

TICKET_TTL = 30.0
MAX_URL = 4096


class TicketStore:
    """HTML 完整模式的一次性 ticket：30 秒过期、单次使用、绑定文件。"""

    def __init__(self, ttl: float = TICKET_TTL):
        self.ttl = ttl
        self._items: dict[str, tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, root: str, rel: str) -> str:
        ticket = secrets.token_urlsafe(24)
        with self._lock:
            self._prune()
            self._items[ticket] = (root, rel, time.monotonic() + self.ttl)
        return ticket

    def consume(self, ticket: str, root: str, rel: str) -> bool:
        with self._lock:
            self._prune()
            item = self._items.pop(ticket, None)
        if item is None:
            return False
        bound_root, bound_rel, expires = item
        return time.monotonic() <= expires and bound_root == root and bound_rel == rel

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if v[2] <= now]:
            del self._items[key]


class AuditLog:
    """JSONL 审计日志：只记事件与路径，永不记凭证。"""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(default_state_dir(), "audit.log")
        self._lock = threading.Lock()

    def write(self, event: str, **fields) -> None:
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event}
        record.update(fields)
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, mode=0o700, exist_ok=True)
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 审计写入失败不阻断服务


class DocgateHandler(BaseHTTPRequestHandler):
    server_version = "docgate/" + __version__
    protocol_version = "HTTP/1.1"
    timeout = 30  # 慢速连接防占用线程

    # ---------- 基础设施 ----------

    def log_message(self, fmt, *args):  # 安静默认日志，审计走 AuditLog
        pass

    @property
    def store(self) -> ConfigStore:
        return self.server.store

    @property
    def limiter(self) -> AuthRateLimiter:
        return self.server.limiter

    @property
    def audit(self) -> AuditLog:
        return self.server.audit

    def client_key(self) -> str:
        forwarded = self.headers.get("Cf-Connecting-Ip") or self.headers.get("X-Forwarded-For")
        if forwarded:
            # 信任边界：回环/隧道后的来源键。截断防日志与限速表污染。
            return forwarded.split(",")[0].strip()[:64]
        return self.client_address[0]

    def _security_headers(self, *, csp: str | None = None, xframe: str = "DENY") -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", xframe)
        if csp:
            self.send_header("Content-Security-Policy", csp)

    def send_json(self, payload, status: int = 200, extra: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error_json(self, status: int, message: str, extra: dict | None = None) -> None:
        self.send_json({"error": message}, status=status, extra=extra)

    def send_file_bytes(self, body: bytes, content_type: str, extra: dict | None = None,
                        *, csp: str | None = None, xframe: str = "DENY") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers(csp=csp, xframe=xframe)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---------- 方法白名单：只读 ----------

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def _method_not_allowed(self):
        self.close_connection = True  # 请求体不消费，直接断开防粘包
        self.send_error_json(405, "docgate 是只读服务，不接受写入类方法", extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed
    do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed
    # WebDAV 动词
    do_MKCOL = do_COPY = do_MOVE = do_PROPFIND = do_PROPPATCH = _method_not_allowed
    do_LOCK = do_UNLOCK = do_MKCALENDAR = do_REPORT = _method_not_allowed

    # ---------- 路由 ----------

    def _dispatch(self):
        try:
            self.store.maybe_reload()  # CLI 的 publish/unpublish/token 即时生效
            raw_url = self.path
            if len(raw_url) > MAX_URL:
                return self.send_error_json(414, "URL 过长")
            parts = urlsplit(raw_url)
            path = unquote(parts.path)
            query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}

            if path.startswith("/api/v1/"):
                return self._api(path, query)
            return self._static(path)
        except BrokenPipeError:
            pass
        except Exception as exc:  # 不向客户端泄漏栈信息
            try:
                self.send_error_json(500, "内部错误")
            except Exception:
                pass
            sys.stderr.write(f"[docgate] error: {exc!r}\n")

    # ---------- 静态资源（查看器自身） ----------

    def _static(self, path: str):
        if path in ("", "/", "/index.html"):
            return self._serve_web_file("index.html", "text/html; charset=utf-8", csp=VIEWER_CSP)
        if path in ("/app.js", "/app.css"):
            ctype = "application/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
            return self._serve_web_file(path.lstrip("/"), ctype, csp=VIEWER_CSP)
        if path.startswith("/vendor/"):
            name = path[len("/vendor/"):]
            if not VENDOR_RE.match(name):
                return self.send_error_json(404, "not found")
            ctype = "application/javascript; charset=utf-8" if name.endswith(".js") else \
                "text/css; charset=utf-8" if name.endswith(".css") else "text/plain; charset=utf-8"
            return self._serve_web_file(os.path.join("vendor", name), ctype, csp=VIEWER_CSP, cache=True)
        return self.send_error_json(404, "not found")

    def _serve_web_file(self, rel: str, ctype: str, *, csp: str, cache: bool = False):
        full = os.path.realpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(full):
            return self.send_error_json(404, "not found")
        with open(full, "rb") as fh:
            body = fh.read()
        extra = {"Cache-Control": "public, max-age=86400" if cache else "no-store"}
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._security_headers(csp=csp)
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---------- API ----------

    def _api(self, path: str, query: dict):
        if path == "/api/v1/health":
            return self.send_json({"ok": True, "service": "docgate", "version": __version__})

        # 完整模式的沙箱 iframe 是浏览器导航，无法携带 Authorization 头；
        # 一次性 ticket 即该端点的凭证（只能由已认证调用方换取）。
        if path == "/api/v1/rawhtml":
            return self._api_rawhtml(query)

        authed, reason = self._authenticate()
        if not authed:
            extra = {"WWW-Authenticate": "Bearer"}
            if reason == "locked":
                return self.send_error_json(429, "认证失败次数过多，请稍后再试", extra=extra)
            return self.send_error_json(401, "需要有效的访问 token", extra=extra)

        if path == "/api/v1/roots":
            return self._api_roots()
        if path == "/api/v1/tree":
            return self._api_tree(query)
        if path == "/api/v1/meta":
            return self._api_meta(query)
        if path == "/api/v1/raw":
            return self._api_raw(query)
        if path == "/api/v1/html-ticket":
            return self._api_html_ticket(query)
        return self.send_error_json(404, "not found")

    def _authenticate(self):
        token = ""
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer "):].strip()
        key = self.client_key()
        if self.limiter.retry_after(key) > 0:
            return False, "locked"
        if token and self.store.verify_token(token):
            self.limiter.record_success(key)
            return True, ""
        self.limiter.record_failure(key)
        self.audit.write("auth_fail", ip=key, path=self.path.split("?")[0])
        return False, "bad_token"

    def _kind_allowed(self, pub: Publish, kind: str | None) -> bool:
        if kind is None:
            return False
        if pub.docs_only and kind not in ("markdown", "html", "image", "pdf"):
            return False
        return True

    def _resolve(self, query: dict, *, need_file: bool = False, kind: str | None = None):
        """校验 root/path 参数，返回 (publish, abs_path)。"""
        root_name = (query.get("root") or "").strip()
        rel = (query.get("path") or "").strip()
        pub = self.store.get(root_name)
        if pub is None:
            raise PathViolation("未发布的根目录")
        try:
            full = resolve_within(pub.path, rel, skip_hidden=self.store.skip_hidden)
        except PathViolation:
            raise
        if need_file and not os.path.isfile(full):
            raise PathViolation("文件不存在")
        if kind is not None:
            file_kind = classify(full)
            if file_kind != kind:
                raise PathViolation("文件类型不匹配")
        return pub, full

    def _api_roots(self):
        roots = []
        for pub in self.store.publishes():
            try:
                entries = len([e for e in os.scandir(pub.path)
                               if not (self.store.skip_hidden and e.name.startswith("."))])
            except OSError:
                entries = 0
            roots.append({
                "name": pub.name,
                "path": pub.path,
                "docs_only": pub.docs_only,
                "entries": entries,
                "published_at": pub.published_at,
            })
        return self.send_json({"roots": roots})

    def _api_tree(self, query: dict):
        try:
            pub, full = self._resolve(query)
        except PathViolation as exc:
            return self.send_error_json(404, str(exc))
        if not os.path.isdir(full):
            return self.send_error_json(404, "不是目录")
        items = []
        try:
            with os.scandir(full) as it:
                for entry in it:
                    if self.store.skip_hidden and entry.name.startswith("."):
                        continue
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        kind = "dir"
                    elif entry.is_file(follow_symlinks=False):
                        kind = classify(entry.name)
                        if not self._kind_allowed(pub, kind):
                            continue  # 不支持/未放行的类型不出现在列表里
                    else:
                        continue  # 符号链接等一律不列出
                    items.append({
                        "name": entry.name,
                        "path": os.path.join(query.get("path", "").strip("/"), entry.name).lstrip("/"),
                        "kind": kind,
                        "size": stat.st_size,
                        "mtime": int(stat.st_mtime),
                    })
        except PermissionError:
            return self.send_error_json(403, "无权读取该目录")
        items.sort(key=lambda x: (0 if x["kind"] == "dir" else 1, x["name"].lower()))
        return self.send_json({"root": pub.name, "path": query.get("path", ""), "entries": items})

    def _api_meta(self, query: dict):
        try:
            pub, full = self._resolve(query, need_file=True)
        except PathViolation as exc:
            return self.send_error_json(404, str(exc))
        kind = classify(full)
        if not self._kind_allowed(pub, kind):
            return self.send_error_json(404, "不支持的文件类型")
        stat = os.stat(full)
        return self.send_json({
            "root": pub.name, "path": query.get("path", ""), "name": os.path.basename(full),
            "kind": kind, "size": stat.st_size, "mtime": int(stat.st_mtime),
            "max_render_bytes": self.store.max_render_bytes,
        })

    def _api_raw(self, query: dict):
        try:
            pub, full = self._resolve(query, need_file=True)
        except PathViolation as exc:
            return self.send_error_json(404, str(exc))
        kind = classify(full)
        if not self._kind_allowed(pub, kind):
            return self.send_error_json(404, "不支持的文件类型")
        size = os.path.getsize(full)
        self.audit.write("view", ip=self.client_key(), root=pub.name,
                         path=query.get("path", ""), kind=kind)
        # 流式发送，避免大文件整块读入内存
        self.send_response(200)
        self.send_header("Content-Type", raw_content_type(full, kind))
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            with open(full, "rb") as fh:
                while chunk := fh.read(64 * 1024):
                    self.wfile.write(chunk)

    def _api_html_ticket(self, query: dict):
        try:
            pub, full = self._resolve(query, need_file=True, kind="html")
        except PathViolation as exc:
            return self.send_error_json(404, str(exc))
        ticket = self.server.tickets.issue(pub.name, query.get("path", ""))
        return self.send_json({"ticket": ticket, "expires_in": int(TICKET_TTL)})

    def _api_rawhtml(self, query: dict):
        ticket = (query.get("ticket") or "").strip()
        root = (query.get("root") or "").strip()
        rel = (query.get("path") or "").strip()
        key = self.client_key()
        if self.limiter.retry_after(key) > 0:
            return self.send_error_json(429, "认证失败次数过多，请稍后再试")
        if not ticket or not self.server.tickets.consume(ticket, root, rel):
            self.limiter.record_failure(key)  # 防 ticket 爆破
            self.audit.write("ticket_reject", ip=key, root=root, path=rel)
            return self.send_error_json(403, "ticket 无效或已过期")
        try:
            pub, full = self._resolve(query, need_file=True, kind="html")
        except PathViolation as exc:
            return self.send_error_json(404, str(exc))
        with open(full, "rb") as fh:
            body = fh.read()
        self.audit.write("view_rawhtml", ip=self.client_key(), root=pub.name, path=rel)
        return self.send_file_bytes(
            body,
            "text/html; charset=utf-8",
            extra={"Cache-Control": "no-store"},
            csp=RAWHTML_CSP,
            xframe="SAMEORIGIN",
        )


class DocgateServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store: ConfigStore, audit: AuditLog | None = None):
        super().__init__(address, DocgateHandler)
        self.store = store
        self.limiter = AuthRateLimiter()
        self.tickets = TicketStore()
        self.audit = audit or AuditLog()


def serve(host: str, port: int, store: ConfigStore) -> None:
    server = DocgateServer((host, port), store)
    bound_host, bound_port = server.server_address[:2]
    print(f"docgate {__version__} 监听 http://{bound_host}:{bound_port}")
    print(f"发布根 {len(store.publishes())} 个；配置 {store.path}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("警告：服务没有绑定回环地址，请确认防火墙与隧道配置", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止服务")
    finally:
        server.server_close()
