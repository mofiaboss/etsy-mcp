# OAuth 2.0 + PKCE

etsy-mcp uses the **Authorization Code Grant with PKCE** flow (RFC 7636) to authenticate against the Etsy Open API v3. This is the only flow Etsy accepts for public clients — there is no client secret in the authorization URL, so even if an attacker intercepts the authorization code from the redirect, they can't exchange it without the verifier.

## Endpoints

| Purpose | URL |
|---|---|
| Authorization (user consent) | `https://www.etsy.com/oauth/connect` |
| Token exchange | `https://api.etsy.com/v3/public/oauth/token` |
| Token refresh | `https://api.etsy.com/v3/public/oauth/token` (same endpoint, `grant_type=refresh_token`) |
| Revoke | User-initiated via https://www.etsy.com/your/account/apps |

## PKCE mechanics

### Step 1: Generate verifier + challenge

```python
from etsy_core.pkce import generate_pkce_pair

verifier, challenge = generate_pkce_pair()
# verifier: 43-char base64url-encoded random bytes
# challenge: base64url(SHA256(verifier))
```

### Step 2: Build authorization URL

```python
from etsy_core.auth import EtsyAuth

auth = EtsyAuth(keystring="your-app-keystring")
url, verifier, state = auth.build_authorization_url()
```

The URL includes:

- `response_type=code`
- `client_id={ETSY_KEYSTRING}`
- `redirect_uri=http://localhost:3456/callback`
- `scope=shops_r shops_w listings_r listings_w transactions_r transactions_w address_r address_w profile_r feedback_r favorites_r favorites_w cart_r cart_w treasury_r treasury_w`
- `state={random_state}` — CSRF protection
- `code_challenge={challenge}`
- `code_challenge_method=S256`

### Step 3: User consents

The CLI opens the URL in the user's browser. The user logs in to Etsy and approves the requested scopes. Etsy redirects to:

```
http://localhost:3456/callback?code={auth_code}&state={state}
```

A local `http.server` running on port 3456 catches the redirect, verifies the `state` parameter matches what was generated in step 2, and extracts the `code`.

### Step 4: Exchange code for tokens

```python
tokens = await auth.exchange_code(code=auth_code, verifier=verifier)
```

Under the hood:

```
POST https://api.etsy.com/v3/public/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&client_id={ETSY_KEYSTRING}
&redirect_uri=http://localhost:3456/callback
&code={auth_code}
&code_verifier={verifier}
```

Etsy verifies that `SHA256(verifier) == challenge` and returns:

```json
{
  "access_token": "12345678.abcdef...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "12345678.ghijkl...",
  "scope": "shops_r shops_w listings_r listings_w ..."
}
```

### Step 5: Persist tokens

`save_tokens()` writes to `~/.config/etsy-mcp/tokens.json` with mode `0600` (parent dir `0700`):

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1712345678,
  "granted_scopes": ["shops_r", "shops_w", ...],
  "obtained_at": 1712342078
}
```

The write is **atomic**: write to `tokens.json.tmp`, chmod to `0600`, then `os.replace()` to the final path. This survives crashes mid-write — either the new file is fully written or the old file is intact.

## Refresh flow — refresh tokens ROTATE

**Critical:** Etsy invalidates the old refresh token immediately on every refresh. You get a brand-new `refresh_token` in every successful response and the previous one stops working.

```python
new_tokens = await auth.refresh(current_tokens)
```

Under the hood:

```
POST https://api.etsy.com/v3/public/oauth/token

grant_type=refresh_token
&client_id={ETSY_KEYSTRING}
&refresh_token={old_refresh_token}
```

The response shape is identical to the initial exchange. The `EtsyAuth` class atomically writes the new tokens to disk before returning them to the caller — there is no window where the new tokens exist only in memory.

### Concurrent refresh safety

Two coroutines (or two MCP processes sharing the same token store) can race to refresh. The `EtsyAuth._refresh_with_lock` method uses `fcntl.flock(LOCK_EX)` on a sibling `tokens.json.lock` file:

1. Coroutine A acquires the lock
2. Coroutine A re-loads tokens from disk — if another process already refreshed, use those
3. Otherwise, perform the refresh and atomically write the result
4. Release the lock
5. Coroutine B acquires the lock, re-loads, sees fresh tokens, returns them — no duplicate API call

The unit test `test_concurrent_refresh_serializes` in `packages/etsy-core/tests/test_auth.py` verifies this end-to-end.

### invalid_grant is terminal

If Etsy returns `{"error": "invalid_grant"}` on refresh, the refresh token has been invalidated for some external reason (revoked in the Etsy dashboard, expired, leaked and rotated, etc.). The MCP raises `EtsyAuthError` with a clear message and **never auto-retries**. The user must run `etsy-mcp auth login` again to obtain a fresh token pair.

## Headless mode

If `ETSY_REFRESH_TOKEN` is set in the environment and `~/.config/etsy-mcp/tokens.json` does not exist, `EtsyAuth` constructs an in-memory `Tokens` instance with an immediate-expiry `access_token` and the env var as the refresh token. The first API call triggers a refresh, which writes a fresh `tokens.json` to disk. After that, the env var is ignored.

This is the recommended deployment pattern for CI environments where you don't want to bake `tokens.json` into a container image.

## Refresh lead time

The `Tokens.is_expired` property returns `True` when the access token is within `REFRESH_LEAD_SECONDS` (60s) of expiry. This gives ample headroom for the refresh round-trip and avoids the "token expired mid-request" race.

## What never leaks

The F3 redaction layer (see [SECURITY.md](../SECURITY.md)) ensures `access_token`, `refresh_token`, `client_secret`, and `keystring` never appear in:

- Log lines (DEBUG, INFO, WARNING, ERROR)
- Tool response envelopes
- Error messages or stack traces

The unit test `test_refresh_does_not_leak_secrets_in_logs` asserts this.
