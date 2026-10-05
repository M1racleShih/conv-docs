"""conv-doc 命令行入口。

    python3 -m conv_doc publish <dir> [--as NAME] [--docs-only]
    python3 -m conv_doc unpublish <name>
    python3 -m conv_doc list
    python3 -m conv_doc token rotate
    python3 -m conv_doc serve [--host 127.0.0.1] [--port 8380]
"""

from __future__ import annotations

import argparse
import secrets
import sys

from . import __version__
from .store import ConfigStore, StoreError, default_config_path


def cmd_publish(args, store: ConfigStore) -> int:
    try:
        pub = store.publish(args.path, name=args.as_name, docs_only=args.docs_only)
    except StoreError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"已发布 {pub.name} → {pub.path}")
    if pub.docs_only:
        print("（docs-only：只放行文档与图片类型）")
    return 0


def cmd_unpublish(args, store: ConfigStore) -> int:
    if store.unpublish(args.name):
        print(f"已撤销 {args.name}")
        return 0
    print(f"错误：没有名为 {args.name!r} 的发布", file=sys.stderr)
    return 1


def cmd_list(args, store: ConfigStore) -> int:
    pubs = store.publishes()
    if not pubs:
        print("当前没有任何发布目录（默认不暴露任何文件）")
        return 0
    for pub in pubs:
        suffix = "  [docs-only]" if pub.docs_only else ""
        print(f"{pub.name:24s} → {pub.path}{suffix}  (发布于 {pub.published_at})")
    return 0


def cmd_token(args, store: ConfigStore) -> int:
    if args.action != "rotate":
        print("错误：未知操作", file=sys.stderr)
        return 1
    token = secrets.token_urlsafe(32)
    store.set_token(token)
    print("新的访问 token（只显示这一次，请保存到手机）：")
    print()
    print(f"    {token}")
    print()
    print("旧 token 已失效。手机端重新输入即可。")
    return 0


def cmd_serve(args, store: ConfigStore) -> int:
    if not store.has_token():
        print("错误：还没有设置访问 token，先运行：python3 -m conv_doc token rotate", file=sys.stderr)
        return 1
    from .server import serve

    serve(args.host, args.port, store)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conv-doc",
        description="只读文档网关：把显式发布的 workspace 目录安全地送到手机端",
    )
    parser.add_argument("--version", action="version", version=f"conv-doc {__version__}")
    parser.add_argument("--config", default=None, help=f"配置文件路径（默认 {default_config_path()}）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("publish", help="显式发布一个目录")
    p.add_argument("path", help="要发布的目录（绝对或相对路径）")
    p.add_argument("--as", dest="as_name", default=None, help="发布名（默认目录名）")
    p.add_argument("--docs-only", action="store_true", help="只放行文档与图片类型")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("unpublish", help="撤销一个发布")
    p.add_argument("name")
    p.set_defaults(func=cmd_unpublish)

    p = sub.add_parser("list", help="查看发布清单")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("token", help="管理访问 token")
    p.add_argument("action", choices=["rotate"], help="rotate：生成新 token 并使旧的失效")
    p.set_defaults(func=cmd_token)

    p = sub.add_parser("serve", help="启动只读服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8380)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = ConfigStore(args.config)
    except StoreError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return args.func(args, store)


if __name__ == "__main__":
    sys.exit(main())
