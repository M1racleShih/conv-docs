---
name: conv-docs-deploy
description: "Deploy conv-docs from zero to a working mobile-readable instance, including Cloudflare Tunnel setup. Use when asked to 'deploy/安装/打通 conv-docs', expose it via Cloudflare Tunnel, set it up on a new machine, or take over an existing deployment. Covers build, local service, tunnel branches (reuse / from-zero / quick smoke), phone acceptance, and handover — with strict stop conditions around shared services and secrets."
---

# conv-docs-deploy — 0→1 deployment protocol

You are executing a deployment runbook. The runbook is the single source of truth for
**what to run**; this skill defines **how to execute it safely**. Do not invent steps,
do not "automate" the runbook into scripts, do not add Docker.

## Documents (read before starting)

| Document | Role |
|---|---|
| `docs/deploy-runbook.en.md` | The runbook itself. Section numbers `§` are identical in zh/en. |
| `docs/deploy-gates.md` | Gates G0–G5: every check command, expected output, on-fail pointer. |
| `docs/deploy-runbook.zh.md` | Chinese mirror (for Chinese-speaking users). |

Read the runbook end-to-end once before Phase 0. Execute phases **in order**:
P0 (§2) → P1 (§3) → P2 (§4) → P3 (§5) → P4 (§6) → P5 (§7).

## When NOT to use

- Routine publish/preview/reading → use the `conv-docs` skill instead.
- The machine already runs conv-docs in production and the user only wants changes →
  this skill only for read-only verification (§2.3 adopt path); every change needs approval.

## Iron rules (from runbook §0 — non-negotiable)

1. **Never break a running service.** Survey first (§2.1). If `conv-docs` or
   `cloudflared` is active, it is production: no restart, no `install-service.sh`
   re-run (it restarts conv-docs), no `token rotate`, no `npm run build` on the live
   checkout (it rewrites the served viewer).
2. **Shared tunnel = additive only.** Backup `~/.cloudflared/config.yml` before any
   edit, append ingress **above** the catch-all, `cloudflared tunnel ingress validate`
   must pass before any reload. If anything else (e.g. herdr-remote relay) regresses,
   restore the backup immediately (§B "relay broke").
3. **Secrets never touch your output.** Do not `cat`/print/paste `token.txt`,
   `cert.pem`, `*.json` credentials, or the token itself — not into chat, documents,
   commits, logs, or preview content. The token reaches the phone only via the human.
   Grep-checks that would require reading a secret → hand to the human (see G5.2).
4. **conv-docs binds 127.0.0.1 only.** Never `--host 0.0.0.0`. Exposure goes through
   the tunnel only.
5. **No new scripts.** Every verification is the read-only probe listed in the gates.

## Execution protocol

1. **Phase order is mandatory.** A gate that has not passed blocks the next phase.
   Report gate results compactly (`G2.4 ok — loopback only`, `G2.2 ok — 401`).
2. **Idempotency: probe before creating.** Re-running a phase must be safe: check
   `cloudflared tunnel list` before `create`, `ls` before `mkdir`, `conv-docs list`
   before `publish`. Never duplicate tunnels, DNS records, or ingress rules.
3. **Branch selection** comes from the §2.2 decision tree (D1–D6), not from guessing.
   State which branch you took and why, in one line.
4. **State-changing commands are labelled ⚠️ in the runbook.** Before each one: say
   what it changes, get confirmation (see Stop conditions), then run once.
5. **On failure:** follow the gate's on-fail pointer (usually Appendix B). Do not
   improvise. The same check failing **3 times** → stop and report: what you ran,
   what you saw, what you suspect, what you need from the human.
6. **DoD is gates, not vibes.** Deployment is "done" when G0–G3 are green and the
   human has checked G4.1–G4.8 on the phone (G4 is 🔒 human-only — hand over the
   checklist, don't claim it passed).

## Stop conditions — pause and ask the human

- 🔒 Cloudflare account/login/zone authorization (`cloudflared tunnel login`, H1/H2).
- 🔒 Any public DNS change (`cloudflared tunnel route dns`, CNAME deletion, H3).
- 🔒 Any purchase or account creation.
- 🔒 Handing the token to the phone, or any command needing the token value
  (G2.3, G4, G5.2, G5.4). If the human exports `TOKEN` in the environment you may
  use it in commands without reading its value from disk.
- ⚠️ Restarting a shared `cloudflared` (brief relay downtime) — confirm timing first.
- ⚠️ `token rotate` on any machine where a phone already holds a working token.
- Anything you cannot verify read-only, and any 3-strike failure (§ protocol 5).

## Worked example of a safe P3 edit (branch A)

Backup → append one ingress rule above catch-all → `ingress validate` → ask before
`route dns` → ask before `systemctl restart cloudflared` → gates G3-N.1–G3-N.7,
including G3-N.6 (the relay must not regress). Full commands: runbook §5.B.

## Quick reference

| Situation | Go to |
|---|---|
| Fresh machine, nothing installed | §2 survey → §3 build → §4 local → §5.C from-zero tunnel |
| Cloudflare already used (tunnel exists) | §5.B reuse (additive ingress) |
| Zero-account smoke first | §5.A Quick Tunnel (temporary URL, kill after) |
| Machine already serving conv-docs | §2.3 adopt path — verify gates only |
| Headless server (no browser) | Appendix D1 (login URL flow) |
| Something broke | Appendix B decision tree |
| Undo / take offline | Appendix C progressive rollback |
| Acceptance evidence | deploy-gates.md G0–G5 |
