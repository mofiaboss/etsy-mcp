# etsy-mcp

Professional-grade Model Context Protocol server wrapping the [Etsy Open API v3](https://developers.etsy.com/documentation/) as **pure capability primitives**. Built so AI agents (Claude, ChatGPT, Gemini, local Llama) can manage Etsy shops at scale without baked-in heuristics getting in their way.

[![CI](https://img.shields.io/github/actions/workflow/status/mofiaboss/etsy-mcp/ci.yml?branch=main)](https://github.com/mofiaboss/etsy-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/etsy-mcp)](https://pypi.org/project/etsy-mcp/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## What this is

90 tools across 13 categories — every endpoint your agent needs to:

- Read shops, listings, listing images/videos/inventory/properties/translations/digital files
- Manage receipts, payments, shipping profiles
- Walk the seller taxonomy and read reviews
- Look up users and buyer addresses
- Bulk create / update listings from templates (rate-limit-friendly)
- Bulk update image alt_text across an entire shop

Every tool is a thin wrapper around an Etsy API endpoint. **No scoring algorithms. No SEO heuristics. No tag generators. No "AI search readiness" judgments.** The MCP is a capability layer; your model is the reasoning layer.

## Why pure primitives

A baked-in `seo_score_listing` heuristic goes stale the day it ships. AI ranking algorithms change constantly, and Claude/GPT/Gemini/Llama all reason differently about SEO. By keeping every judgment inside the model, the MCP works identically across every agent today and continues to work as both Etsy's algorithms and your model evolve. Less code, lower test surface, no hidden intelligence to debug. See [docs/WORKFLOWS.md](docs/WORKFLOWS.md) for end-to-end LLM-driven workflow examples that prove the model alone is enough.

## How we compare

| Project | Tools | Reasoning baked in? |
|---|---|---|
| [aserper/etsy-mcp](https://github.com/aserper/etsy-mcp) | 37 | partial |
| [profplum700/etsy-mcp](https://github.com/profplum700/etsy-mcp) | 10 | partial |
| **etsy-mcp (this project)** | **90** | **none — pure primitives** |

## Quick start

### Install

```bash
uvx etsy-mcp@latest --help
```

Or install into a project:
```bash
uv add etsy-mcp
```

### Authenticate

```bash
etsy-mcp auth login
```

This walks you through the OAuth 2.0 + PKCE flow, opens your browser, captures the callback on `localhost:3456`, and writes tokens to `~/.config/etsy-mcp/tokens.json` (mode 0600). Refresh tokens rotate automatically; you only re-auth if your refresh token is invalidated.

### Register with Claude Code

```bash
claude mcp add etsy -- uvx etsy-mcp@latest
```

Or in `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "etsy": {
      "command": "uvx",
      "args": ["etsy-mcp@latest"],
      "env": {
        "ETSY_KEYSTRING": "your-app-keystring"
      }
    }
  }
}
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — package layering and responsibilities
- [docs/OAUTH.md](docs/OAUTH.md) — full PKCE flow and token rotation
- [docs/RATE_LIMITS.md](docs/RATE_LIMITS.md) — token bucket, daily counter, backoff
- [docs/ERROR_HANDLING.md](docs/ERROR_HANDLING.md) — exception hierarchy and envelope shapes
- [docs/TESTING.md](docs/TESTING.md) — unit and integration test strategy
- [docs/WORKFLOWS.md](docs/WORKFLOWS.md) — **end-to-end LLM workflows using only primitives**
- [docs/permissions.md](docs/permissions.md) — policy gates and confirmation modes
- [SECURITY.md](SECURITY.md), [PRIVACY.md](PRIVACY.md)

## Security notice

Tokens are stored locally at `~/.config/etsy-mcp/tokens.json` with mode `0600`. Refresh tokens rotate on every refresh — Etsy invalidates the old one immediately. The F3 redaction layer scrubs OAuth tokens, buyer PII (`email`, `first_name`, `last_name`, `name`, `etsy_user_id`), and shop credentials from every log line, error envelope, and tool response. Report vulnerabilities per [SECURITY.md](SECURITY.md) — never via public issues.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow, golden paths, and PR conventions. The full project rules live in [AGENTS.md](AGENTS.md) — read them before opening a PR.

## License

[MIT](LICENSE) — copyright 2026 Rick Villucci
