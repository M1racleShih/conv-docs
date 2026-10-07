# conv-docs 部署施工图（Runbook）—— 从裸机到手机可读（0 → 1）

> **交叉引用**（`§` 章节号中英一致）：
> 验收 gate = [deploy-gates.md](deploy-gates.md)（G0–G5，唯一定义）·
> English = [deploy-runbook.en.md](deploy-runbook.en.md) ·
> Agent 执行协议 = `skills/conv-docs-deploy/SKILL.md` ·
> 参考手册 = [zh/deploy.html](zh/deploy.html)

**图例**：🔒 = 仅人工执行（凭据 / 账号 / 手机）· ⚠️ = 会改变状态，执行前确认 · `[Gn.m]` = deploy-gates.md 中的 gate 检查项

---

## §0 如何使用本 runbook

每个阶段固定结构：**前置条件 → 步骤 → gate → 失败处理 → 回滚**。gate 不过，不进下一阶段。执行者可以是人或 agent；标注 🔒 的步骤必须由人完成或确认。

### 铁律（红线，任何情况不得违反）

| # | 规则 |
|---|---|
| R1 | **绝不破坏正在运行的服务。** 若 `conv-docs` 或 `cloudflared` 已在运行，视为生产：不重启、不重跑 `install-service.sh`（它会重启 conv-docs）、不 `token rotate`（手机端会立刻失效）——除非人明确要求。 |
| R2 | **共享隧道只做增量修改。** 若 `~/.cloudflared/config.yml` 上还跑着别的服务（如 herdr-remote relay），改前先备份（`cp config.yml config.yml.bak.$(date +%s)`），ingress 只在 catch-all **之前**追加规则，任何重载前先 `cloudflared tunnel ingress validate`。 |
| R3 | **秘密不经过 agent。** `token.txt`、`cert.pem`、`*.json` 凭据：永不 `cat`、永不粘贴进文档/提交/日志。token 只由人交到手机。 |
| R4 | **不开放公网端口。** conv-docs 只绑 `127.0.0.1`，只经隧道暴露；永不 `--host 0.0.0.0`。 |
| R5 | **不写新脚本、不做 Docker。** 本 runbook 按原文执行，不要"顺手"脚本化。（项目决策；Docker 明确不在范围内。） |

### 停止条件（agent 必须停下问人）

Cloudflare 登录授权（H2）· 任何 DNS 变更（H3）· 任何付费操作（H1）· token 处理（H3/H4）· 重启共享的 `cloudflared` · 同一检查连续失败 3 次。

---

## §1 范围与定义

- **覆盖**：Linux（以 Debian/Ubuntu 系命令为例，其他发行版等价替换）· macOS · WSL2。仅原生方案——Docker 经决策明确排除。
- **"裸机"** = OS 已装好、有 sudo/root、网络可达。其余（git、Python、uv、Node、cloudflared）由本 runbook 安装。
- **不覆盖**：买域名（人工，H1）、装操作系统、原生手机 App（查看器是 Web/PWA）。
- **完成定义（DoD）**：G0–G3 全绿 + 手机上 [deploy-gates.md](deploy-gates.md) 的 G4.1–G4.8 全过。G4.9 可选。

---

## §2 Phase 0 —— 环境盘点与决策树

**前置**：目标机 shell 可达。

### 2.1 只读盘点

```sh
uname -s; grep -qi microsoft /proc/version && echo WSL
python3 --version; git --version
uv --version 2>/dev/null; node --version 2>/dev/null; npm --version 2>/dev/null
cloudflared --version 2>/dev/null
command -v systemctl && systemctl --user is-active conv-docs 2>/dev/null; systemctl is-active cloudflared 2>/dev/null
ls ~/.cloudflared/ 2>/dev/null        # 记录 cert.pem / config.yml / *.json 是否存在——不看内容
ls ~/.config/conv-docs/ 2>/dev/null   # 记录 config.json / token.txt 是否存在——不看内容
curl -sI --max-time 5 https://region1.v2.argotunnel.com >/dev/null && echo net-ok   # 隧道出网预检
```

