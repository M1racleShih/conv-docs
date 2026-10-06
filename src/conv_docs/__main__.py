"""conv-docs 命令行入口。

    python3 -m conv_docs publish <dir> [--as NAME] [--docs-only]
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
from .store import ConfigStore, StoreError, default_config_path


def cmd_publish(args, store: ConfigStore) -> int:
    try:
        pub = store.publish(args.path, name=args.as_name, docs_only=args.docs_only)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"published {pub.name} → {pub.path}")
    if pub.docs_only:
        print("(docs-only: documents and images only)")
    return 0


def cmd_unpublish(args, store: ConfigStore) -> int:
    if store.unpublish(args.name):
        print(f"revoked {args.name}")
        return 0
    print(f"error: no publish named {args.name!r}", file=sys.stderr)
    return 1


def cmd_list(args, store: ConfigStore) -> int:
    pubs = store.publishes()
    if not pubs:
        print("no published directories (nothing is exposed by default)")
        return 0
    for pub in pubs:
        suffix = "  [docs-only]" if pub.docs_only else ""
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
    p.set_defaults(func=cmd_publish)

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
