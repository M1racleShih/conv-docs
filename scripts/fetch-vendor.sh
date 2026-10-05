#!/usr/bin/env bash
# 重新拉取固定版本的前端渲染依赖（vendor）。
# 平时不需要运行——仓库已内置这些文件；仅在升级版本时使用。
set -euo pipefail

VENDOR_DIR="$(cd "$(dirname "$0")/.." && pwd)/conv_doc/web/vendor"
MARKED_VER="18.0.14"
DOMPURIFY_VER="3.4.16"
HLJS_VER="11.12.0"

mkdir -p "$VENDOR_DIR"
cd "$VENDOR_DIR"

echo "marked v${MARKED_VER} (MIT)"
curl -fsSL -o marked.umd.js "https://cdn.jsdelivr.net/npm/marked@${MARKED_VER}/lib/marked.umd.js"
curl -fsSL -o LICENSE.marked.txt "https://raw.githubusercontent.com/markedjs/marked/v${MARKED_VER}/LICENSE"

echo "DOMPurify ${DOMPURIFY_VER} (Apache-2.0)"
curl -fsSL -o purify.min.js "https://cdn.jsdelivr.net/npm/dompurify@${DOMPURIFY_VER}/dist/purify.min.js"
curl -fsSL -o LICENSE.dompurify.txt "https://raw.githubusercontent.com/cure53/DOMPurify/${DOMPURIFY_VER}/LICENSE"

echo "highlight.js v${HLJS_VER} (BSD-3-Clause)"
curl -fsSL -o highlight.min.js "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@${HLJS_VER}/build/highlight.min.js"
curl -fsSL -o github.min.css "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@${HLJS_VER}/build/styles/github.min.css"
curl -fsSL -o LICENSE.highlightjs.txt "https://raw.githubusercontent.com/highlightjs/highlight.js/${HLJS_VER}/LICENSE"

echo "完成：$VENDOR_DIR"
