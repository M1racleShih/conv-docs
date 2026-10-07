# Deployment Acceptance Gates · 部署验收 Gate 清单

> **单一事实来源（SSOT）**：本清单是 G0–G5 验收 gate 的唯一定义。
> Runbook（[zh](deploy-runbook.zh.md) / [en](deploy-runbook.en.md)）与 agent skill（`skills/conv-docs-deploy/SKILL.md`）只引用，不复制。
> This file is the single definition of gates G0–G5. Runbooks and the deploy skill reference it.

**规则 / Rules**

1. 所有探测命令均为**只读**；gate 未通过不得进入下一阶段。All probes are read-only; a failing gate blocks progress.
2. 命令中的 `docs.example.com`、`<tunnel>`、`8380` 等占位符按实际值替换。Replace placeholders.
3. `uv run conv-docs` ≡ `python3 -m conv_docs`；无 uv 时用 `python3`（venv 内先 `source .venv/bin/activate`）。

**标记 / Legend**

| 标记 | 含义 / Meaning |
|---|---|
| 🔒 | 需人工执行或人工提供（涉及 token / 凭据 / 账号 / 手机）。Agent 不得代读秘密。 |
| ⚠️ | 会改变状态，执行前须确认（尤其：重启共享服务、轮换 token）。 |
| G1b | 可选 gate，跳过不阻塞部署。Optional, non-blocking. |

---

## G0 — 环境盘点 / Environment survey（P0 后）

| # | 检查 / Check | 命令 / Command | 期望 / Expected | 失败处理 / On fail |
|---|---|---|---|---|
| G0.1 | 平台 | `uname -s`；`grep -qi microsoft /proc/version && echo WSL` | `Linux` 或 `Darwin`；WSL 时标出 | 非 Linux/Darwin 不在本 runbook 范围 |
| G0.2 | Python ≥ 3.10 | `python3 --version` | `Python 3.10+` | → P1 安装步骤（附录 A1） |
| G0.3 | 版本管理 | `uv --version`（可选） | 有则用 uv；无则 venv 回退 | 仅影响命令前缀，不阻塞 |
| G0.4 | Node.js（可选，仅重建 viewer / 冒烟） | `node --version && npm --version` | Node 18+ | 跳过 G1b |
| G0.5 | git | `git --version` | 任意近期版本 | → 附录 A1 |
| G0.6 | cloudflared | `cloudflared --version` | 输出版本号 | → P3 前先按附录 A2 安装 |
| G0.7 | 自启机制 | `command -v systemctl`（Linux）；macOS 记录用 launchd | 标注走哪张自启表 | 无 systemd → 附录 A3 前台运行 |
| G0.8 | 既有 cloudflared 状态 | `ls ~/.cloudflared/`（**不看内容**） | 记录：`cert.pem` / `config.yml` / `*.json` 存在与否 | 决定 P3 走分支 A 或 B |
| G0.9 | 既有 conv-docs 配置 | `ls ~/.config/conv-docs/`（**不看内容**） | 记录 `config.json` / `token.txt` 是否存在 | 存在 → 走「接管既有部署」路径（runbook P0） |
| G0.10 | 既有服务状态 | `systemctl --user is-active conv-docs 2>/dev/null; systemctl is-active cloudflared 2>/dev/null` | 记录 active / inactive | **active → 红线生效**：禁止随意重启（见 G2.6 / G3.6） |
| G0.11 | 出网 7844（隧道前置） | `curl -sI --max-time 5 https://region1.v2.argotunnel.com >/dev/null && echo net-ok` | `net-ok` | 企业网络可能封 7844 → 附录 D2 |

---

## G1 — Build 验收 / Build（P1 后）

| # | 检查 / Check | 命令 / Command | 期望 / Expected | 失败处理 / On fail |
|---|---|---|---|---|
| G1.1 | 依赖就绪 | `uv sync`（或 `python3 -m venv .venv`） | 退出码 0 | 看报错：网络/镜像 → 换源重试 |
| G1.2 | 单测全绿 | `uv run pytest`（或 `.venv/bin/python -m pytest`） | `0 failed`（当前 77 项） | 逐条看失败；禁止带失败进入 P2 |
| G1.3 | CLI 可用 | `uv run conv-docs --version` | 输出 `conv-docs x.y.z` | 检查是否在仓库根目录 |
| G1b.1 | viewer 产物与源码一致 | `npm install && npm run build && git status --porcelain src/conv_docs/web/app.js` | 输出为空（产物已提交且一致） | 有 diff → 提交或还原；⚠️ 有线上服务时慎用（见 G1b 警告） |
| G1b.2 | 无头浏览器冒烟（18 断言） | `TOKEN=<token> node scripts/browser-smoke.mjs` 🔒 | 全部断言通过 | 需本机 Chrome + 运行中的服务 + `ROOT` 以 `--allow-code` 发布；失败不影响部署判定 |

