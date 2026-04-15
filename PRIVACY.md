# Privacy Policy

**Last updated:** 2026-04-15

## Summary

etsy-mcp does not collect, store, or transmit any data to us. Everything happens locally between your AI agent and the Etsy API. We have no servers, no analytics, no telemetry. However — **etsy-mcp does touch buyer personal data** that the Etsy API returns as part of normal seller operations. This document explains what data passes through and how it's protected.

## How etsy-mcp works

```
Your AI Agent <--local stdio--> etsy-mcp (on your machine) <--HTTPS--> api.etsy.com
```

etsy-mcp runs locally on your machine. Your agent (Claude Code, Claude Desktop, or any other MCP client) speaks the MCP protocol to it over stdio or HTTP. etsy-mcp speaks OAuth-authenticated HTTPS to Etsy.

## What we don't collect

- **No telemetry.** Zero usage data, error reports, or analytics.
- **No phone-home.** etsy-mcp connects only to `api.etsy.com` and `www.etsy.com` (auth). Nothing else.
- **No persistent storage of buyer data.** Buyer information is fetched on-demand and held in memory only for the duration of the tool call.
- **No tracking.** No cookies, no fingerprinting.

## Buyer PII the MCP touches

When you call receipt-related tools (`etsy_receipts_*`), the Etsy API returns buyer information that the MCP must process to fulfill the request:

| Field | Source endpoint | Why it's needed |
|---|---|---|
| `email` | `/shops/{shop_id}/receipts/{receipt_id}` | Order management, customer communication |
| `first_name` / `last_name` / `name` | Same | Shipping labels, order display |
| `formatted_address`, `city`, `state`, `zip`, `country` | Same | Shipping address |
| `phone_number` | Same | Carrier delivery contact |
| `transparency_message` | Same | Buyer's note to seller |

This data flows from `api.etsy.com` -> etsy-mcp (in memory) -> your AI agent (via the MCP protocol). It is never persisted to disk by etsy-mcp.

## How buyer PII is protected

### F3 redaction in logs and errors

Every log line, error envelope, and tool response runs user-controlled data through `redact_sensitive()` before emission. The default field list redacts `email`, `first_name`, `last_name`, `name`, `etsy_user_id`, and `user_id` to `[REDACTED — sensitive field]`.

This means: even if you `tail -f` the MCP's stderr while running, you will not see buyer email addresses in log lines. The structured tool response that reaches your agent does contain the raw fields (because your agent needs them to fulfill the user's request) — but every other emission path is scrubbed.

### Tool responses are not stored by etsy-mcp

Once a tool call returns, etsy-mcp holds nothing. There is no cache, no database, no session file. Re-calling the same tool re-fetches from Etsy.

### Your AI agent may store conversation history

This is **outside etsy-mcp's control**. Whatever your MCP client does with tool responses (Claude Desktop saves conversations, etc.) is governed by the client's privacy policy. If you handle sensitive buyer data, configure your client accordingly.

## Scope minimization advice

By default, `etsy-mcp auth login` requests the full seller scope set. If you don't need write access or buyer-PII-touching endpoints, request a narrower scope:

```bash
etsy-mcp auth login --scope shops_r listings_r profile_r
```

This grants read-only access to your shop, listings, and profile — no transaction or buyer data. Etsy enforces the granted scopes server-side, so a narrower scope makes it impossible for the MCP (or a buggy LLM) to ever touch buyer data.

| Scope | What it lets the MCP read/write |
|---|---|
| `shops_r` / `shops_w` | Shop metadata |
| `listings_r` / `listings_w` | Listings, images, inventory, properties |
| `transactions_r` / `transactions_w` | Receipts (includes buyer PII), payments, shipping |
| `address_r` / `address_w` | Buyer addresses on receipts |
| `profile_r` | Your own profile |
| `feedback_r` | Reviews on your listings |

The `transactions_*` and `address_*` scopes are the only ones that expose buyer PII. Skip them if your use case is purely listing management.

## Token storage

OAuth tokens live at `~/.config/etsy-mcp/tokens.json` with file mode `0600` and parent directory mode `0700`. They are never transmitted anywhere except back to Etsy on token refresh. See [SECURITY.md](SECURITY.md) for the full token threat model.

## Questions

Open a discussion at https://github.com/mofiaboss/etsy-mcp/discussions.
