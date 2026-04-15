"""Tests for etsy_mcp.cli.auth — callback server hardening.

These tests avoid binding a real HTTP server. They drive _CallbackHandler
through a light fake that reproduces BaseHTTPRequestHandler's expected
wfile/rfile surface, and use unittest.mock to assert bind behavior.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from etsy_core.exceptions import EtsyAuthError
from etsy_mcp.cli import auth as auth_mod

# ---------------------------------------------------------------------------
# Helpers — a fake request/client wrapper for BaseHTTPRequestHandler
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Stand-in for a socket.socket that BaseHTTPRequestHandler can use.

    BaseHTTPRequestHandler/StreamRequestHandler reads from self.rfile and
    writes to self.wfile (both obtained via request.makefile). However the
    default wfile is a socketserver._SocketWriter that calls
    self._sock.sendall, so we must also expose sendall on this stub.
    """

    def __init__(self, raw_request: bytes) -> None:
        self._rfile = io.BytesIO(raw_request)
        self._wbuf = bytearray()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        if "r" in mode:
            return self._rfile
        # Return a wrapper BytesIO that also records to _wbuf (since the
        # default writer is _SocketWriter which forwards to sendall — we
        # just give it a normal BytesIO and also route sendall there).
        return io.BytesIO()

    def sendall(self, data: bytes) -> None:
        self._wbuf.extend(data)


def _drive_handler(path: str, state: dict[str, Any]) -> bytes:
    """Instantiate _CallbackHandler against a fake request. Returns sent bytes."""
    raw = f"GET {path} HTTP/1.0\r\n\r\n".encode()
    req = _FakeRequest(raw)
    # BaseHTTPRequestHandler calls self.setup/handle/finish during __init__;
    # we pass a minimal client address and server stub.
    server_stub = MagicMock()
    auth_mod._CallbackHandler(
        req, ("127.0.0.1", 12345), server_stub, state_holder=state
    )
    return bytes(req._wbuf)


# ---------------------------------------------------------------------------
# Handler tests — instance-scoped state, CSRF validation, 404 isolation
# ---------------------------------------------------------------------------


def test_handler_writes_to_instance_state_not_class() -> None:
    """Regression for SA-5: state must land on the passed dict, not class attrs."""
    state: dict[str, Any] = {"code": None, "state": None, "error": None}
    _drive_handler("/callback?code=abc&state=xyz", state)
    assert state["code"] == "abc"
    assert state["state"] == "xyz"
    assert state["error"] is None
    # Nothing should be bolted onto the class itself.
    assert not hasattr(auth_mod._CallbackHandler, "received_code")
    assert not hasattr(auth_mod._CallbackHandler, "received_state")
    assert not hasattr(auth_mod._CallbackHandler, "received_error")


def test_handler_state_isolated_across_sequential_calls() -> None:
    """Two handler invocations with separate state dicts must not leak values."""
    state_a: dict[str, Any] = {"code": None, "state": None, "error": None}
    _drive_handler("/callback?code=first_code&state=first_state", state_a)

    state_b: dict[str, Any] = {"code": None, "state": None, "error": None}
    # Second call: only an error, no code
    _drive_handler("/callback?error=access_denied", state_b)

    assert state_a["code"] == "first_code"
    assert state_a["state"] == "first_state"
    assert state_a["error"] is None

    assert state_b["code"] is None
    assert state_b["state"] is None
    assert state_b["error"] == "access_denied"


def test_handler_404_on_wrong_path_does_not_record_code() -> None:
    state: dict[str, Any] = {"code": None, "state": None, "error": None}
    sent = _drive_handler("/wrong?code=SHOULD_NOT_RECORD&state=nope", state)
    # State untouched
    assert state["code"] is None
    assert state["state"] is None
    assert state["error"] is None
    # Response actually sent a 404
    assert b"404" in sent


def test_handler_records_error_param() -> None:
    state: dict[str, Any] = {"code": None, "state": None, "error": None}
    _drive_handler("/callback?error=access_denied", state)
    assert state["error"] == "access_denied"
    assert state["code"] is None