> ⚠️ **G1b 警告**：`npm run build` 会重写 `src/conv_docs/web/app.js`。若该 checkout 正被线上服务使用，重建即改变线上查看器——先 `git status` 确认干净，重建后立即核对 G1b.1。
> `npm run build` rewrites the served viewer artifact. On a live checkout, verify G1b.1 immediately after.

---

## G2 — 本机服务验收 / Local service（P2 后）

| # | 检查 / Check | 命令 / Command | 期望 / Expected | 失败处理 / On fail |
|---|---|---|---|---|
| G2.1 | 健康检查 | `curl -fsS http://127.0.0.1:8380/api/v1/health` | `{"ok": true, "service": "conv-docs", "version": ...}` | 服务未起 → `journalctl --user -u conv-docs -n 50` |
| G2.2 | 无 token 必 401 | `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8380/api/v1/roots` | `401` | 返回 200 = 认证失效，**停止部署**排查 `security.py` |
| G2.3 | 带 token 可读 | `curl -fsS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8380/api/v1/roots` 🔒 | JSON 根列表（空列表也正常） | `401` → token 未设置/已轮换；`429` → 触发限速（10 次/15 分钟封 15 分钟） |
| G2.4 | 只绑环回 | Linux: `ss -ltnp \| grep 8380`；macOS: `lsof -nP -iTCP:8380 -sTCP:LISTEN` | `127.0.0.1:8380`（**无** `0.0.0.0`/`*:8380`） | 出现公网绑定 → 立即停服修正（安全红线） |
| G2.5 | 秘密文件权限 | Linux: `stat -c '%a %n' ~/.config/conv-docs/config.json ~/.config/conv-docs/token.txt`；macOS: `stat -f '%Lp %N' ...` | 均为 `600` | `chmod 600 <file>` 后复查 |
| G2.6 | 服务常驻（仅 systemd 安装后） | `systemctl --user is-active conv-docs` | `active` | ⚠️ 已有线上服务时**不要**重跑 `install-service.sh`（会重启服务），改查 `status` |
| G2.7 | 发布清单可见 | `uv run conv-docs list` | 列出刚发布的条目 | 名字拼写/配置路径（`CONV_DOCS_CONFIG`） |

---

## G3 — 隧道验收 / Tunnel（P3 后）

### G3-Q：Quick Tunnel 分支（分支 C）

| # | 检查 / Check | 命令 / Command | 期望 / Expected | 失败处理 / On fail |
|---|---|---|---|---|
| G3-Q.1 | URL 已生成 | 看 `cloudflared tunnel --url ...` 输出 | 含 `https://*.trycloudflare.com` | 看进程报错；确认 G0.11 出网 |
| G3-Q.2 | 公网健康 | `curl -fsS https://<random>.trycloudflare.com/api/v1/health` | `{"ok": true, ...}` | 本地 G2.1 复核；分流应用/隧道问题 |

### G3-N：命名隧道分支（分支 A / B）

