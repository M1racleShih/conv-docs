<p align="center">
  <img src="assets/logo.svg" width="180" alt="conv-docs logo：捧着文档的可爱猫头鹰">
</p>

<h1 align="center">conv-docs</h1>

<p align="center"><b>Convenient Documents</b> —— 随时在手机上只读查看 workspace 文档。</p>

<p align="center">
  <a href="README.md">English</a> · 简体中文
</p>

---

conv-docs 把 PC 上**显式发布**的 workspace 目录，通过 [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/) 的独立子域名，以 token 认证的方式送到手机端阅读器。Markdown 与 HTML 渲染，纯只读，与 [herdr-remote](https://github.com/dcolinmorgan/herdr-remote) 的 agent 控制通道完全隔离。

📘 项目文档（双语）：

| | English | 中文 |
|---|---|---|
| 调研报告（选型依据） | [docs/en/index.html](docs/en/index.html) | [docs/zh/index.html](docs/zh/index.html) |
| 方案设计与威胁模型 | [docs/en/design.html](docs/en/design.html) | [docs/zh/design.html](docs/zh/design.html) |
| 部署与使用手册 | [docs/en/deploy.html](docs/en/deploy.html) | [docs/zh/deploy.html](docs/zh/deploy.html) |
| 安全评审（STRIDE） | [docs/en/security-review.html](docs/en/security-review.html) | [docs/zh/security-review.html](docs/zh/security-review.html) |

## 特性

- **显式授权** —— 默认零暴露；按目录 `publish` / `unpublish`，即时生效
- **纯只读** —— 只接受 GET/HEAD；WebDAV 类写入动词一律 405
- **token 认证** —— Bearer token，服务端只存 SHA-256 哈希（配置 0600），一键轮换，按来源的失败限速
- **Markdown / HTML 渲染** —— marked + DOMPurify + highlight.js（内置），交互式 HTML 另有脚本沙箱「完整模式」
- **路径沙箱** —— realpath 包含性检查、符号链接逃逸拒绝、隐藏文件跳过、扩展名白名单
- **零第三方运行时依赖** —— Python 3.10+ 标准库；查看器为无依赖 TypeScript
- **双语界面** —— 默认英文，一键切换中文

## 快速开始

```bash
uv sync                                # 创建 .venv 并锁定依赖（推荐；直接用 python3 也可以）
uv run conv-docs token rotate          # 生成 token（明文只显示一次）
uv run conv-docs publish ~/work/proj-a --as proj-a
uv run conv-docs serve                 # 127.0.0.1:8380
```

> `uv run conv-docs` 与 `python3 -m conv_docs` 等价；服务端零第三方运行时依赖。

常驻运行：`bash scripts/install-service.sh`（systemd 用户服务 + cloudflared ingress 配置片段）。

## 命令

| 命令 | 作用 |
|------|------|
| `publish <dir> [--as NAME] [--docs-only]` | 显式发布目录（`--docs-only` 只放行文档与图片） |
| `unpublish <name>` | 撤销发布 |
| `list` | 查看发布清单 |
| `token rotate` | 生成新 token 并使旧的失效（新 token 自动保存到 `~/.config/conv-docs/token.txt`） |
| `serve [--host H] [--port P]` | 启动只读服务（默认 127.0.0.1:8380） |

## 开发与验证

```bash
uv run pytest                               # 49 项单测：认证、只读、路径沙箱、ticket、响应头
TOKEN=<token> node scripts/browser-smoke.mjs # 无头 Chrome 端到端：登录→浏览→渲染→沙箱（17 项断言）
npm install && npm run build                # 重建 TypeScript 查看器（web-src/app.ts → src/conv_docs/web/app.js）
```

目录结构：

```
src/conv_docs/          Python 包：服务端（store / security / http）+ 编译产物 web 查看器
src/conv_docs/web/      查看器产物（app.js 已提交；vendor 库含各自许可证）
web-src/app.ts          查看器源码（strict TypeScript）
tests/                  测试（unittest 风格，pytest / unittest 均可跑）
scripts/                install-service.sh · fetch-vendor.sh · browser-smoke.mjs
docs/en/, docs/zh/      HTML 文档（双语）
assets/                 logo（原创美术作品，MIT）
pyproject.toml          uv 项目（运行时零依赖，dev 组含 pytest）· uv.lock 已提交
```

## 安全

威胁模型与残余风险见 [docs/zh/design.html](docs/zh/design.html)，部署安全清单见 [docs/zh/deploy.html](docs/zh/deploy.html)。核心不变量：用户内容**永不**以 `text/html` 返回（完整模式除外，强制 CSP sandbox 且不含 `allow-same-origin`）；token 只走 `Authorization` 头；审计日志在 `~/.local/state/conv-docs/audit.log`。报告安全问题见 [SECURITY.zh-CN.md](SECURITY.zh-CN.md)。

## 第三方组件

| 组件 | 版本 | License | 用途 |
|------|------|---------|------|
| [marked](https://github.com/markedjs/marked) | 18.0.14 | MIT | Markdown 解析 |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.16 | Apache-2.0 | HTML/XSS 清洗 |
| [highlight.js](https://github.com/highlightjs/highlight.js) | 11.12.0 | BSD-3-Clause | 语法高亮 |

各组件保留各自许可证，原文在 `src/conv_docs/web/vendor/LICENSE.*`；完整说明见 [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md)。

## License

MIT —— 见 [LICENSE](LICENSE)。logo（`assets/logo.svg`）为原创美术作品，同为 MIT 条款，不涉及任何第三方知识产权。
