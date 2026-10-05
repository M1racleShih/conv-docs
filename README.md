<p align="center">
  <img src="assets/logo.svg" width="180" alt="conv-docs logo: a cute owl reading a document">
</p>

<h1 align="center">conv-docs</h1>

<p align="center"><b>Convenient Documents</b> — read-only workspace docs, on your phone.</p>

<p align="center">
  English · <a href="README.zh-CN.md">简体中文</a>
</p>

---

conv-docs serves **explicitly published** workspace directories from your PC, through a dedicated hostname on your [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/), to a mobile reader with token auth. Markdown and HTML render beautifully; strictly read-only; fully isolated from the [herdr-remote](https://github.com/dcolinmorgan/herdr-remote) agent control plane.

📘 Documentation (bilingual):

| | English | 中文 |
|---|---|---|
| Research report (why these wheels) | [docs/en/index.html](docs/en/index.html) | [docs/zh/index.html](docs/zh/index.html) |
| Design & threat model | [docs/en/design.html](docs/en/design.html) | [docs/zh/design.html](docs/zh/design.html) |
| Deployment & usage | [docs/en/deploy.html](docs/en/deploy.html) | [docs/zh/deploy.html](docs/zh/deploy.html) |
| Security review (STRIDE) | [docs/en/security-review.html](docs/en/security-review.html) | [docs/zh/security-review.html](docs/zh/security-review.html) |

## Features

- **Explicit grants** — nothing is exposed by default; `publish` / `unpublish` per directory, effective immediately
- **Strictly read-only** — GET/HEAD only; WebDAV-style write verbs return 405
- **Token auth** — Bearer token, server stores a SHA-256 hash only (config 0600), one-command rotation, per-source failure rate limiting
- **Markdown & HTML rendering** — marked + DOMPurify + highlight.js (vendored), plus a script-sandboxed "full mode" for interactive HTML
- **Path sandbox** — realpath containment, symlink-escape refusal, hidden files skipped, extension allowlist
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
| `publish <dir> [--as NAME] [--docs-only]` | Publish a directory explicitly (`--docs-only` = documents and images only) |
| `unpublish <name>` | Revoke a publish |
| `list` | Show the publish list |
| `token rotate` | Generate a new token and invalidate the old one |
| `serve [--host H] [--port P]` | Start the read-only service (default 127.0.0.1:8380) |

## Development & verification

```bash
uv run pytest                               # 49 unit tests: auth, read-only, path sandbox, tickets, headers
TOKEN=<token> node scripts/browser-smoke.mjs # headless-Chrome end-to-end: login → browse → render → sandbox (17 checks)
npm install && npm run build                # rebuild the TypeScript viewer (web-src/app.ts → src/conv_docs/web/app.js)
```

Project layout:

```
src/conv_docs/          Python package: server (store / security / http) + compiled web viewer
src/conv_docs/web/      viewer bundle (compiled app.js is committed; vendored libs incl. licenses)
web-src/app.ts          viewer source (TypeScript, strict)
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
