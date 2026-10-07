# conv-docs Deployment Runbook — bare machine → phone (0 → 1)

> **Cross-refs** (section numbers `§` are identical in zh/en):
> Acceptance gates = [deploy-gates.md](deploy-gates.md) (G0–G5, SSOT) ·
> 中文版 = [deploy-runbook.zh.md](deploy-runbook.zh.md) ·
> Agent execution protocol = `skills/conv-docs-deploy/SKILL.md` ·
> Reference manual = [en/deploy.html](en/deploy.html)

**Legend**: 🔒 = human-only (secrets / accounts / phone) · ⚠️ = state-changing, confirm first · `[Gn.m]` = gate check in deploy-gates.md

---

## §0 How to use this runbook

Each phase has: **Preconditions → Steps → Gate → On failure → Rollback**. A gate that does not pass blocks the next phase. The executor may be a human or an agent; anything marked 🔒 must be done (or confirmed) by the human.

### Iron rules (red lines — never violate)

| # | Rule |
|---|---|
| R1 | **Never break a running service.** If `conv-docs` or `cloudflared` is already active, treat it as production: no restarts, no `install-service.sh` re-runs (it restarts conv-docs), no `token rotate` (invalidates the phone) — unless the human explicitly asks. |
| R2 | **Shared tunnel = additive edits only.** If `~/.cloudflared/config.yml` carries other services (e.g. herdr-remote relay), back it up before any edit (`cp config.yml config.yml.bak.$(date +%s)`), only add ingress rules **above** the catch-all, and run `cloudflared tunnel ingress validate` before any reload. |
| R3 | **Secrets never move through the agent.** `token.txt`, `cert.pem`, `*.json` credentials: never `cat`, never paste into documents/commits/logs. The token goes to the phone only through the human. |
| R4 | **No public bind.** conv-docs stays on `127.0.0.1`; exposure happens only through the tunnel. Never `--host 0.0.0.0`. |
| R5 | **No new scripts, no Docker.** This runbook is executed as written; do not "automate" it into scripts. (Project decision; Docker deliberately out of scope.) |

### Stop conditions (agent must pause and ask the human)

Cloudflare login/authorization (H2) · any DNS change (H3) · any purchase (H1) · token handling (H3/H4) · restarting a shared `cloudflared` · the same check failing 3 times in a row.

---

## §1 Scope & definitions

- **Covered**: Linux (Debian/Ubuntu-family commands; other distros equivalent) · macOS · WSL2. Native only — Docker is out of scope by decision.
- **"Bare machine"** = OS installed, sudo/root available, network reachable. Everything else (git, Python, uv, Node, cloudflared) is installed by this runbook.
- **Not covered**: buying a domain (human, H1), OS installation, native mobile apps (the viewer is a web app / PWA).
- **Definition of Done**: G0–G3 green + G4.1–G4.8 checked on the phone ([deploy-gates.md](deploy-gates.md)). G4.9 optional.

---

## §2 Phase 0 — Environment survey & decision tree

**Preconditions**: shell access to the target machine.

### 2.1 Read-only survey

```sh
uname -s; grep -qi microsoft /proc/version && echo WSL
python3 --version; git --version
uv --version 2>/dev/null; node --version 2>/dev/null; npm --version 2>/dev/null
cloudflared --version 2>/dev/null
command -v systemctl && systemctl --user is-active conv-docs 2>/dev/null; systemctl is-active cloudflared 2>/dev/null
ls ~/.cloudflared/ 2>/dev/null        # note which of cert.pem / config.yml / *.json exist — do NOT read contents
ls ~/.config/conv-docs/ 2>/dev/null   # note config.json / token.txt presence — do NOT read contents
curl -sI --max-time 5 https://region1.v2.argotunnel.com >/dev/null && echo net-ok   # tunnel egress pre-check
```

### 2.2 Decision tree

| # | Question | If yes | If no |
|---|---|---|---|
| D1 | `conv-docs` already active **and** configured? | → 2.3 adopt path | → Phase 1 (build) |
| D2 | `cloudflared` installed? | skip install | → A2 install, then continue |
| D3 | `~/.cloudflared/config.yml` exists with a named tunnel? | → **Branch A** (§5.B, reuse) | → **Branch B** (§5.C, from zero) |
| D4 | Want a zero-account smoke test first? | → **Branch C** (§5.A) before A/B | skip |
| D5 | `systemctl` available? | conv-docs: `install-service.sh`; cloudflared: `service install` | foreground + A3 table |
| D6 | Headless machine (no browser)? | use D1 flow of Appendix D for `cloudflared login` | normal flow |