### 2.2 决策树

| # | 问题 | 是 | 否 |
|---|---|---|---|
| D1 | `conv-docs` 已在运行**且**已配置？ | → 2.3 接管路径 | → Phase 1（build） |
| D2 | 已装 `cloudflared`？ | 跳过安装 | → A2 安装后继续 |
| D3 | `~/.cloudflared/config.yml` 里已有命名隧道？ | → **分支 A**（§5.B，复用） | → **分支 B**（§5.C，从零建） |
| D4 | 想先零账号冒烟一次？ | → 先走**分支 C**（§5.A）再走 A/B | 跳过 |
| D5 | 有 `systemctl`？ | conv-docs：`install-service.sh`；cloudflared：`service install` | 前台运行 + A3 表 |
| D6 | 无头机器（无浏览器）？ | `cloudflared login` 用附录 D1 流程 | 正常流程 |

### 2.3 接管既有部署（红线路径）

若 D1 = 是（例如本机已在生产服务 conv-docs）：

1. **不要**重跑 `install-service.sh`（会重启服务）、**不要**轮换 token、**不要**重复 publish。
2. 只读记录现状：`uv run conv-docs list`、G2.1、G2.4、`systemctl --user status conv-docs`。
3. 只执行 **gate 校验**（G2、G3-N 如适用）。任何变更须经人明确批准。

**gate** `[G0.1–G0.11]` · **失败处理**：缺工具 → 按 A1/A2 安装后重测。 · **回滚**：无（只读）。

---

## §3 Phase 1 —— Build

**前置**：已定 clone 位置；安装包可下载。

```sh
git clone <repo-url> conv-docs && cd conv-docs
uv sync                      # 没有 uv？→ python3 -m venv .venv && .venv/bin/pip install -e . --group dev
uv run pytest                # 或：.venv/bin/python -m pytest
uv run conv-docs --version
```

可选：重建 TypeScript 查看器（需 Node 18+）——**线上服务所在的 checkout 勿动**，除非你就是要换线上查看器（见 G1b 警告）：

```sh
npm install && npm run build && git status --porcelain src/conv_docs/web/app.js   # 期望输出为空
```

**gate** `[G1.1–G1.3]`，可选 `[G1b.1–G1b.2]` · **失败处理**：测试失败先修好再走；网络错误换源重试。 · **回滚**：`git checkout .` 还原构建产物。

---

## §4 Phase 2 —— 本机部署

**前置**：Phase 1 全绿。既有部署 → 走 §2.3。

```sh
# 1. 访问 token（明文只打印一次；同时写入 ~/.config/conv-docs/token.txt，0600）
uv run conv-docs token rotate                # ⚠️ 仅首次安装——线上机勿动

# 2. 发布一个样例 workspace（不做这步默认零暴露）
mkdir -p ~/conv-docs-demo && printf '# Hello conv-docs\n' > ~/conv-docs-demo/hello.md
uv run conv-docs publish ~/conv-docs-demo --as demo --docs-only
uv run conv-docs list

# 3a. 常驻（systemd 用户服务）—— Linux/WSL：
bash scripts/install-service.sh              # ⚠️ 幂等但每次重跑都会重启 conv-docs
# 3b. 前台（macOS 或无 systemd）：
uv run conv-docs serve                       # 127.0.0.1:8380；常驻方式见 A3
```

**gate** `[G2.1–G2.7]` · **失败处理**：`journalctl --user -u conv-docs -n 50`（或前台控制台）；带 token 仍 401 → token 不匹配，查 `CONV_DOCS_CONFIG`。 · **回滚**：`uv run conv-docs unpublish demo`；停服（`systemctl --user stop conv-docs`）。

---

