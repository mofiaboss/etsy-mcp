"""OAuth 2.0 + PKCE authentication for Etsy API v3.

This module implements the full OAuth flow:
1. Build authorization URL with PKCE challenge
2. Exchange authorization code for tokens (via token endpoint)
3. Persist tokens atomically with file lock
4. Refresh tokens automatically when expiring (rotation-aware)
5. Load tokens from disk on startup

Critical security properties:
- Token storage at ~/.config/etsy-mcp/tokens.json (mode 0600, parent 0700)
- File lock via fcntl.flock() prevents concurrent refresh races
- Atomic write via tempfile + rename survives crashes mid-refresh
- refresh_token rotates on every refresh (Etsy requirement)
- invalid_grant is terminal — never auto-retry, prompt re-login
- F3 redaction: tokens never appear in logs or error messages
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from etsy_core.exceptions import EtsyAuthError
from etsy_core.pkce import CODE_CHALLENGE_METHOD, generate_pkce_pair, generate_state

logger = logging.getLogger(__name__)

ETSY_AUTH_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"


def _safe_json_body(response: httpx.Response) -> dict[str, Any]:
    """Parse a non-200 OAuth response body without crashing on malformed JSON.

    Cycle 2 fix P1-A: Etsy proxies sometimes return HTML 502 pages with
    misleading `Content-Type: application/json` headers, or truncated bodies
    that pass the content-type check but fail to parse. The previous direct
    `response.json()` call crashed with a raw JSONDecodeError stack trace
    instead of producing a clean EtsyAuthError. This helper degrades to an
    empty dict so the caller can construct a clean error message.
    """
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("application/json"):
        return {}
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}

#: Default scope set for the "full seller" profile.
#: Covers every permission needed for listing management, orders, shipping,
#: and buyer interaction. Users can request a narrower set via the CLI
#: --scope flag if they want to principle-of-least-privilege their setup.
DEFAULT_SCOPES = (
    "shops_r",
    "shops_w",
    "listings_r",
    "listings_w",
    "transactions_r",
    "transactions_w",
    "address_r",
    "address_w",
    "profile_r",
    "feedback_r",
    "favorites_r",
    "favorites_w",
    "cart_r",
    "cart_w",
    "treasury_r",
    "treasury_w",
)

#: Refresh tokens this many seconds before the access token expires.
#: 60 seconds gives ample headroom for the refresh round-trip and avoids
#: the "token expired mid-request" race.
REFRESH_LEAD_SECONDS = 60


@dataclass(frozen=True)
class Tokens:
    """OAuth token state — IMMUTABLE.

    Cycle 1 review fix: this dataclass is frozen and `granted_scopes` is a
    `frozenset[str]` so callers cannot mutate authorization state after
    construction (e.g., appending fake scopes to bypass scope checks).
    Construction enforces invariants in `__post_init__`. The only legal
    "needs refresh" state is the one produced by `bootstrap_from_refresh_token`.

    Attributes:
        access_token: Bearer token for API requests. May be empty ONLY when
            the instance was produced by `bootstrap_from_refresh_token`.
        refresh_token: Used to mint new access tokens (rotates on each refresh).
            MUST be non-empty.
        expires_at: Unix timestamp when access_token expires. May be 0 ONLY
            when bootstrapping from env var.
        granted_scopes: Scopes actually granted by Etsy. Frozen at construction.
        obtained_at: Unix timestamp when tokens were obtained.
    """

    access_token: str
    refresh_token: str
    expires_at: int
    granted_scopes: frozenset[str] = field(default_factory=frozenset)
    obtained_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        # Refresh token is the only true invariant — without it we cannot
        # ever mint a new access token, so an instance with no refresh_token
        # is structurally useless and should be rejected at construction.
        if not self.refresh_token or not self.refresh_token.strip():
            raise ValueError(
                "Tokens.refresh_token must be non-empty. "
                "Use Tokens.bootstrap_from_refresh_token() for the env-var case."
            )
        # access_token + expires_at can be empty/zero only in the bootstrap
        # case (where they will be filled in by the next refresh call).
        # We don't enforce a strict combination here because the same shape
        # is used as a transient "force refresh" sentinel; downstream
        # `is_expired` already handles expires_at=0 correctly.

    @property
    def is_expired(self) -> bool:
        """True if the access token is within REFRESH_LEAD_SECONDS of expiring."""
        return time.time() >= (self.expires_at - REFRESH_LEAD_SECONDS)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Note: granted_scopes is converted from frozenset to a sorted list
        for stable on-disk representation (json doesn't natively handle sets).
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "granted_scopes": sorted(self.granted_scopes),
            "obtained_at": self.obtained_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tokens:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data["expires_at"]),
            granted_scopes=frozenset(data.get("granted_scopes", [])),
            obtained_at=int(data.get("obtained_at", time.time())),
        )

    @classmethod
    def bootstrap_from_refresh_token(cls, refresh_token: str) -> Tokens:
        """Construct a 'needs immediate refresh' Tokens instance.

        Used by the ETSY_REFRESH_TOKEN env var fallback path: we have a
        refresh token but no access token yet. The next call to
        `EtsyAuth.get_access_token()` will trigger a refresh that fills in
        the real access_token + expires_at + granted_scopes.
        """
        if not refresh_token or not refresh_token.strip():
            raise ValueError("bootstrap_from_refresh_token requires a non-empty refresh_token")
        return cls(
            access_token="",
            refresh_token=refresh_token.strip(),
            expires_at=0,  # Forces is_expired=True immediately
            granted_scopes=frozenset(),
            obtained_at=int(time.time()),
        )


def default_config_dir() -> Path:
    """Return the default config directory, honoring XDG_CONFIG_HOME."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "etsy-mcp"
    return Path.home() / ".config" / "etsy-mcp"