### 2.3 Adopting an existing deployment (red-line path)

If D1 = yes (e.g. this machine already serves conv-docs in production):

1. Do **not** re-run `install-service.sh` (it restarts the service), do **not** rotate the token, do **not** re-publish anything.
2. Record the current state: `uv run conv-docs list`, G2.1, G2.4, `systemctl --user status conv-docs` (read-only).
3. Continue with the **gates only** (G2, G3-N as applicable). Any change requires explicit human approval.

**Gate** `[G0.1–G0.11]` · **On failure**: missing tool → install per A1/A2, re-run survey. · **Rollback**: none (read-only).

---

## §3 Phase 1 — Build

**Preconditions**: repo clone location decided; network for package installs.

```sh
git clone <repo-url> conv-docs && cd conv-docs
uv sync                      # no uv? → python3 -m venv .venv && .venv/bin/pip install -e . --group dev
uv run pytest                # or: .venv/bin/python -m pytest
uv run conv-docs --version
```

Optional rebuild of the TypeScript viewer (needs Node 18+) — **skip on a live checkout** unless you intend to change the served viewer (see G1b warning):

```sh
npm install && npm run build && git status --porcelain src/conv_docs/web/app.js   # expect empty
```

**Gate** `[G1.1–G1.3]`, optional `[G1b.1–G1b.2]` · **On failure**: fix test failures before continuing; network errors → retry with a mirror. · **Rollback**: `git checkout .` to undo build artifacts.

---

## §4 Phase 2 — Local deployment

**Preconditions**: Phase 1 green. On an existing deployment → §2.3 instead.

```sh
# 1. Access token (plaintext prints ONCE; also saved to ~/.config/conv-docs/token.txt, 0600)
uv run conv-docs token rotate                # ⚠️ first install only — never on a live box

# 2. Publish a sample workspace (nothing is exposed until you do this)
mkdir -p ~/conv-docs-demo && printf '# Hello conv-docs\n' > ~/conv-docs-demo/hello.md
uv run conv-docs publish ~/conv-docs-demo --as demo --docs-only
uv run conv-docs list

# 3a. Persistent (systemd user service) — Linux/WSL:
bash scripts/install-service.sh              # ⚠️ idempotent BUT restarts conv-docs on every run
# 3b. Foreground (macOS or no systemd):
uv run conv-docs serve                       # 127.0.0.1:8380; autostart options → A3
```

**Gate** `[G2.1–G2.7]` · **On failure**: `journalctl --user -u conv-docs -n 50` (or foreground console); 401-with-token → token mismatch, check `CONV_DOCS_CONFIG`. · **Rollback**: `uv run conv-docs unpublish demo`; stop the service (`systemctl --user stop conv-docs`).

---

## §5 Phase 3 — Cloudflare tunnel

**Preconditions**: G2 green. Branch chosen at D3/D4. `cloudflared` installed (A2).

### §5.A Branch C — Quick Tunnel smoke (zero account, ~2 minutes)

Purpose: separate "app problem" from "tunnel problem" before touching DNS.

```sh
cloudflared tunnel --url http://127.0.0.1:8380
# → note the https://<random>.trycloudflare.com URL (optional: --allowed-mail you@example.com for an email gate)
```

Open the URL on the phone: health page should respond. **Temporary by design** — hostname changes on restart, no SLA. Kill the process when done.

**Gate** `[G3-Q.1–G3-Q.2]` · **On failure**: no URL printed → check egress (`[G0.11]`).

### §5.B Branch A — Reuse an existing tunnel (e.g. the herdr-remote one)

The tunnel is shared: **additive edit only** (R2). Backup first:

```sh
cp ~/.cloudflared/config.yml ~/.cloudflared/config.yml.bak.$(date +%s)
```

Add one ingress rule **above** the final catch-all; keep every existing rule untouched:

```yaml
ingress:
  - hostname: relay.你的域名          # existing rule(s) — leave exactly as-is
    service: http://127.0.0.1:8375
  - hostname: docs.example.com        # ← new: conv-docs
    service: http://127.0.0.1:8380
  - service: http_status:404          # catch-all must stay last
```

```sh
cloudflared tunnel ingress validate                 # must say Valid BEFORE any reload
cloudflared tunnel route dns <tunnel-name> docs.example.com    # ⚠️🔒 public DNS change — confirm with human
systemctl restart cloudflared                       # ⚠️ shared service; brief relay downtime. macOS: A3
```

