---
name: conv-docs
description: "Send documents and reports to the user's phone via the conv-docs read-only gateway. Use when the user asks to 'send to my phone', 'preview/publish docs', push a report for mobile reading, or manage published workspaces. Covers temporary previews (TTL / burn-after-reading), exclude patterns for sensitive files, code filtering, and project grouping."
---

# conv-docs — Convenient Documents on Your Phone

conv-docs serves explicitly published files from this PC to the user's phone through a
token-authenticated, strictly read-only web viewer (Markdown / HTML / text / image / PDF).
Use it whenever the user wants to **read workspace output on a mobile device**.

## When to use

- The user asks to "send this to my phone", "let me read it on mobile", "给我看/发手机".
- You finished a report, design doc, or research note and want to hand it over for review.
- The user asks to manage what is exposed: publish, unpublish, list, or preview.

## Preconditions (check, don't assume)

1. Service reachable: `curl -s http://127.0.0.1:8380/api/v1/health` → `{"ok": true, ...}`.
   If not running, it is usually a systemd user unit: `systemctl --user start conv-docs`.
   Starting a foreground server yourself is a last resort — ask first.
2. Token exists: `conv-docs list` works without it; the viewer needs the token the user
   already has. **Never read, print, copy, or embed the token** (it lives in
   `~/.config/conv-docs/token.txt`, 0600 — do not open that file, do not paste it into
   any document, log, commit, or preview content).

All examples below assume `uv run conv-docs` (equals `python3 -m conv_docs`).
A custom config path may apply (`--config` / `CONV_DOCS_CONFIG`).

## Core workflow

**Prefer `preview` for agent-generated output** — it expires automatically and cannot
linger as a standing exposure:

```bash
uv run conv-docs preview report.md                 # single file, expires in 24h
uv run conv-docs preview docs/ --ttl 2h            # a directory, custom lifetime
uv run conv-docs preview report.md --once          # burn after first read (10-min grace)
uv run conv-docs preview docs/ --project alpha     # grouped in the web UI
```

- `--ttl` accepts `30m`, `2h`, `7d`, or plain seconds (max 30d; default 24h).
- Re-previewing the same path **replaces** the old preview and resets the clock.
- `--once`: the countdown starts at the first content access, then the entry vanishes.

**Use `publish` only for long-lived, deliberately shared directories:**

```bash
uv run conv-docs publish ~/work/proj-a --as proj-a --project alpha
```

**Manage:**

```bash
uv run conv-docs list          # shows previews with remaining time, projects, excludes
uv run conv-docs unpublish <name>
```

After previewing/publishing, tell the user the entry name and where to find it
(the conv-docs site on their phone; previews are marked "temporary/single view").

## Safety rules (non-negotiable)

1. **Exclude sensitive files before exposing anything** — exclude patterns are enforced
   server-side at every layer (listing and direct access both 404):

   ```bash
   uv run conv-docs preview docs/ --exclude '*.env' --exclude 'secrets/**' --exclude '*.pem'
   ```

   Pattern semantics (simplified .gitignore): no `/` → matches the file name at any depth
   (`*.env`, `id_rsa`); with `/` → relative to the published root (`secrets/**`, `build/*`).
   Before publishing a directory for the first time, scan it for credentials, keys,
   tokens, or private data and add excludes accordingly.

2. **Source code and structured data are hidden by default** (`.py/.ts/...`, json/yaml/toml,
   Dockerfile...). Add `--allow-code` only when the user explicitly wants code visible.
   HTML files that load companion `.css` need `--allow-code` for their styles to render.

3. **`--docs-only`** is the strictest tier (markdown/html/image/pdf only).

4. Never preview/publish: dotfiles are skipped automatically, but also avoid `.ssh`,
   credential dirs, anything containing secrets even after excludes — when in doubt,
   copy the safe files to a temp directory and preview that.

5. The token is the only gate to all published content. It must never appear in output
   you produce. If a document accidentally contains the token, unpublish immediately
   and ask the user to rotate (`uv run conv-docs token rotate`).

## Quick reference

| Need | Command |
|------|---------|
| Temporary hand-off (default choice) | `preview <file\|dir> [--ttl 2h] [--once]` |
| Long-lived share | `publish <dir> [--as NAME]` |
| Group under a project | add `--project NAME` |
| Hide sensitive paths | add `--exclude GLOB` (repeatable) |
| Show code/config files | add `--allow-code` |
| Strictest tier | add `--docs-only` |
| See what is exposed | `list` |
| Revoke | `unpublish <name>` |
