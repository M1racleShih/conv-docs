"""conv-docs 命令行入口。

    python3 -m conv_docs publish <dir> [--as NAME] [--docs-only] [--project P]
                                       [--exclude GLOB ...] [--allow-code]
    python3 -m conv_docs preview <file|dir> [--as NAME] [--ttl 2h] [--once]
                                    [--exclude GLOB ...] [--allow-code] [--docs-only] [--project P]
    python3 -m conv_docs unpublish <name>
    python3 -m conv_docs list
    python3 -m conv_docs token rotate
    python3 -m conv_docs serve [--host 127.0.0.1] [--port 8380]
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys

from . import __version__
from .store import DEFAULT_PREVIEW_TTL, ConfigStore, StoreError, default_config_path, parse_ttl


def _fmt_remaining(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


def cmd_publish(args, store: ConfigStore) -> int:
    try:
        pub = store.publish(args.path, name=args.as_name, docs_only=args.docs_only,
                            project=args.project, excludes=args.exclude,
                            allow_code=args.allow_code)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"published {pub.name} → {pub.path}")
    if pub.docs_only:
        print("(docs-only: documents and images only)")
    if pub.allow_code:
        print("(allow-code: source code and data files are visible)")
    if pub.excludes:
        print(f"(excludes: {' '.join(pub.excludes)})")
    if pub.project:
        print(f"(project: {pub.project})")
    return 0


def cmd_preview(args, store: ConfigStore) -> int:
    try:
        ttl = parse_ttl(args.ttl)
        pub = store.preview(args.path, name=args.as_name, ttl=ttl, once=args.once,
                            docs_only=args.docs_only, project=args.project,
                            excludes=args.exclude, allow_code=args.allow_code)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    from .security import classify
    if os.path.isfile(pub.path) and not (pub.allow_code or pub.docs_only) \
            and classify(pub.path) == "code" and store.filter_code:
        print("note: this file is code-filtered by default; viewers cannot see it without --allow-code",
              file=sys.stderr)
    suffix = " · single view" if pub.once else ""
    print(f"preview {pub.name} → {pub.path}  (expires in {_fmt_remaining(ttl)}{suffix})")
    if pub.excludes:
        print(f"(excludes: {' '.join(pub.excludes)})")
    if pub.project:
        print(f"(project: {pub.project})")
    print("temporary preview: it disappears automatically when expired")
    return 0


def cmd_unpublish(args, store: ConfigStore) -> int:
    if store.unpublish(args.name):
        print(f"revoked {args.name}")
        return 0
    print(f"error: no publish named {args.name!r}", file=sys.stderr)
    return 1


def cmd_list(args, store: ConfigStore) -> int:
    store.purge_expired()
    pubs = store.publishes()
    if not pubs:
        print("no published directories (nothing is exposed by default)")
        return 0
    for pub in pubs:
        tags = []
        if pub.is_preview:
            remaining = store.preview_remaining(pub)
            if pub.once:
                tags.append("preview · single view" + (f" · burning ({_fmt_remaining(remaining)})" if pub.burned_at else ""))
            else:
                tags.append(f"preview · {_fmt_remaining(remaining) if remaining is not None else '—'} left")
        if pub.docs_only:
            tags.append("docs-only")
        if pub.allow_code:
            tags.append("allow-code")
        if pub.project:
            tags.append(f"project:{pub.project}")
        if pub.excludes:
            tags.append(f"excludes:{len(pub.excludes)}")
        suffix = f"  [{' | '.join(tags)}]" if tags else ""
        print(f"{pub.name:24s} → {pub.path}{suffix}  (published at {pub.published_at})")
    return 0


def cmd_token(args, store: ConfigStore) -> int:
    if args.action != "rotate":
        print("error: unknown action", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(32)
    store.set_token(token)
    # 同时写入 config 同目录的 token.txt（0600），避免明文只留在终端回显里
    token_file = os.path.join(os.path.dirname(store.path), "token.txt")
    try:
        with open(token_file, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
        os.chmod(token_file, 0o600)
    except OSError:
        token_file = ""
    print("New access token (shown once — save it for your phone):")
    print()
    print(f"    {token}")
    print()
    if token_file:
        print(f"Saved to {token_file} (0600)")
    print("The old token is now invalid. Re-enter the new one on your phone.")
    return 0


def cmd_serve(args, store: ConfigStore) -> int:
    if not store.has_token():
        print("error: no access token yet; run: python3 -m conv_docs token rotate", file=sys.stderr)
        return 1
    from .server import serve

    serve(args.host, args.port, store)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conv-docs",
        description="read-only document gateway: serve explicitly published workspace docs securely to your phone",
    )
    parser.add_argument("--version", action="version", version=f"conv-docs {__version__}")
    parser.add_argument("--config", default=None, help=f"config file path (default {default_config_path()})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("publish", help="explicitly publish a directory")
    p.add_argument("path", help="directory to publish (absolute or relative)")
    p.add_argument("--as", dest="as_name", default=None, help="publish name (defaults to the directory name)")
    p.add_argument("--docs-only", action="store_true", help="allow documents and images only")
    p.add_argument("--project", default=None, metavar="NAME",
                   help="group this publish under a project (implicit, groups the web UI)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="exclude pattern, repeatable (e.g. --exclude '*.env' --exclude 'secrets/**')")
    p.add_argument("--allow-code", action="store_true",
                   help="show source code and data/config files (hidden by default)")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("preview", help="temporary preview that expires (file or directory)")
    p.add_argument("path", help="file or directory to preview (absolute or relative)")
    p.add_argument("--as", dest="as_name", default=None, help="preview name (defaults to the file/directory name)")
    p.add_argument("--ttl", default=str(DEFAULT_PREVIEW_TTL), metavar="DUR",
                   help="lifetime, e.g. 30m / 2h / 7d or plain seconds (default 24h; max 30d)")
    p.add_argument("--once", action="store_true",
                   help="burn after first view: expires 10 minutes after the first content access")
    p.add_argument("--docs-only", action="store_true", help="allow documents and images only")
    p.add_argument("--project", default=None, metavar="NAME", help="group this preview under a project")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="exclude pattern, repeatable")
    p.add_argument("--allow-code", action="store_true", help="show source code and data/config files")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("unpublish", help="revoke a publish")
    p.add_argument("name")
    p.set_defaults(func=cmd_unpublish)

    p = sub.add_parser("list", help="show the publish list")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("token", help="manage the access token")
    p.add_argument("action", choices=["rotate"], help="rotate: generate a new token and invalidate the old one")
    p.set_defaults(func=cmd_token)

    p = sub.add_parser("serve", help="start the read-only service")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8380)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = ConfigStore(args.config)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return args.func(args, store)


if __name__ == "__main__":
    sys.exit(main())