| # | 检查 / Check | 命令 / Command | 期望 / Expected | 失败处理 / On fail |
|---|---|---|---|---|
| G3-N.1 | ingress 合法 | `cloudflared tunnel ingress validate` | `Valid` | 按报错修 config.yml；docs 规则须在 catch-all **之前** |
| G3-N.2 | DNS 已路由 | `dig +short docs.example.com CNAME`（或 `nslookup docs.example.com`） | `<UUID>.cfargotunnel.com` | `cloudflared tunnel route dns <tunnel> docs.example.com` 🔒 |
| G3-N.3 | 隧道有连接 | `cloudflared tunnel info <tunnel>` | CONNECTING/CONNECTED ≥ 1 | `systemctl status cloudflared`（或附录 A3 对应项） |
| G3-N.4 | 公网健康（TLS 有效，不带 `-k`） | `curl -fsS https://docs.example.com/api/v1/health` | `{"ok": true, ...}` | 502/530 → 附录 B「隧道 502/530」 |
| G3-N.5 | 公网无 token 必 401 | `curl -s -o /dev/null -w '%{http_code}\n' https://docs.example.com/api/v1/roots` | `401` | 返回 200 → 该 URL 后面不是 conv-docs，停止排查 |
| G3-N.6 | 共享隧道不回归 | `cloudflared tunnel ingress validate` + 人工确认 relay 规则原样 | relay hostname 仍指向原端口；catch-all 仍在最后 | 立即恢复 config.yml 备份并重载（**动共享 config 前先备份**） |
| G3-N.7 | 手机网络可达 🔒 | 手机关 Wi-Fi 用蜂窝访问 G3-N.4 同一 URL | 同 G3-N.4 | 仅 Wi-Fi 不通 → 本地网络/DNS 问题，非部署问题 |

---

## G4 — 手机端验收 / Phone acceptance = DoD（P4 后）🔒

在手机浏览器逐项打勾（建议蜂窝网络 + 一次 Wi-Fi 各过一遍）：

| # | 检查 / Check | 操作 / Action | 期望 / Expected |
|---|---|---|---|
| G4.1 | 登录 | 打开 `https://docs.example.com`，粘贴 token | 进入工作区列表；token 只存浏览器本地 |
| G4.2 | 浏览 | 点进发布目录 → 点开一个 `.md` | Markdown 渲染、代码高亮正常 |
| G4.3 | HTML 安全渲染 | 打开 HTML 文件 | 正常显示；脚本/事件被剥离（预期行为） |
| G4.4 | 完整模式沙箱 | 切「完整模式」 | 30 秒一次性 ticket 内加载；交互可用；沙箱隔离（无 same-origin） |
| G4.5 | exclude 强制 | 直访被 `--exclude` 的文件 URL | 404（列表同样不可见） |
| G4.6 | 代码过滤 | 直访 `.py`/`.json` 等 | 404（未 `--allow-code` 时） |
| G4.7 | 预览时效 | `preview` 一个文件（`--ttl 5m`）后等待 | 到期自动消失 |
| G4.8 | 读-only | 尝试 POST 任意 API | 405 |
| G4.9 | PWA 体验 | 「添加到主屏幕」 | 图标/启动正常，可当 App 用 |

**DoD 判定**：G0–G3 全绿 + G4.1–G4.8 全过 = 部署完成。G4.9 可选。

---

## G5 — 安全 gate 与移交 / Security & handover（P5 后）

| # | 检查 / Check | 命令 / Command | 期望 / Expected |
|---|---|---|---|
| G5.1 | 服务面最小化 | 复核 G2.4；`curl -s -o /dev/null -w '%{http_code}\n' http://<LAN-IP>:8380/` | 环回监听；LAN 直连应拒绝/不通 |
| G5.2 | 秘密落盘合规 | 复核 G2.5；`grep -RIl "$(cat ~/.config/conv-docs/token.txt 2>/dev/null)" . 2>/dev/null \| head` 🔒 | 第二条输出为空（token 未泄入仓库） |
| G5.3 | 审计日志 | `tail -n 20 ~/.local/state/conv-docs/audit.log` | JSONL：认证失败、发布变更、文件访问 |
| G5.4 | 轮换演练（可选） | ⚠️ `uv run conv-docs token rotate` 🔒 | 新 token 只显示一次；旧手机立即失效；`token.txt` 已更新（0600） |
| G5.5 | 二层防护（可选） | Cloudflare Zero Trust → Access → `docs.example.com` | 邮箱 OTP 等策略生效（token 仍为应用层凭证） |
| G5.6 | 移交清单 | 见 runbook P5「移交记录」模板 | 隧道名/UUID/hostname/服务单元/config 路径齐全，**不含**任何秘密 |

---

## 限速与已知行为 / Rate limits & known behavior（排障参考）

- 认证失败 **10 次 / 15 分钟** → 封禁 **15 分钟**（429）。换网络或等待。
- 完整模式 ticket：**30 秒一次性**；过期重取属正常。
- Quick Tunnel：域名人次一换、无 SLA、并发 200 上限、不支持 SSE——仅冒烟用。
- `install-service.sh` **幂等但会重启 conv-docs 服务**（重跑即重启）；线上接管时勿重跑。