**Gate** `[G3-N.1–G3-N.7]` (G3-N.6 is the no-regression check for the relay) · **On failure**: 502/530 → Appendix B; relay regression → restore the backup and reload immediately.

### §5.C Branch B — Named tunnel from zero

**Human handoff H1** 🔒: a Cloudflare account and a domain whose DNS is on Cloudflare
([add site](https://developers.cloudflare.com/fundamentals/manage-domains/add-site/) → [change nameservers](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)). Free plan is fine. No domain yet? Use Branch C meanwhile.

```sh
# 1. Auth — 🔒 H2: opens a browser (headless: Appendix D1), pick the zone; writes ~/.cloudflared/cert.pem
cloudflared tunnel login

# 2. Create tunnel
cloudflared tunnel create docs
cloudflared tunnel list                      # note the UUID

# 3. Config — ~/.cloudflared/config.yml
cat > ~/.cloudflared/config.yml <<'EOF'
tunnel: <Tunnel-UUID>
credentials-file: /home/<USER>/.cloudflared/<Tunnel-UUID>.json
ingress:
  - hostname: docs.example.com
    service: http://127.0.0.1:8380
  - service: http_status:404
EOF
cloudflared tunnel ingress validate

# 4. Route DNS — ⚠️🔒 H3: creates a public CNAME <UUID>.cfargotunnel.com
cloudflared tunnel route dns docs docs.example.com

# 5. Run (foreground first for a clean log, then install the service)
cloudflared tunnel run docs
# → verify G3-N.4 from another network, Ctrl-C, then:
cloudflared service install                  # Linux: needs sudo + explicit config path → A3; macOS: A3
```

**Gate** `[G3-N.1–G3-N.7]` · **On failure**: login did not open a browser → D1; DNS not resolving → H3 may need the zone on Cloudflare nameservers; 502 → Appendix B. · **Rollback**: Appendix C.

---

## §6 Phase 4 — Phone acceptance (DoD) 🔒

On the phone browser (try cellular **and** Wi-Fi): work through `[G4.1–G4.9]` in [deploy-gates.md](deploy-gates.md).

Notes: full-mode HTML uses a 30-second one-time ticket — re-tap if expired. Code/data files 404 by default (`--allow-code` opts in; companion stylesheets `.css` referenced by HTML excepted). Excluded paths 404 even by direct URL.

**Gate** `[G4]` = DoD · **On failure**: map the symptom via Appendix B.

---

## §7 Phase 5 — Security gates & handover

1. Walk through `[G5.1–G5.6]`.
2. Optional hardening: Cloudflare Access policy in front of `docs.example.com` (email OTP) — token remains the app-layer credential. 🔒
3. Fill the handover record (keep out of any public repo):

```
conv-docs deployment record
- host / OS:                 ______________________
- repo dir / version:        ______________________
- service unit:              conv-docs.service (systemd user) / launchd / foreground
- port:                      127.0.0.1:8380
- tunnel name / UUID:        ______________________
- public hostname:           ______________________
- cloudflared service:       systemd unit / launchd / foreground (config path: __________)
- config / state paths:      ~/.config/conv-docs/  ·  ~/.local/state/conv-docs/audit.log
- token:                     on the phone + ~/.config/conv-docs/token.txt (0600) — VALUE NOT RECORDED
- gates passed:              G0 __ G1 __ G2 __ G3 __ G4 __ G5 __   date: ______
```

---

## Appendix A — Platform tables

### A1 Base dependencies

| | Linux (Debian/Ubuntu) | macOS | WSL2 |
|---|---|---|---|
| git | `sudo apt-get install git` | preinstalled / `brew install git` | same as Linux |
| Python 3.10+ | `sudo apt-get install python3 python3-venv` | preinstalled / `brew install python` | same as Linux |
| uv (recommended) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | same | same as Linux |
| Node 18+ (optional) | `sudo apt-get install nodejs npm` | `brew install node` | same as Linux |

### A2 cloudflared install

| Platform | Command |
|---|---|
| Debian/Ubuntu | `sudo mkdir -p --mode=0755 /usr/share/keyrings` · `curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \| sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null` · `echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \| sudo tee /etc/apt/sources.list.d/cloudflared.list` · `sudo apt-get update && sudo apt-get install cloudflared` |
| RHEL/Fedora | `curl -fsSl https://pkg.cloudflare.com/cloudflared.repo \| sudo tee /etc/yum.repos.d/cloudflared.repo` · `sudo yum install cloudflared` |
| macOS | `brew install cloudflared` |
| Any | binary from the [downloads page](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) |

> Note: Cloudflare rotated its package signing key on **2025-10-30**; if installs fail with key errors on older setups, re-add the keyring as above.

### A3 Autostart

| Component | Linux | macOS | WSL2 |
|---|---|---|---|
| conv-docs | `bash scripts/install-service.sh` → systemd **user** unit (`~/.config/systemd/user/conv-docs.service`). Manage: `systemctl --user {status,restart,stop} conv-docs` · logs: `journalctl --user -u conv-docs -f` | no systemd: run foreground (`uv run conv-docs serve`), or a LaunchAgent with `ProgramArguments=[python,-m,conv_docs,serve]` `RunAtLoad`/`KeepAlive` | systemd available if `/etc/wsl.conf` has `[boot] systemd=true`; else foreground / Windows Task Scheduler calling `wsl -e` |
| cloudflared | `sudo cloudflared --config /home/<USER>/.cloudflared/config.yml service install` (**sudo makes `$HOME=/root` — pass `--config` explicitly**) · then `systemctl enable --now cloudflared` | login (user agent): `cloudflared service install` · boot (daemon, uses `/etc/cloudflared`): `sudo cloudflared service install` · manual: `sudo launchctl start com.cloudflare.cloudflared` · logs: `/Library/Logs/com.cloudflare.cloudflared.{err,out}.log` | same as Linux |

---

## Appendix B — Troubleshooting decision tree

| Symptom | Probe | Fix |
|---|---|---|
| Phone 401 | token complete? rotated since? | re-paste; `token rotate` invalidates old — 10 failures/15 min → 15-min lockout (429), wait or switch network |
| Phone 404 (file) | `uv run conv-docs list`; is the file hidden / non-whitelisted / excluded? | publish again with the right flags; excluded paths 404 by design |
| Tunnel 502/530 | G2.1 local? `cloudflared tunnel ingress validate`; docs rule above catch-all? | fix ordering; `journalctl --user -u conv-docs`; `systemctl status cloudflared` |
| Relay (herdr-remote) broke after edit | diff `config.yml` vs the `.bak.*` | restore backup → validate → reload (R2) |
| DNS not resolving | `dig +short docs.example.com CNAME` | nameservers on Cloudflare? `route dns` re-run (H3) |
| HTML full mode blank | ticket is 30 s one-shot | re-tap "full mode"; sandboxed scripts are expected |
| Page styles missing | CSP blocks external `<link>` | expected; companion `.css` is served automatically (only when referenced by an HTML file; unreferenced `.css` still 404s) |
| Quick Tunnel dead | process still running? | URL dies with the process; hostname changes each start — by design |
| cloudflared won't connect | `[G0.11]` egress 7844 | corporate firewall — see D2 |
| Service won't start | `journalctl --user -u conv-docs -n 50`; port conflict `ss -ltnp \| grep 8380` | fix config path / free the port |

---

## Appendix C — Rollback / teardown (progressive)

| Level | Action | Effect |
|---|---|---|
| C1 stop exposing content | `uv run conv-docs unpublish <name>` (all entries) | immediate; service keeps running |
| C2 stop the service | `systemctl --user disable --now conv-docs` (macOS: stop foreground/launchd) | tunnel returns 502 at origin |
| C3 remove from tunnel | restore `config.yml` backup (R2) → `cloudflared tunnel ingress validate` → `systemctl restart cloudflared` ⚠️ | hostname returns 404/502; **relay unaffected if backup is right** |
| C4 remove DNS | delete the `docs.example.com` CNAME in the Cloudflare dashboard (H3) | public name dies |
| C5 delete tunnel | `cloudflared tunnel delete docs` (after C4; remove `<UUID>.json`) | tunnel gone |
| C6 kill access | `uv run conv-docs token rotate` 🔒⚠️ | every phone loses access instantly |

---

## Appendix D — Headless login & network pre-checks

**D1 `cloudflared tunnel login` without a browser**: the command prints a URL instead of opening one. Open that URL on any machine, log in, select the zone — `cert.pem` is written **on the headless machine** afterwards. Verify: `ls ~/.cloudflared/cert.pem` (do not read it).

**D2 Connectivity pre-check**: cloudflared dials out to Cloudflare on **TCP 7844**. If G0.11 fails behind a corporate network, ask IT to allow `*.argotunnel.com:7844` outbound (see [connectivity pre-checks](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/troubleshoot-tunnels/connectivity-prechecks/)).

---

*End of runbook. Gates live in [deploy-gates.md](deploy-gates.md); agent protocol in `skills/conv-docs-deploy/SKILL.md`.*
