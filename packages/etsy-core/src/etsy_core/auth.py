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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from etsy_core.exceptions import EtsyAuthError
from etsy_core.pkce import CODE_CHALLENGE_METHOD, generate_pkce_pair, generate_state

logger = logging.getLogger(__name__)

ETSY_AUTH_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

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


@dataclass
class Tokens:
    """OAuth token state.

    Attributes:
        access_token: Bearer token for API requests
        refresh_token: Used to mint new access tokens (rotates on each refresh)
        expires_at: Unix timestamp when access_token expires
        granted_scopes: Scopes actually granted by Etsy (may differ from requested)
        obtained_at: Unix timestamp when tokens were obtained
    """

    access_token: str
    refresh_token: str
    expires_at: int
    granted_scopes: list[str] = field(default_factory=list)
    obtained_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def is_expired(self) -> bool:
        """True if the access token is within REFRESH_LEAD_SECONDS of expiring."""
        return time.time() >= (self.expires_at - REFRESH_LEAD_SECONDS)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tokens:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data["expires_at"]),
            granted_scopes=list(data.get("granted_scopes", [])),
            obtained_at=int(data.get("obtained_at", time.time())),
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
            self._tokens = Tokens(
                access_token="",
                refresh_token=self._initial_refresh_env,
                expires_at=0,  # Force immediate refresh
                granted_scopes=[],
                obtained_at=int(time.time()),
            )
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
        # Ensure parent dir is 0700 even if it already existed
        try:
            self.token_path.parent.chmod(0o700)
        except OSError:
            pass  # Not critical if chmod fails on existing dir

        tmp_path = self.token_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(tokens.to_dict(), indent=2))
            tmp_path.chmod(0o600)
            os.replace(tmp_path, self.token_path)
            self._tokens = tokens
        except OSError as exc:
            # Clean up temp file on failure
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
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

        scope_str = " ".join(scopes)
        params = {
            "response_type": "code",
            "client_id": self.keystring,
            "redirect_uri": self.redirect_uri,
            "scope": scope_str,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": CODE_CHALLENGE_METHOD,
        }
        query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
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
            # Don't leak the code or verifier — just the status and safe error description
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            error_desc = body.get("error_description") or body.get("error") or "(no description)"
            raise EtsyAuthError(
                f"Token exchange failed (HTTP {response.status_code}): {error_desc}",
                status=response.status_code,
            )

        tokens = self._parse_token_response(response.json())
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
        """Acquire file lock and perform the refresh, allowing another process
        to have already done it in the interim.

        The post-lock re-check only short-circuits if the on-disk refresh_token
        is DIFFERENT from the one we were asked to refresh — that indicates
        another process already rotated the token pair while we were waiting
        for the lock. If the on-disk tokens still match what we have, we
        perform the refresh ourselves.
        """
        lock_path = self.token_path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        with open(lock_path, "w") as lock_file:
            try:
                os.chmod(lock_path, 0o600)
            except OSError:
                pass
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # Re-check: another process may have refreshed while we waited.
                # Short-circuit ONLY if the on-disk refresh_token is different
                # (indicating a successful rotation by another process) AND the
                # on-disk access token is still valid.
                fresh = self.load_tokens()
                if (
                    fresh is not None
                    and fresh.refresh_token
                    and fresh.refresh_token != tokens.refresh_token
                    and not fresh.is_expired
                    and fresh.access_token
                ):
                    logger.debug("Another process already refreshed; using their tokens")
                    return fresh

                # Do the actual refresh
                return await self._refresh_unlocked(tokens)
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
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
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

        new_tokens = self._parse_token_response(response.json())
        self.save_tokens(new_tokens)
        logger.info("Tokens refreshed successfully. New expiry: %d", new_tokens.expires_at)
        return new_tokens

    def _parse_token_response(self, data: dict[str, Any]) -> Tokens:
        """Convert an Etsy token endpoint response into a Tokens object."""
        required = ("access_token", "refresh_token", "expires_in")
        missing = [k for k in required if k not in data]
        if missing:
            raise EtsyAuthError(f"Etsy token response missing required fields: {missing}")

        now = int(time.time())
        scope = data.get("scope", "")
        granted_scopes = scope.split() if isinstance(scope, str) else list(scope)

        return Tokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=now + int(data["expires_in"]),
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