def test_handler_success_response_body() -> None:
    state: dict[str, Any] = {"code": None, "state": None, "error": None}
    sent = _drive_handler("/callback?code=abc&state=xyz", state)
    assert b"200" in sent
    assert b"Authorization successful" in sent


# ---------------------------------------------------------------------------
# _run_callback_server_until_received — bind + state surface
# ---------------------------------------------------------------------------


def test_bind_failure_surfaces_etsy_auth_error() -> None:
    """OSError during HTTPServer construction must become a clear EtsyAuthError."""
    with patch.object(
        auth_mod.http.server,
        "HTTPServer",
        side_effect=OSError(98, "Address already in use"),
    ):
        with pytest.raises(EtsyAuthError) as excinfo:
            auth_mod._run_callback_server_until_received(timeout_seconds=0.1)
    msg = excinfo.value.message
    assert "127.0.0.1" in msg
    assert "3456" in msg
    assert "already" in msg.lower() or "in use" in msg.lower()


def test_callback_host_is_ipv4_loopback() -> None:
    """Regression: CALLBACK_HOST must be 127.0.0.1, not 'localhost'."""
    assert auth_mod.CALLBACK_HOST == "127.0.0.1"


def test_run_callback_server_yields_state_when_code_seeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a completed callback by seeding state through a fake server."""

    class _FakeHTTPServer:
        timeout = 1.0
        _state_ref: dict[str, Any] | None = None

        def __init__(self, addr: tuple[str, int], factory: Any) -> None:
            # Call the factory with dummy args to capture the state_holder
            # via a harmless path: the real factory forwards to _CallbackHandler
            # which we also monkeypatch to just store state_holder.
            factory()

        def handle_request(self) -> None:
            if _FakeHTTPServer._state_ref is not None:
                _FakeHTTPServer._state_ref["code"] = "seeded_code"
                _FakeHTTPServer._state_ref["state"] = "seeded_state"

    class _FakeHandler:
        def __init__(self, *args: Any, state_holder: dict[str, Any], **kwargs: Any) -> None:
            _FakeHTTPServer._state_ref = state_holder

    monkeypatch.setattr(auth_mod.http.server, "HTTPServer", _FakeHTTPServer)
    monkeypatch.setattr(auth_mod, "_CallbackHandler", _FakeHandler)

    result = auth_mod._run_callback_server_until_received(timeout_seconds=2.0)
    assert result["code"] == "seeded_code"
    assert result["state"] == "seeded_state"
    assert result["error"] is None


# ---------------------------------------------------------------------------
# _login — CSRF state validation uses the returned dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_csrf_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the callback returns a state that doesn't match, login must abort."""
    monkeypatch.setenv("ETSY_KEYSTRING", "k")
    monkeypatch.setenv("ETSY_SHARED_SECRET", "s")

    fake_auth = MagicMock()
    fake_auth.build_authorization_url.return_value = (
        "https://etsy.example/auth",
        "verifier",
        "expected_state",
    )
    monkeypatch.setattr(auth_mod, "EtsyAuth", lambda **kwargs: fake_auth)
    monkeypatch.setattr(auth_mod.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(
        auth_mod,
        "_run_callback_server_until_received",
        lambda timeout_seconds=300: {
            "code": "abc",
            "state": "WRONG_STATE",
            "error": None,
        },
    )

    with pytest.raises(EtsyAuthError, match="CSRF"):
        await auth_mod._login(scopes=("shops_r",))


@pytest.mark.asyncio
async def test_login_missing_code_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETSY_KEYSTRING", "k")
    monkeypatch.setenv("ETSY_SHARED_SECRET", "s")

    fake_auth = MagicMock()
    fake_auth.build_authorization_url.return_value = (
        "https://etsy.example/auth",
        "verifier",
        "the_state",
    )
    monkeypatch.setattr(auth_mod, "EtsyAuth", lambda **kwargs: fake_auth)
    monkeypatch.setattr(auth_mod.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(
        auth_mod,
        "_run_callback_server_until_received",
        lambda timeout_seconds=300: {
            "code": None,
            "state": "the_state",
            "error": None,
        },
    )

    with pytest.raises(EtsyAuthError, match="No authorization code"):
        await auth_mod._login(scopes=("shops_r",))