## §5 Phase 3 —— Cloudflare 隧道打通

**前置**：G2 全绿。分支在 D3/D4 决定。已装 `cloudflared`（A2）。

### §5.A 分支 C —— Quick Tunnel 冒烟（零账号，约 2 分钟）

目的：在动 DNS 之前，先把"应用问题"与"隧道问题"分开。

```sh
cloudflared tunnel --url http://127.0.0.1:8380
# → 记下 https://<random>.trycloudflare.com 输出的 URL（可选：--allowed-mail you@example.com 加邮箱门禁）
```

手机打开该 URL 应能访问。**天生临时**——域名每次重启都变、无 SLA。用完 Ctrl-C 结束进程。

**gate** `[G3-Q.1–G3-Q.2]` · **失败处理**：没打印 URL → 查出网（`[G0.11]`）。

### §5.B 分支 A —— 复用已有隧道（如 herdr-remote 在用的那个）

隧道是共享的：**只做增量**（R2）。先备份：

```sh
cp ~/.cloudflared/config.yml ~/.cloudflared/config.yml.bak.$(date +%s)
```

在最后的 catch-all **之前**新增一条 ingress；已有规则一字不动：

```yaml
ingress:
  - hostname: relay.你的域名          # 已有规则——原样保留
    service: http://127.0.0.1:8375
  - hostname: docs.example.com        # ← 新增：conv-docs
    service: http://127.0.0.1:8380
  - service: http_status:404          # catch-all 必须在最后
```

```sh
cloudflared tunnel ingress validate                 # 任何重载前必须显示 Valid
cloudflared tunnel route dns <隧道名> docs.example.com    # ⚠️🔒 公网 DNS 变更——须经人确认
systemctl restart cloudflared                       # ⚠️ 共享服务，relay 会瞬断。macOS 见 A3
```

**gate** `[G3-N.1–G3-N.7]`（G3-N.6 是 relay 不回归检查） · **失败处理**：502/530 → 附录 B；relay 回归 → 立即还原备份并重载。

### §5.C 分支 B —— 从零创建命名隧道

