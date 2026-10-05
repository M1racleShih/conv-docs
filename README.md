# conv-doc

只读文档网关：把 PC 上**显式发布**的 workspace 目录，通过 Cloudflare Tunnel 以 token 认证的方式送到手机端渲染阅读。Markdown / HTML 渲染，纯只读，与 [herdr-remote](https://github.com/dcolinmorgan/herdr-remote) 的 agent 控制通道完全隔离。

方案调研、设计与部署手册（HTML）：

- [调研报告](docs/index.html) — 需求、候选方案对比（含 star / 活跃度证据）、选型结论
- [方案设计](docs/design.html) — 架构、API、渲染管线、威胁模型
- [部署与使用](docs/deploy.html) — 安装、systemd、Cloudflare Tunnel、手机端、运维与排查
- [安全评审报告](docs/security-review.html) — STRIDE 逐面评审：发现、处置与残余风险

## 特性

- **显式发布才可见**：默认零暴露；`publish` / `unpublish` 按目录授权，即时生效
- **纯只读**：服务端只有 GET/HEAD，WebDAV 类写入动词一律 405
- **token 认证**：Bearer token，服务端只存 SHA-256 哈希（配置 0600），支持一键轮换；认证失败按来源限速
- **Markdown / HTML 渲染**：marked + DOMPurify + highlight.js（仓库内置），HTML 另有脚本沙箱「完整模式」
- **路径沙箱**：realpath 包含性检查、符号链接逃逸拒绝、隐藏文件跳过、扩展名白名单
- **零第三方运行时依赖**：Python 3.10+ 标准库实现

## 快速开始

```bash
python3 -m conv_doc token rotate                    # 生成 token（明文只显示一次）
python3 -m conv_doc publish ~/work/proj-a --as proj-a
python3 -m conv_doc serve                           # 127.0.0.1:8380
```

常驻运行：`bash scripts/install-service.sh`（systemd 用户服务 + cloudflared ingress 配置片段）。

## 命令

| 命令 | 作用 |
|------|------|
| `publish <dir> [--as NAME] [--docs-only]` | 显式发布目录（`--docs-only` 只放行文档与图片） |
| `unpublish <name>` | 撤销发布 |
| `list` | 查看发布清单 |
| `token rotate` | 生成新 token 并使旧的失效 |
| `serve [--host H] [--port P]` | 启动只读服务（默认 127.0.0.1:8380） |

## 开发与验证

```bash
python3 -m unittest discover -s tests        # 49 项：认证、只读、路径沙箱、ticket、响应头
TOKEN=<token> node scripts/browser-smoke.mjs # 无头 Chrome 端到端：登录→浏览→渲染→沙箱
```

目录结构：

```
conv_doc/          服务端（store 配置 / security 安全原语 / server HTTP）+ web/ 移动端查看器
conv_doc/web/vendor/  渲染栈（marked 18.0.14 · DOMPurify 3.4.16 · highlight.js 11.12.0，含各自 LICENSE）
tests/            标准库 unittest 测试
scripts/          install-service.sh · fetch-vendor.sh · browser-smoke.mjs
docs/             HTML 文档（调研 / 设计 / 部署）
```

## 安全

威胁模型与残余风险见 [方案设计](docs/design.html)，部署安全清单见 [部署手册](docs/deploy.html)。要点：用户内容永不以 `text/html` 返回（完整模式除外且强制 CSP sandbox 无 `allow-same-origin`）；token 只走 Authorization 头；审计日志 `~/.local/state/conv-doc/audit.log`。报告安全问题见 [SECURITY.md](SECURITY.md)。

## 第三方组件

| 组件 | 版本 | License | 用途 |
|------|------|---------|------|
| [marked](https://github.com/markedjs/marked) | 18.0.14 | MIT | Markdown 解析 |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.16 | Apache-2.0 | HTML/XSS 清洗 |
| [highlight.js](https://github.com/highlightjs/highlight.js) | 11.12.0 | BSD-3-Clause | 代码高亮 |

各组件许可证原文在 `conv_doc/web/vendor/LICENSE.*`。

## License

MIT
