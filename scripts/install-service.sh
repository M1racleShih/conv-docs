#!/usr/bin/env bash
# 安装 conv-docs 为 systemd 用户服务，并给出 cloudflared ingress 配置片段。
# 幂等：重复运行会更新 unit 并重启服务。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${CONV_DOCS_PORT:-8380}"
HOST="${CONV_DOCS_HOST:-127.0.0.1}"
CONFIG="${CONV_DOCS_CONFIG:-$HOME/.config/conv-docs/config.json}"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/conv-docs.service"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ] && [ -x "$REPO_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$REPO_DIR/.venv/bin/python"   # uv sync 创建的项目环境
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
  echo "错误：找不到 python3" >&2
  exit 1
fi

# 1. 配置与 token
if [ ! -f "$CONFIG" ]; then
  echo "初始化配置：$CONFIG"
  mkdir -p "$(dirname "$CONFIG")"
  chmod 700 "$(dirname "$CONFIG")"
fi
if ! "$PYTHON_BIN" -m conv_docs --config "$CONFIG" list >/dev/null 2>&1; then
  echo "错误：conv-docs 无法载入配置（在 $REPO_DIR 下运行 python3 -m conv_docs list 检查）" >&2
  exit 1
fi

if ! grep -q '"token_sha256": "[0-9a-f]\{64\}"' "$CONFIG" 2>/dev/null; then
  echo "尚未设置访问 token，正在生成："
  (cd "$REPO_DIR" && "$PYTHON_BIN" -m conv_docs --config "$CONFIG" token rotate)
fi
# 2. systemd 用户服务
mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=conv-docs - read-only workspace docs gateway
After=network-online.target

[Service]
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON_BIN -m conv_docs --config $CONFIG serve --host $HOST --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now conv-docs.service
sleep 1
systemctl --user --no-pager status conv-docs.service | head -8 || true

# 3. cloudflared ingress 片段
HOSTNAME="${CONV_DOCS_HOSTNAME:-docs.你的域名}"
cat <<EOF

─── 下一步：接入 Cloudflare Tunnel ───────────────────────────────

在 cloudflared 的配置文件（通常 ~/.cloudflared/config.yml）的 ingress
规则里，为文档服务新增一条，注意放在最后的 catch-all 之前：

  ingress:
    - hostname: $HOSTNAME
      service: http://$HOST:$PORT
    # ...已有的 relay 规则保持不变...
    - service: http_status:404

然后让 DNS 指向隧道并重载配置：

  cloudflared tunnel route dns <你的隧道名> $HOSTNAME
  cloudflared tunnel ingress validate
  systemctl --user restart cloudflared   # 或你现有的 cloudflared 服务

已有的 ingress 规则与 token 无需任何改动。

手机端打开 https://$HOSTNAME ，输入 token。

常用命令（在 $REPO_DIR 下，uv run conv-docs 等价于 python3 -m conv_docs）：

  uv run conv-docs token rotate   # 轮换 token（旧的立即失效）
  uv run conv-docs list           # 查看发布清单
EOF