**人工交接 H1** 🔒：Cloudflare 账号 + 一个 DNS 托管在 Cloudflare 的域名
（[添加站点](https://developers.cloudflare.com/fundamentals/manage-domains/add-site/) → [改 nameservers](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)）。免费计划即可。还没有域名？先用分支 C 顶着。

```sh
# 1. 授权登录 —— 🔒 H2：会开浏览器（无头机器：附录 D1），选择域名区域；写入 ~/.cloudflared/cert.pem
cloudflared tunnel login

# 2. 创建隧道
cloudflared tunnel create docs
cloudflared tunnel list                      # 记下 UUID

# 3. 配置 —— ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<'EOF'
tunnel: <Tunnel-UUID>
credentials-file: /home/<USER>/.cloudflared/<Tunnel-UUID>.json
ingress:
  - hostname: docs.example.com
    service: http://127.0.0.1:8380
  - service: http_status:404
EOF
cloudflared tunnel ingress validate

# 4. 路由 DNS —— ⚠️🔒 H3：会创建公网 CNAME <UUID>.cfargotunnel.com
cloudflared tunnel route dns docs docs.example.com

# 5. 先前台跑一次看干净日志，确认后装服务
cloudflared tunnel run docs
# → 换个网络验证 G3-N.4，Ctrl-C 结束，然后：
cloudflared service install                  # Linux：需 sudo + 显式 config 路径 → A3；macOS → A3
```

**gate** `[G3-N.1–G3-N.7]` · **失败处理**：登录没开浏览器 → D1；DNS 不解析 → H3 前提（域名需在 Cloudflare nameservers）；502 → 附录 B。 · **回滚**：附录 C。

---

## §6 Phase 4 —— 手机端验收（DoD）🔒

手机浏览器（蜂窝网络**和** Wi-Fi 各过一遍）：逐项完成 [deploy-gates.md](deploy-gates.md) 的 `[G4.1–G4.9]`。

说明：HTML 完整模式是 30 秒一次性 ticket——过期重取属正常。代码/数据文件默认 404（需 `--allow-code` 放行；HTML 引用的伴生样式表 `.css` 除外）。被 `--exclude` 的路径直访也是 404。

**gate** `[G4]` = DoD · **失败处理**：按附录 B 的症状表定位。

---

## §7 Phase 5 —— 安全 gate 与移交

1. 过一遍 `[G5.1–G5.6]`。
2. 可选加固：Cloudflare Zero Trust 给 `docs.example.com` 配 Access 策略（邮箱 OTP）——token 仍是应用层凭证。🔒
3. 填写移交记录（勿入公开仓库）：

```
conv-docs 部署记录
- 主机 / OS：                ______________________
- 仓库目录 / 版本：           ______________________
- 服务单元：                 conv-docs.service（systemd 用户级）/ launchd / 前台
- 端口：                     127.0.0.1:8380
- 隧道名 / UUID：            ______________________
- 公网 hostname：            ______________________
- cloudflared 服务：         systemd 单元 / launchd / 前台（config 路径：__________）
- 配置 / 状态路径：           ~/.config/conv-docs/  ·  ~/.local/state/conv-docs/audit.log
- token：                    手机 + ~/.config/conv-docs/token.txt（0600）——不记录内容
- gate 通过：                G0 __ G1 __ G2 __ G3 __ G4 __ G5 __   日期：______
```

---

## 附录 A —— 平台差异表

### A1 基础依赖

| | Linux（Debian/Ubuntu） | macOS | WSL2 |
|---|---|---|---|
| git | `sudo apt-get install git` | 系统自带 / `brew install git` | 同 Linux |
| Python 3.10+ | `sudo apt-get install python3 python3-venv` | 自带 / `brew install python` | 同 Linux |
| uv（推荐） | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | 同左 | 同 Linux |
| Node 18+（可选） | `sudo apt-get install nodejs npm` | `brew install node` | 同 Linux |

### A2 cloudflared 安装

| 平台 | 命令 |
|---|---|
| Debian/Ubuntu | `sudo mkdir -p --mode=0755 /usr/share/keyrings` · `curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \| sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null` · `echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \| sudo tee /etc/apt/sources.list.d/cloudflared.list` · `sudo apt-get update && sudo apt-get install cloudflared` |
| RHEL/Fedora | `curl -fsSl https://pkg.cloudflare.com/cloudflared.repo \| sudo tee /etc/yum.repos.d/cloudflared.repo` · `sudo yum install cloudflared` |
| macOS | `brew install cloudflared` |
| 任意 | [官方下载页](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) 的二进制 |

> 注：Cloudflare 于 **2025-10-30** 轮换了包签名密钥；老环境安装报 key 错误时按上表重装 keyring。

### A3 开机自启

| 组件 | Linux | macOS | WSL2 |
|---|---|---|---|
| conv-docs | `bash scripts/install-service.sh` → systemd **用户**单元（`~/.config/systemd/user/conv-docs.service`）。管理：`systemctl --user {status,restart,stop} conv-docs` · 日志：`journalctl --user -u conv-docs -f` | 无 systemd：前台运行（`uv run conv-docs serve`），或写 LaunchAgent（`ProgramArguments=[python,-m,conv_docs,serve]`，`RunAtLoad`/`KeepAlive`） | `/etc/wsl.conf` 有 `[boot] systemd=true` 则同 Linux；否则前台 / Windows 任务计划调 `wsl -e` |
| cloudflared | `sudo cloudflared --config /home/<USER>/.cloudflared/config.yml service install`（**sudo 下 `$HOME=/root`，必须显式 `--config`**）· 然后 `systemctl enable --now cloudflared` | 登录启动（用户 agent）：`cloudflared service install` · 开机启动（daemon，用 `/etc/cloudflared`）：`sudo cloudflared service install` · 手动：`sudo launchctl start com.cloudflare.cloudflared` · 日志：`/Library/Logs/com.cloudflare.cloudflared.{err,out}.log` | 同 Linux |

---

## 附录 B —— 故障排查决策树

| 现象 | 探测 | 修复 |
|---|---|---|
| 手机 401 | token 是否完整？此后是否轮换过？ | 重新粘贴；`token rotate` 会使旧 token 失效——15 分钟内失败 10 次封 15 分钟（429），等待或换网络 |
| 手机 404（文件） | `uv run conv-docs list`；文件是否隐藏 / 不在白名单 / 被 exclude？ | 用正确参数重新发布；被排除路径 404 属设计 |
| 隧道 502/530 | 本地 G2.1？`cloudflared tunnel ingress validate`；docs 规则在 catch-all 之前？ | 修顺序；`journalctl --user -u conv-docs`；`systemctl status cloudflared` |
| relay（herdr-remote）改后挂了 | `diff config.yml config.yml.bak.*` | 还原备份 → validate → 重载（R2） |
| DNS 不解析 | `dig +short docs.example.com CNAME` | 域名是否已切 Cloudflare nameservers？重跑 `route dns`（H3） |
| HTML 完整模式空白 | ticket 只有 30 秒且一次性 | 重新点「完整模式」；脚本被沙箱约束属预期 |
| 页面样式丢失 | CSP 拦截外站 `<link>` | 属预期；伴生 `.css` 已自动放行（仅被 HTML 引用时，未引用的仍 404） |
| Quick Tunnel 失效 | 进程还在吗？ | URL 随进程终止、每次重启换域名——天生如此 |
| cloudflared 连不上 | `[G0.11]` 出网 7844 | 企业网络封端口 → D2 |
| 服务起不来 | `journalctl --user -u conv-docs -n 50`；端口冲突 `ss -ltnp \| grep 8380` | 修配置路径 / 释放端口 |

---

## 附录 C —— 回滚 / 下线（逐级）

| 级别 | 操作 | 效果 |
|---|---|---|
| C1 停止暴露内容 | `uv run conv-docs unpublish <name>`（全部条目） | 即时生效；服务照常 |
| C2 停服务 | `systemctl --user disable --now conv-docs`（macOS：结束前台/launchd） | 隧道处 502 |
| C3 摘除隧道规则 | 还原 `config.yml` 备份（R2）→ `cloudflared tunnel ingress validate` → `systemctl restart cloudflared` ⚠️ | hostname 404/502；**备份正确则 relay 不受影响** |
| C4 删 DNS | 在 Cloudflare 面板删除 `docs.example.com` 的 CNAME（H3） | 公网域名失效 |
| C5 删隧道 | `cloudflared tunnel delete docs`（先做 C4；删 `<UUID>.json`） | 隧道销毁 |
| C6 切断访问 | `uv run conv-docs token rotate` 🔒⚠️ | 所有手机立即掉线 |

---

## 附录 D —— 无头登录与网络预检

**D1 无浏览器的 `cloudflared tunnel login`**：命令会打印一个 URL 而非打开浏览器。在任意机器打开该 URL、登录、选择域名区域——`cert.pem` 会写在**无头机器**上。验证：`ls ~/.cloudflared/cert.pem`（不要读内容）。

**D2 出网预检**：cloudflared 向 Cloudflare 发起 **TCP 7844** 出站连接。G0.11 失败且在企业网络内 → 请 IT 放行 `*.argotunnel.com:7844` 出站（参见[连通性预检](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/troubleshoot-tunnels/connectivity-prechecks/)）。

---

*runbook 结束。gate 定义在 [deploy-gates.md](deploy-gates.md)；agent 协议在 `skills/conv-docs-deploy/SKILL.md`。*
