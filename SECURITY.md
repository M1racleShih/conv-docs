# Security Policy

English · [简体中文](SECURITY.zh-CN.md)

## Model summary

conv-docs is a single-user, token-authenticated, strictly read-only document gateway. Core guarantees:

- Only explicitly `publish`ed directories are readable; hidden files, files outside the extension allowlist, and symlinks escaping the root are always refused.
- The server never serves user content as `text/html`; HTML full mode runs behind a one-shot ticket in a CSP sandbox without `allow-same-origin` (opaque origin).
- The token is stored as a SHA-256 hash in a 0600 config file and travels only in the `Authorization: Bearer` header; failed authentication is rate-limited per source.
- There is no write endpoint; write-style methods (including WebDAV verbs) return 405.

Threat model, residual risks and per-threat countermeasures: [docs/en/design.html](docs/en/design.html). STRIDE review with code-level findings: [docs/en/security-review.html](docs/en/security-review.html). Deployment checklist: [docs/en/deploy.html](docs/en/deploy.html).

## Supported versions

Security fixes land on the main branch; the project is 0.x and interfaces may change.

## Reporting a vulnerability

Please report via GitHub Issues (or a private security advisory) with: impact, reproduction steps, exploit scenario. Do not disclose unfixed vulnerabilities publicly.

## Operational advice

- On token leakage or device loss, run `uv run conv-docs token rotate` immediately.
- Keep the service bound to `127.0.0.1` and expose it only through Cloudflare Tunnel; never expose the port directly.
- Review directory contents before publishing; when unsure, use `--docs-only`.
- Optionally add a Cloudflare Access policy in front of `docs.*` as a second layer.
