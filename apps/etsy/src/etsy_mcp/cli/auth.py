"""`etsy-mcp auth` CLI subcommand.

Commands:
- `login`: Interactive OAuth PKCE bootstrap — opens browser, catches callback,
           exchanges code, persists tokens to ~/.config/etsy-mcp/tokens.json
- `info`: Display current token state with F3 redaction
- `logout`: Delete stored tokens

Implementation notes:
- Local callback server runs on localhost:3456
- Single-use handler (accepts one callback, then shuts down)
- State parameter validated to prevent CSRF
- Tokens persisted atomically via EtsyAuth.save_tokens
- Default scope profile: full seller (see etsy_core.auth.DEFAULT_SCOPES)
"""

from __future__ import annotations

import asyncio
import http.server
import logging
import os
import sys
import threading
import urllib.parse
import webbrowser
from typing import Any

from etsy_core.auth import DEFAULT_SCOPES, EtsyAuth, default_config_dir, default_token_path
from etsy_core.exceptions import EtsyAuthError

logger = logging.getLogger(__name__)

# Bind explicitly to 127.0.0.1 — not "localhost", which may resolve to ::1
# on some systems and silently succeed while the browser hits 127.0.0.1,
# or vice versa. Using an explicit IPv4 literal eliminates that ambiguity
# and also avoids accidentally binding to a public interface.
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 3456
CALLBACK_PATH = "/callback"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot HTTP handler that captures the OAuth callback.

    Received values are written into a per-call state_holder dict passed
    by the owning server loop. Instance-scoped storage prevents state from
    leaking across sequential login attempts in the same process.
    """

    def __init__(self, *args: Any, state_holder: dict[str, Any], **kwargs: Any) -> None:
        # state_holder must be set BEFORE super().__init__, because
        # BaseHTTPRequestHandler.__init__ immediately handles the request
        # and will call do_GET() from within super().__init__.
        self.state_holder = state_holder
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler convention
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = urllib.parse.parse_qs(parsed.query)
        error = params.get("error", [None])[0]
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        self.state_holder["error"] = error
        self.state_holder["code"] = code
        self.state_holder["state"] = state

        if error:
            body = f"Authorization failed: {error}. You can close this window.".encode()
        elif code:
            body = (
                b"<html><body><h1>Authorization successful</h1>"
                b"<p>You can close this window and return to your terminal.</p>"
                b"</body></html>"
            )
        else:
            body = b"Missing code or error parameter. You can close this window."

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silence the default stderr logging
        pass


def _run_callback_server_until_received(
    timeout_seconds: float = 300,
) -> dict[str, Any]:
    """Start the callback server in a thread and wait for one request.

    Returns a dict with keys 'code', 'state', 'error'. Values are None until
    the callback is received. Bind failure is a hard error (security signal) —
    we refuse to fall back to a different port silently.
    """
    state: dict[str, Any] = {"code": None, "state": None, "error": None}

    def handler_factory(*args: Any, **kwargs: Any) -> _CallbackHandler:
        return _CallbackHandler(*args, state_holder=state, **kwargs)

    try:
        server = http.server.HTTPServer(
            (CALLBACK_HOST, CALLBACK_PORT), handler_factory
        )
    except OSError as exc:
        raise EtsyAuthError(
            f"Cannot bind OAuth callback server on {CALLBACK_HOST}:{CALLBACK_PORT}: "
            f"{exc}. This usually means another etsy-mcp auth login is already "
            f"running, or port {CALLBACK_PORT} is in use by another process."
        ) from exc

    server.timeout = 1.0

    def serve() -> None:
        while state["code"] is None and state["error"] is None:
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        raise EtsyAuthError(f"OAuth callback timed out after {timeout_seconds}s")

    return state


def _require_credentials() -> tuple[str, str]:
    """Load ETSY_KEYSTRING + ETSY_SHARED_SECRET from env."""
    keystring = os.environ.get("ETSY_KEYSTRING")
    shared_secret = os.environ.get("ETSY_SHARED_SECRET")
    if not keystring:
        raise EtsyAuthError(
            "ETSY_KEYSTRING env var is not set. "
            "Register an app at https://www.etsy.com/developers/your-apps "
            "and export ETSY_KEYSTRING=<your_keystring>."
        )
    if not shared_secret:
        raise EtsyAuthError(
            "ETSY_SHARED_SECRET env var is not set. "
            "Export ETSY_SHARED_SECRET=<your_shared_secret>."
        )
    return keystring, shared_secret


async def _login(scopes: tuple[str, ...]) -> None:
    """Execute the OAuth PKCE bootstrap flow."""
    keystring, shared_secret = _require_credentials()
    auth = EtsyAuth(keystring=keystring, shared_secret=shared_secret)

    url, verifier, state = auth.build_authorization_url(scopes=scopes)
    print("Opening browser for Etsy authorization…", file=sys.stderr)
    print(f"If your browser doesn't open, visit: {url}", file=sys.stderr)
    webbrowser.open(url)

    try:
        callback_state = _run_callback_server_until_received(timeout_seconds=300)
    except EtsyAuthError:
        raise
    except Exception as exc:
        raise EtsyAuthError(f"Failed to capture OAuth callback: {exc}") from exc

    if callback_state["error"]:
        raise EtsyAuthError(f"Authorization rejected: {callback_state['error']}")

    if callback_state["state"] != state:
        raise EtsyAuthError("State parameter mismatch — possible CSRF attempt. Aborting.")

    code = callback_state["code"]
    if not code:
        raise EtsyAuthError("No authorization code received in callback.")

    tokens = await auth.exchange_code(code, verifier)
    print(f"\nAuthorization successful. Tokens stored at: {auth.token_path}", file=sys.stderr)
    print(f"Granted scopes: {', '.join(tokens.granted_scopes)}", file=sys.stderr)
    print(f"Token expires in: ~{(tokens.expires_at - int(__import__('time').time())) // 60} minutes", file=sys.stderr)


def _info() -> None:
    """Display current token state with F3 redaction."""
    path = default_token_path()
    if not path.exists():
        print(f"No tokens found at {path}", file=sys.stderr)
        print("Run `etsy-mcp auth login` to authenticate.", file=sys.stderr)
        sys.exit(1)

    import json
    import time

    data = json.loads(path.read_text())
    expires_at = int(data.get("expires_at", 0))
    now = int(time.time())
    remaining = max(0, expires_at - now)

    print(f"Token store: {path}")
    print("Access token: [REDACTED]")
    print("Refresh token: [REDACTED]")
    print(f"Expires at: {expires_at} ({remaining}s from now)")
    print(f"Granted scopes: {', '.join(data.get('granted_scopes', []))}")
    print(f"Obtained at: {data.get('obtained_at', 'unknown')}")


def _logout() -> None:
    """Delete stored tokens and related state."""
    paths = [
        default_token_path(),
        default_config_dir() / "tokens.lock",
        default_config_dir() / "daily_counter.json",
    ]
    deleted = 0
    for path in paths:
        if path.exists():
            try:
                path.unlink()
                deleted += 1
                print(f"Deleted {path}", file=sys.stderr)
            except OSError as exc:
                print(f"Failed to delete {path}: {exc}", file=sys.stderr)
    if deleted == 0:
        print("No tokens to delete.", file=sys.stderr)


def auth_cli(args: list[str]) -> None:
    """Entry point for `etsy-mcp auth` subcommands."""
    if not args:
        print("Usage: etsy-mcp auth <login|info|logout> [--scope <scopes>]", file=sys.stderr)
        sys.exit(1)

    cmd = args[0]

    if cmd == "login":
        scopes: tuple[str, ...] = DEFAULT_SCOPES
        # Parse --scope flag (comma or space separated)
        if len(args) > 1 and args[1] == "--scope" and len(args) > 2:
            scope_arg = args[2]
            scopes = tuple(s.strip() for s in scope_arg.replace(",", " ").split() if s.strip())
        try:
            asyncio.run(_login(scopes))
        except EtsyAuthError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            sys.exit(1)
        return

    if cmd == "info":
        _info()
        return

    if cmd == "logout":
        _logout()
        return

    print(f"Unknown auth command: {cmd}", file=sys.stderr)
    print("Usage: etsy-mcp auth <login|info|logout>", file=sys.stderr)
    sys.exit(1)