def default_token_path() -> Path:
    """Return the default tokens.json path."""
    override = os.environ.get("ETSY_TOKEN_STORE")
    if override:
        return Path(override).expanduser()
    return default_config_dir() / "tokens.json"


class EtsyAuth:
    """OAuth 2.0 + PKCE auth manager for Etsy API.

    Owns the token store and the refresh lifecycle. Clients call
    `get_access_token()` before every API request; this class handles
    refresh transparently.
    """

    def __init__(
        self,
        keystring: str,
        shared_secret: str | None = None,
        token_path: Path | None = None,
        *,
        redirect_uri: str = "http://localhost:3456/callback",
    ) -> None:
        if not keystring or not keystring.strip():
            raise EtsyAuthError("ETSY_KEYSTRING is required and must not be empty")
        self.keystring = keystring.strip()
        self.shared_secret = (shared_secret or "").strip() or None
        self.token_path = token_path or default_token_path()
        self.redirect_uri = redirect_uri
        self._tokens: Tokens | None = None
        self._initial_refresh_env: str | None = os.environ.get("ETSY_REFRESH_TOKEN")

    # -------------------------------------------------------------------------
    # Token loading and persistence
    # -------------------------------------------------------------------------

    def load_tokens(self) -> Tokens | None:
        """Load tokens from disk (or env var fallback). Returns None if unavailable."""
        # Env var fallback: if ETSY_REFRESH_TOKEN is set and we have no disk tokens,
        # construct an in-memory token state that will refresh on first use.
        if self._initial_refresh_env and not self.token_path.exists():
            logger.info("Loading refresh token from ETSY_REFRESH_TOKEN env var (headless mode)")
            self._tokens = Tokens.bootstrap_from_refresh_token(self._initial_refresh_env)
            return self._tokens

        if not self.token_path.exists():
            return None

        try:
            data = json.loads(self.token_path.read_text())
            self._tokens = Tokens.from_dict(data)
            return self._tokens
        except (json.JSONDecodeError, OSError, KeyError, ValueError) as exc:
            logger.error("Failed to load tokens from %s: %s", self.token_path, exc.__class__.__name__)
            raise EtsyAuthError(
                f"Token store at {self.token_path} is corrupt or unreadable. "
                f"Delete it and run `etsy-mcp auth login` to re-authenticate."
            ) from exc

    def save_tokens(self, tokens: Tokens) -> None:
        """Persist tokens atomically to disk with proper permissions.

        Uses write-to-temp + rename for atomicity. Survives crashes mid-write.
        """
        self.token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Ensure parent dir is 0700 even if it already existed.
        # Cycle 3 fix: log warning on chmod failure instead of bare pass —
        # silent permission drift on NFS / noexec mounts could leave the
        # token store world-readable with no operator visibility.
        try:
            self.token_path.parent.chmod(0o700)
        except OSError as exc:
            logger.warning(
                "Could not enforce 0700 mode on config dir %s: %s. "
                "Token store may be more permissive than intended.",
                self.token_path.parent,
                exc,
            )

        tmp_path = self.token_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(tokens.to_dict(), indent=2))
            tmp_path.chmod(0o600)
            os.replace(tmp_path, self.token_path)
            self._tokens = tokens
        except OSError as exc:
            # Clean up temp file on failure. Log the cleanup outcome at debug
            # level — Cycle 3 fix: don't silently swallow the inner OSError,
            # operators investigating a stale .tmp file deserve a breadcrumb.
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError as cleanup_exc:
                    logger.debug(
                        "Could not clean up temp token file %s after save failure: %s",
                        tmp_path,
                        cleanup_exc,
                    )
            raise EtsyAuthError(f"Failed to write token store at {self.token_path}") from exc

    # -------------------------------------------------------------------------
    # PKCE flow
    # -------------------------------------------------------------------------

    def build_authorization_url(
        self,
        scopes: tuple[str, ...] | list[str] = DEFAULT_SCOPES,
    ) -> tuple[str, str, str]:
        """Generate a PKCE-enabled authorization URL.

        Returns:
            (url, verifier, state) — caller must store verifier + state to
            verify the callback and exchange the code.
        """
        verifier, challenge = generate_pkce_pair()
        state = generate_state()

        # Build the query string via urllib.parse.urlencode for correct escaping
        # of keys AND values. The previous implementation used
        # httpx.QueryParams({k: v})[k] which returns unescaped values — scope
        # strings with spaces (e.g. "shops_r shops_w") landed raw in the URL
        # and produced malformed authorization requests. Caught in Cycle 1 review.
        params = {
            "response_type": "code",
            "client_id": self.keystring,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": CODE_CHALLENGE_METHOD,
        }
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        url = f"{ETSY_AUTH_URL}?{query}"
        return url, verifier, state

    async def exchange_code(self, code: str, verifier: str) -> Tokens:
        """Exchange an authorization code for access + refresh tokens.

        Called by the callback handler after the user consents in the browser.
        On success, persists tokens to disk and returns them.
        """
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.keystring,
            "redirect_uri": self.redirect_uri,
            "code": code,
            "code_verifier": verifier,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                ETSY_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            # Cycle 2 fix P1-A: wrap the JSON parse in try/except. A malformed
            # body with a JSON-shaped Content-Type header (Etsy proxy returning
            # an HTML 502 page or a truncated body) used to crash exchange_code
            # with a raw stack trace instead of a clean EtsyAuthError.
            body = _safe_json_body(response)
            error_desc = body.get("error_description") or body.get("error") or "(no description)"
            raise EtsyAuthError(
                f"Token exchange failed (HTTP {response.status_code}): {error_desc}",
                status=response.status_code,
            )

        # Same defense for the success path — a 200 with malformed JSON should
        # raise a clean EtsyAuthError, not a raw JSONDecodeError.
        try:
            response_body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise EtsyAuthError(
                "Token exchange returned 200 with malformed JSON body — refusing to parse"
            ) from exc

        tokens = self._parse_token_response(response_body)
        self.save_tokens(tokens)
        logger.info("Initial token exchange successful. Granted scopes: %s", tokens.granted_scopes)
        return tokens

    async def refresh(self, current: Tokens | None = None) -> Tokens:
        """Refresh the access token using the current refresh token.

        Etsy rotates refresh tokens on every refresh. This method performs
        the full rotation: exchange old refresh_token for new access_token +
        new refresh_token, then atomically write the new state to disk.

        File locking via _refresh_with_lock serializes concurrent refreshes
        across async tasks and (via fcntl) across concurrent MCP processes.
        """
        tokens = current or self._tokens or self.load_tokens()
        if tokens is None or not tokens.refresh_token:
            raise EtsyAuthError(
                "No refresh token available. Run `etsy-mcp auth login` to authenticate."
            )

        return await self._refresh_with_lock(tokens)

    async def _refresh_with_lock(self, tokens: Tokens) -> Tokens:
        """Acquire file lock and perform the refresh.

        Concurrency contract (Cycle 1 review fix):
        The authoritative state for a refresh is ALWAYS whatever is on disk
        AT THE MOMENT the lock is held, not whatever was passed in as an
        argument. The caller's `tokens` argument is a hint about the caller's
        expected previous state — but between the caller grabbing that
        reference and the lock being acquired, any number of other coroutines
        or sibling processes may have rotated the token pair.

        Sequence under the lock:
        1. Re-read tokens.json from disk (authoritative)
        2. If disk tokens exist AND are not expired AND access_token is
           non-empty → another refresher already did the work; return them
        3. Otherwise, use the DISK tokens (not the argument) as input to the
           refresh API call. Never send a stale refresh_token just because
           our caller held an outdated reference.
        4. If disk tokens are missing entirely, fall back to the caller's
           argument (the caller may be bootstrapping from an env var).

        This fix closes the race window identified in Cycle 1 review where
        a coroutine holding a stale pre-rotation reference would POST the
        already-rotated refresh_token to Etsy, get `invalid_grant`, and
        force the user to re-login despite a valid refresh token being on
        disk.
        """
        lock_path = self.token_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        with open(lock_path, "w") as lock_file:
            try:
                os.chmod(lock_path, 0o600)
            except OSError as exc:
                logger.warning(
                    "Could not set 0600 on lock file %s: %s", lock_path, exc
                )
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # Step 1: authoritative re-read from disk
                disk_tokens = self.load_tokens()

                # Step 2: another refresher may have already done the work
                if (
                    disk_tokens is not None
                    and disk_tokens.refresh_token
                    and disk_tokens.access_token
                    and not disk_tokens.is_expired
                ):
                    logger.debug(
                        "Another refresher already rotated tokens; adopting on-disk state"
                    )
                    return disk_tokens

                # Step 3: use disk tokens as input if available (authoritative),
                # otherwise fall back to the caller's argument (bootstrap case).
                refresh_input = disk_tokens if (
                    disk_tokens is not None and disk_tokens.refresh_token
                ) else tokens

                if refresh_input is None or not refresh_input.refresh_token:
                    raise EtsyAuthError(
                        "No refresh token available inside refresh lock. "
                        "Run `etsy-mcp auth login` to re-authenticate."
                    )

                return await self._refresh_unlocked(refresh_input)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    async def _refresh_unlocked(self, tokens: Tokens) -> Tokens:
        """Perform the refresh API call without lock management."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.keystring,
            "refresh_token": tokens.refresh_token,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    ETSY_TOKEN_URL,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                raise EtsyAuthError(f"Refresh request failed: {exc.__class__.__name__}") from exc

        if response.status_code != 200:
            # Cycle 2 fix P1-A: same defensive parse as exchange_code.
            body = _safe_json_body(response)
            error = body.get("error") or "unknown"
            error_desc = body.get("error_description") or "(no description)"

            if error == "invalid_grant":
                raise EtsyAuthError(
                    "Refresh token is no longer valid (invalid_grant). "
                    "Run `etsy-mcp auth login` to re-authenticate."
                )
            raise EtsyAuthError(
                f"Token refresh failed (HTTP {response.status_code}): {error_desc}",
                status=response.status_code,
            )

        try:
            response_body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise EtsyAuthError(
                "Token refresh returned 200 with malformed JSON body — refusing to parse"
            ) from exc

        new_tokens = self._parse_token_response(response_body)
        self.save_tokens(new_tokens)
        logger.info("Tokens refreshed successfully. New expiry: %d", new_tokens.expires_at)
        return new_tokens

    def _parse_token_response(self, data: dict[str, Any]) -> Tokens:
        """Convert an Etsy token endpoint response into a Tokens object.

        Cycle 1 review fix: validates that `expires_in` is a positive integer.
        A malicious or broken response with `expires_in=0` or negative would
        produce tokens that compute `is_expired=True` immediately AND have a
        fresh refresh_token — which would trigger an infinite refresh loop on
        the next request. Defend explicitly.
        """
        required = ("access_token", "refresh_token", "expires_in")
        missing = [k for k in required if k not in data]
        if missing:
            raise EtsyAuthError(f"Etsy token response missing required fields: {missing}")

        try:
            expires_in = int(data["expires_in"])
        except (TypeError, ValueError) as exc:
            raise EtsyAuthError(
                f"Etsy token response has non-integer expires_in: {data.get('expires_in')!r}"
            ) from exc

        if expires_in <= 0:
            raise EtsyAuthError(
                f"Etsy token response has non-positive expires_in: {expires_in}. "
                f"Refusing to construct Tokens that would loop forever."
            )

        if not data["access_token"] or not str(data["access_token"]).strip():
            raise EtsyAuthError("Etsy token response has empty access_token")
        if not data["refresh_token"] or not str(data["refresh_token"]).strip():
            raise EtsyAuthError("Etsy token response has empty refresh_token")

        now = int(time.time())
        scope = data.get("scope", "")
        granted_scopes = (
            frozenset(scope.split()) if isinstance(scope, str) else frozenset(scope)
        )

        return Tokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=now + expires_in,
            granted_scopes=granted_scopes,
            obtained_at=now,
        )

    # -------------------------------------------------------------------------
    # Public accessors
    # -------------------------------------------------------------------------

    async def get_access_token(self) -> str:
        """Return a valid access token, refreshing if necessary.

        This is the primary method clients call before every API request.
        Handles: loading from disk, detecting expiry, refreshing via lock,
        returning the current token.

        Raises EtsyAuthError if no tokens are available or refresh fails.
        """
        if self._tokens is None:
            self._tokens = self.load_tokens()

        if self._tokens is None:
            raise EtsyAuthError(
                "No tokens available. Run `etsy-mcp auth login` to authenticate, "
                "or set ETSY_REFRESH_TOKEN in the environment."
            )

        if self._tokens.is_expired:
            self._tokens = await self.refresh(self._tokens)

        return self._tokens.access_token

    def get_keystring(self) -> str:
        """Return the app keystring (client ID) for x-api-key header."""
        return self.keystring
