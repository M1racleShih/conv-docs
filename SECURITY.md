# Security Policy

## 模型摘要

conv-doc 是单用户、token 认证、纯只读的文档网关。核心保证：

- 只有显式 `publish` 的目录可被读取；隐藏文件、扩展名白名单之外的文件、逃逸符号链接一律拒绝。
- 服务端对用户内容永不返回 `text/html`；HTML 完整模式经一次性 ticket 进入 CSP sandbox（无 `allow-same-origin`）的不透明源。
- token 以 SHA-256 哈希存储于 0600 配置文件，仅经 `Authorization: Bearer` 头传输；认证失败按来源限速。
- 无任何写入端点；写入类方法（含 WebDAV 动词）返回 405。

威胁模型、残余风险与逐条对策见 [docs/design.html](docs/design.html)；部署安全清单见 [docs/deploy.html](docs/deploy.html)。

## 支持版本

当前主分支接收安全修复；项目处于 0.x，接口可能变动。

## 报告问题

请通过 GitHub Issues（可私密报告）或仓库联系方式提交，包含：影响范围、复现步骤、利用场景。请勿公开披露未修复的漏洞。

## 运营建议

- token 泄漏或设备丢失时立即 `python3 -m conv_doc token rotate`。
- 服务仅绑定 `127.0.0.1` 并经 Cloudflare Tunnel 暴露；不要直接暴露公网端口。
- 发布目录前自行确认内容；不确定时使用 `--docs-only`。
- 可在 Cloudflare Zero Trust 上为 `docs.*` 增加 Access 策略作为第二层防护。
