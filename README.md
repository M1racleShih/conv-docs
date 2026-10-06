<p align="center">
  <img src="assets/logo.svg" width="180" alt="conv-docs logo: a cute owl reading a document">
</p>

<h1 align="center">conv-docs</h1>

<p align="center"><b>Convenient Documents</b> — read-only workspace docs, on your phone.</p>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a>
</p>

---

conv-docs serves **explicitly published** workspace directories from your PC, through a dedicated hostname on your [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/), to a mobile reader with token auth. Markdown and HTML render beautifully; strictly read-only; fully standalone — useful with any workflow that produces documents, and isolated from everything else running on your machine.

📘 Documentation (bilingual):

| | English | 中文 |
|---|---|---|
| Research report (why these wheels) | [docs/en/index.html](docs/en/index.html) | [docs/zh/index.html](docs/zh/index.html) |
| Design & threat model | [docs/en/design.html](docs/en/design.html) | [docs/zh/design.html](docs/zh/design.html) |
| Deployment & usage | [docs/en/deploy.html](docs/en/deploy.html) | [docs/zh/deploy.html](docs/zh/deploy.html) |
| Security review (STRIDE) | [docs/en/security-review.html](docs/en/security-review.html) | [docs/zh/security-review.html](docs/zh/security-review.html) |

## Features

- **Explicit grants** — nothing is exposed by default; `publish` / `unpublish` per directory, effective immediately
- **Temporary previews** — `preview` a file or directory with a TTL (default 24h) or `--once` burn-after-reading; same path re-previews replace and reset
- **Code filtering** — source code and structured data/config files (`.py`, `.json`, `.yaml`, …) are hidden by default; opt in per publish with `--allow-code`
- **Exclude patterns** — `--exclude '*.env' --exclude 'secrets/**'`: server-enforced at every layer (listings and direct access both 404)
- **Projects** — `--project NAME` groups entries in the web UI; single-token model unchanged
- **Strictly read-only** — GET/HEAD only; WebDAV-style write verbs return 405
- **Token auth** — Bearer token, server stores a SHA-256 hash only (config 0600), one-command rotation, per-source failure rate limiting
- **Markdown & HTML rendering** — marked + DOMPurify + highlight.js (vendored), plus a script-sandboxed "full mode" for interactive HTML
- **Path sandbox** — realpath containment, symlink-escape refusal, hidden files skipped, extension allowlist
- **Agent skill** — `skills/conv-docs/SKILL.md` lets coding agents hand reports to your phone safely (preview-first, excludes, token discipline)
- **Zero third-party runtime dependencies** — Python 3.10+ standard library; the viewer is dependency-free TypeScript
- **Bilingual UI** — English by default, one tap to switch to Chinese

## Quick start

```bash
uv sync                                # create .venv and lock deps (recommended; plain python3 also works)
uv run conv-docs token rotate          # generate the token (printed once)
uv run conv-docs publish ~/work/proj-a --as proj-a
uv run conv-docs serve                 # 127.0.0.1:8380
```

> `uv run conv-docs` is equivalent to `python3 -m conv_docs`. The server has zero third-party runtime dependencies.

Run as a service: `bash scripts/install-service.sh` (systemd user unit + a cloudflared ingress snippet).

## Commands

| Command | Purpose |
|---------|---------|
| `publish <dir> [--as NAME] [--docs-only] [--project P] [--exclude GLOB…] [--allow-code]` | Publish a directory explicitly (`--docs-only` = documents and images only) |
| `preview <file\|dir> [--as NAME] [--ttl 2h] [--once] [same flags as publish]` | Temporary preview that expires (default 24h; `--once` burns 10 min after first view) |
| `unpublish <name>` | Revoke a publish or preview |
| `list` | Show publishes and previews (remaining time, project, excludes) |
| `token rotate` | Generate a new token and invalidate the old one |
| `serve [--host H] [--port P]` | Start the read-only service (default 127.0.0.1:8380) |

Notes:

- **Code filtering**: code and data/config files are hidden by default (global `settings.filter_code`, per-entry `--allow-code` override). Plain-text documents and data tables (`txt/log/rst/csv/tsv…`) stay visible. HTML files that load companion `.css` need `--allow-code` for their styles.
- **Exclude semantics** (simplified .gitignore): a pattern without `/` matches that file name at any depth (`*.env`); with `/` it is relative to the root (`secrets/**`, `build/*`). Excluded paths are enforced server-side — hidden from listings and 404 on direct access.
- **Previews**: re-previewing the same path replaces the old entry and resets the clock; expired/burned entries disappear automatically.

## Development & verification

```bash
uv run pytest                               # 77 unit tests: auth, read-only, path sandbox, tickets, headers, code filter, excludes, previews
TOKEN=<token> node scripts/browser-smoke.mjs # headless-Chrome end-to-end: login → browse → render → sandbox (18 checks; fixture root needs --allow-code)
npm install && npm run build                # rebuild the TypeScript viewer (web-src/app.ts → src/conv_docs/web/app.js)
```

Project layout:

```
src/conv_docs/          Python package: server (store / security / http) + compiled web viewer
src/conv_docs/web/      viewer bundle (compiled app.js is committed; vendored libs incl. licenses)
web-src/app.ts          viewer source (TypeScript, strict)
skills/conv-docs/       agent skill source (import into a skill pool with `dskills install skills/conv-docs`)
tests/                  test suite (unittest-style; runs under pytest or unittest)
scripts/                install-service.sh · fetch-vendor.sh · browser-smoke.mjs
docs/en/, docs/zh/      HTML documentation (bilingual)
assets/                 logo (original artwork, MIT)
pyproject.toml          uv project (zero runtime deps; dev group has pytest) · uv.lock committed
```

## Security

Threat model and residual risks: [docs/en/design.html](docs/en/design.html). Deployment checklist: [docs/en/deploy.html](docs/en/deploy.html). Key invariants: user content is **never** served as `text/html` (full mode excepted, forced CSP sandbox without `allow-same-origin`); the token travels only in the `Authorization` header; audit log at `~/.local/state/conv-docs/audit.log`. Report issues per [SECURITY.md](SECURITY.md).

## Third-party components

| Component | Version | License | Role |
|-----------|---------|---------|------|
| [marked](https://github.com/markedjs/marked) | 18.0.14 | MIT | Markdown parsing |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.16 | Apache-2.0 | HTML/XSS sanitisation |
| [highlight.js](https://github.com/highlightjs/highlight.js) | 11.12.0 | BSD-3-Clause | Syntax highlighting |

Each component keeps its own license; original texts live in `src/conv_docs/web/vendor/LICENSE.*`. See [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) for the full statement.

## License

MIT — see [LICENSE](LICENSE). The logo (`assets/logo.svg`) is original artwork under the same MIT terms; it references no third-party intellectual property.
