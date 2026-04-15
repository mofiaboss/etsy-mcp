# Security Policy

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

### Primary channel: GitHub Security Advisories

1. Go to https://github.com/mofiaboss/etsy-mcp/security/advisories
2. Click "Report a vulnerability"
3. Provide:
   - Description and impact
   - Steps to reproduce
   - Affected versions
   - Any proof-of-concept code

### Response timeline

- **Acknowledgment:** within 72 hours
- **Triage:** within 7 days — severity assessment + remediation plan
- **Fix:** coordinated 90-day disclosure window
- **Disclosure:** advisory published after fix or after 90 days, whichever comes first

Reporters are credited in the advisory unless they request anonymity.

## Threat Model Summary

etsy-mcp brokers OAuth tokens and buyer PII from the Etsy API. The principal threats:

| Threat | Mitigation |
|---|---|
| OAuth token leakage via logs | F3 redaction layer scrubs every log line, error envelope, and tool response |
| Token theft from disk | `~/.config/etsy-mcp/tokens.json` is mode `0600`, parent dir mode `0700` |
| Token corruption mid-write | Atomic write via temp file + rename, plus `fcntl.flock` to serialize concurrent refreshes |
| Refresh token replay after rotation | Etsy invalidates the old refresh token immediately; we persist the new one before returning to caller |
| Authorization code interception | PKCE S256 challenge required on every authorization URL |
| CSRF on OAuth callback | Random `state` parameter generated per-flow and verified before token exchange |
| Buyer PII exposure (email, name, address) | F3 redaction includes `email`, `first_name`, `last_name`, `name`, `etsy_user_id` |
| Double-charge from retried writes | `EtsyPossiblyCompletedError` raised on POST timeout — never auto-retried |
| Daily budget exhaustion via runaway loop | Daily counter refuses new requests at 95% of the configured budget |
| Destructive action without consent | Preview-then-confirm flow on all mutations + policy gate env vars |

## F3 Redaction

Every log path, every error envelope, every tool response runs user-controlled data through `redact_sensitive()` from `etsy_core.redaction` before emission. The default field list:

- OAuth credentials: `access_token`, `refresh_token`, `shared_secret`, `keystring`, `client_secret`, `client_id`, `Authorization`, `x-api-key`
- Buyer PII: `email`, `first_name`, `last_name`, `name`
- User identifiers: `etsy_user_id`, `user_id`
- Legacy: `authCode`

Redaction is **defense-in-depth**. The primary protection is never logging secrets in the first place — but when that fails (and it will), redaction catches it.

## Token Rotation Incident Response

If you suspect your tokens have been compromised:

1. **Immediately revoke** the app authorization at https://www.etsy.com/your/account/apps
2. Delete `~/.config/etsy-mcp/tokens.json`
3. Re-run `etsy-mcp auth login` to obtain fresh tokens
4. Audit your shop's order history and listing changes for unauthorized activity
5. Rotate your `ETSY_KEYSTRING` in the Etsy developer console if you suspect the keystring itself leaked

If you find evidence of unauthorized API activity originating from etsy-mcp specifically, file a security advisory per the channel above.

## Scope

### In scope

- All code in `apps/etsy/`, `packages/etsy-core/`, `packages/etsy-mcp-shared/`
- The OAuth flow, token storage, refresh logic, F3 redaction layer
- The retry, rate limiting, and possibly-completed-error guards
- Documentation that recommends insecure practices

### Out of scope

- Etsy API itself (report to https://www.etsy.com/developers)
- Vulnerabilities in upstream dependencies (`httpx`, `tenacity`, `pydantic`, etc.) — report to the respective maintainers, then we'll bump the pin
- Vulnerabilities in MCP protocol clients (Claude Desktop, Claude Code, etc.) — report to Anthropic
