"""Unit tests for etsy_core.auth (OAuth 2.0 + PKCE + token persistence)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from etsy_core.auth import (
    DEFAULT_SCOPES,
    ETSY_TOKEN_URL,
    EtsyAuth,
    Tokens,
    default_config_dir,
    default_token_path,
)
from etsy_core.exceptions import EtsyAuthError


class TestDefaultPaths:
    def test_default_config_dir_with_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert default_config_dir() == tmp_path / "etsy-mcp"

    def test_default_config_dir_without_xdg(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert default_config_dir() == Path.home() / ".config" / "etsy-mcp"

    def test_default_token_path_with_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ETSY_TOKEN_STORE", str(tmp_path / "custom.json"))
        assert default_token_path() == tmp_path / "custom.json"

    def test_default_token_path_uses_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ETSY_TOKEN_STORE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert default_token_path() == tmp_path / "etsy-mcp" / "tokens.json"


class TestTokensDataclass:
    def test_to_dict_round_trip(self):
        original = Tokens(
            access_token="a",
            refresh_token="r",
            expires_at=1000,
            granted_scopes=frozenset({"x", "y"}),
            obtained_at=900,
        )
        restored = Tokens.from_dict(original.to_dict())
        assert restored == original

    def test_is_expired_true_when_past_lead(self):
        t = Tokens(access_token="a", refresh_token="r", expires_at=int(time.time()) - 10)
        assert t.is_expired is True

    def test_is_expired_false_when_well_in_future(self):
        t = Tokens(access_token="a", refresh_token="r", expires_at=int(time.time()) + 3600)
        assert t.is_expired is False

    def test_is_expired_true_within_lead_window(self):
        # REFRESH_LEAD_SECONDS is 60 — anything within 60s counts as expired
        t = Tokens(access_token="a", refresh_token="r", expires_at=int(time.time()) + 30)
        assert t.is_expired is True

    def test_empty_refresh_token_rejected_at_construction(self):
        """Cycle 1 fix SA-7 — Tokens enforces refresh_token invariant."""
        with pytest.raises(ValueError, match="refresh_token must be non-empty"):
            Tokens(access_token="a", refresh_token="", expires_at=1000)
        with pytest.raises(ValueError, match="refresh_token must be non-empty"):
            Tokens(access_token="a", refresh_token="   ", expires_at=1000)

    def test_frozen_dataclass_cannot_be_mutated(self):
        """Cycle 1 fix SA-7 — Tokens is immutable."""
        from dataclasses import FrozenInstanceError

        t = Tokens(access_token="a", refresh_token="r", expires_at=1000)
        with pytest.raises(FrozenInstanceError):
            t.access_token = "hijacked"  # type: ignore[misc]

    def test_granted_scopes_frozenset_cannot_be_appended(self):
        """Cycle 1 fix SA-7 — granted_scopes is immutable, no privilege escalation."""
        t = Tokens(
            access_token="a",
            refresh_token="r",
            expires_at=1000,
            granted_scopes=frozenset({"shops_r"}),
        )
        # frozenset has no add/append method — attempting to mutate raises
        assert isinstance(t.granted_scopes, frozenset)
        with pytest.raises(AttributeError):
            t.granted_scopes.add("shops_w")  # type: ignore[attr-defined]

    def test_bootstrap_from_refresh_token(self):
        """Cycle 1 fix SA-7 — explicit constructor for the env-var bootstrap case."""
        t = Tokens.bootstrap_from_refresh_token("env-refresh-token")
        assert t.refresh_token == "env-refresh-token"
        assert t.access_token == ""
        assert t.expires_at == 0
        assert t.is_expired is True
        assert t.granted_scopes == frozenset()

    def test_bootstrap_rejects_empty(self):
        with pytest.raises(ValueError, match="non-empty refresh_token"):
            Tokens.bootstrap_from_refresh_token("")


class TestEtsyAuthConstruction:
    def test_empty_keystring_raises(self, temp_config_dir):
        with pytest.raises(EtsyAuthError, match="ETSY_KEYSTRING is required"):
            EtsyAuth(keystring="")

    def test_whitespace_keystring_raises(self, temp_config_dir):
        with pytest.raises(EtsyAuthError, match="ETSY_KEYSTRING is required"):
            EtsyAuth(keystring="   ")

    def test_strips_keystring_whitespace(self, temp_config_dir):
        a = EtsyAuth(keystring="  abc  ")
        assert a.keystring == "abc"


class TestSaveAndLoadTokens:
    def test_save_creates_file_with_proper_perms(self, auth_factory, fake_tokens, temp_config_dir):
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        assert auth.token_path.exists()
        # Mode check is best-effort cross-platform
        mode = auth.token_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_load_returns_saved_tokens(self, auth_factory, fake_tokens):
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        # Fresh instance loads the same tokens
        auth2 = EtsyAuth(keystring="test-keystring", token_path=auth.token_path)
        loaded = auth2.load_tokens()
        assert loaded is not None
        assert loaded.access_token == fake_tokens.access_token

    def test_load_returns_none_when_missing(self, auth_factory):
        auth = auth_factory()
        assert auth.load_tokens() is None

    def test_load_corrupt_raises_auth_error(self, auth_factory):
        auth = auth_factory()
        auth.token_path.parent.mkdir(parents=True, exist_ok=True)
        auth.token_path.write_text("not json {{")
        with pytest.raises(EtsyAuthError, match="corrupt or unreadable"):
            auth.load_tokens()

    def test_load_missing_required_field_raises(self, auth_factory):
        auth = auth_factory()
        auth.token_path.parent.mkdir(parents=True, exist_ok=True)
        auth.token_path.write_text(json.dumps({"foo": "bar"}))
        with pytest.raises(EtsyAuthError):
            auth.load_tokens()

    def test_save_is_atomic(self, auth_factory, fake_tokens):
        # After a successful save, no .tmp file lingers
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        tmp_path = auth.token_path.with_suffix(".tmp")
        assert not tmp_path.exists()

    def test_save_atomic_crash_preserves_old(self, auth_factory, monkeypatch):
        """If os.replace fails mid-save, the previously-saved tokens must
        remain readable and the temp file must not linger."""
        auth = auth_factory()
        tokens_v1 = Tokens(
            access_token="v1-access",
            refresh_token="v1-refresh",
            expires_at=1_000_000,
            obtained_at=900_000,
        )
        tokens_v2 = Tokens(
            access_token="v2-access",
            refresh_token="v2-refresh",
            expires_at=2_000_000,
            obtained_at=1_900_000,
        )
        auth.save_tokens(tokens_v1)

        def _boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(EtsyAuthError, match="Failed to write token store"):
            auth.save_tokens(tokens_v2)

        # Reload fresh — must be v1, not v2
        monkeypatch.undo()  # allow os.replace to work again if needed (no-op here)
        fresh = EtsyAuth(keystring="test-keystring", token_path=auth.token_path)
        loaded = fresh.load_tokens()
        assert loaded is not None
        assert loaded.access_token == "v1-access"
        assert loaded.expires_at == 1_000_000
        # No stray temp file
        tmp_path = auth.token_path.with_suffix(".tmp")
        assert not tmp_path.exists()


class TestEnvFallback:
    def test_refresh_env_creates_in_memory_state(self, auth_factory, monkeypatch):
        monkeypatch.setenv("ETSY_REFRESH_TOKEN", "env-refresh-token")
        # Re-instantiate so the env var is picked up at __init__
        auth = EtsyAuth(
            keystring="test", token_path=auth_factory().token_path
        )
        loaded = auth.load_tokens()
        assert loaded is not None
        assert loaded.refresh_token == "env-refresh-token"
        assert loaded.is_expired is True


class TestBuildAuthorizationUrl:
    def test_includes_all_pkce_params(self, auth_factory):
        auth = auth_factory()
        url, verifier, state = auth.build_authorization_url()
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert f"state={state}" in url
        assert "response_type=code" in url
        assert verifier  # non-empty
        assert state  # non-empty

    def test_includes_default_scopes(self, auth_factory):
        auth = auth_factory()
        url, _, _ = auth.build_authorization_url()
        for scope in DEFAULT_SCOPES:
            assert scope in url

    def test_includes_keystring_as_client_id(self, auth_factory):
        auth = auth_factory("my-key-1234")
        url, _, _ = auth.build_authorization_url()
        assert "client_id=my-key-1234" in url

    def test_custom_scopes_passed_through(self, auth_factory):
        auth = auth_factory()
        url, _, _ = auth.build_authorization_url(scopes=("shops_r",))
        assert "shops_r" in url
        assert "listings_r" not in url


class TestExchangeCode:
    """Tests for EtsyAuth.exchange_code (authorization_code grant)."""

    @pytest.mark.asyncio
    async def test_exchange_code_success_persists_tokens(
        self, auth_factory, mock_httpx, token_endpoint_success
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_endpoint_success)
        )
        tokens = await auth.exchange_code("auth-code-abc", "verifier-xyz")
        assert tokens.access_token == token_endpoint_success["access_token"]
        assert tokens.refresh_token == token_endpoint_success["refresh_token"]
        on_disk = json.loads(auth.token_path.read_text())
        assert on_disk["access_token"] == token_endpoint_success["access_token"]
        assert on_disk["refresh_token"] == token_endpoint_success["refresh_token"]

    @pytest.mark.asyncio
    async def test_exchange_code_400_invalid_grant(self, auth_factory, mock_httpx):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "code already used"},
            )
        )
        with pytest.raises(EtsyAuthError, match="code already used"):
            await auth.exchange_code("used-code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_400_invalid_request(self, auth_factory, mock_httpx):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                400,
                json={"error": "invalid_request", "error_description": "missing code_verifier"},
            )
        )
        with pytest.raises(EtsyAuthError, match="missing code_verifier"):
            await auth.exchange_code("code", "")

    @pytest.mark.asyncio
    async def test_exchange_code_500_server_error(self, auth_factory, mock_httpx):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(500, json={"error": "internal"})
        )
        with pytest.raises(EtsyAuthError, match="Token exchange failed"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_response_missing_refresh_token(
        self, auth_factory, mock_httpx
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        )
        with pytest.raises(EtsyAuthError, match="refresh_token"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_response_with_zero_expires_in(
        self, auth_factory, mock_httpx
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "a", "refresh_token": "r", "expires_in": 0},
            )
        )
        with pytest.raises(EtsyAuthError, match="non-positive expires_in"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_response_with_negative_expires_in(
        self, auth_factory, mock_httpx
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "a", "refresh_token": "r", "expires_in": -1},
            )
        )
        with pytest.raises(EtsyAuthError, match="non-positive expires_in"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_response_with_non_int_expires_in(
        self, auth_factory, mock_httpx
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "a",
                    "refresh_token": "r",
                    "expires_in": "not a number",
                },
            )
        )
        with pytest.raises(EtsyAuthError, match="non-integer expires_in"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_response_with_empty_access_token(
        self, auth_factory, mock_httpx
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "", "refresh_token": "r", "expires_in": 3600},
            )
        )
        with pytest.raises(EtsyAuthError, match="empty access_token"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_response_with_whitespace_access_token(
        self, auth_factory, mock_httpx
    ):
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "   ", "refresh_token": "r", "expires_in": 3600},
            )
        )
        with pytest.raises(EtsyAuthError, match="empty access_token"):
            await auth.exchange_code("code", "verifier")

    @pytest.mark.asyncio
    async def test_exchange_code_caplog_does_not_leak_secrets(
        self, auth_factory, mock_httpx, token_endpoint_success, caplog
    ):
        import logging

        caplog.set_level(logging.DEBUG)
        auth = auth_factory()
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_endpoint_success)
        )
        await auth.exchange_code("my-secret-code", "my-secret-verifier")
        for record in caplog.records:
            msg = record.getMessage()
            assert "my-secret-code" not in msg
            assert "my-secret-verifier" not in msg
            assert token_endpoint_success["access_token"] not in msg
            assert token_endpoint_success["refresh_token"] not in msg


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_rotates_tokens(self, auth_factory, expired_tokens, mock_httpx, token_endpoint_success):
        """Cycle 1 fix CONV-3 — refresh uses on-disk state as authoritative.

        The test now seeds the disk with EXPIRED tokens (not fresh ones),
        because the rewritten _refresh_with_lock short-circuits when the
        on-disk state is already valid. Calling refresh on already-fresh
        tokens is a no-op by design (no wasted API call).
        """
        auth = auth_factory()
        auth.save_tokens(expired_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(return_value=httpx.Response(200, json=token_endpoint_success))

        new_tokens = await auth.refresh(expired_tokens)
        assert new_tokens.access_token == token_endpoint_success["access_token"]
        assert new_tokens.refresh_token == token_endpoint_success["refresh_token"]
        # Fresh instance reads the rotated token from disk
        on_disk = json.loads(auth.token_path.read_text())
        assert on_disk["refresh_token"] == token_endpoint_success["refresh_token"]

    @pytest.mark.asyncio
    async def test_refresh_short_circuits_when_disk_is_fresh(
        self, auth_factory, fake_tokens, mock_httpx
    ):
        """Cycle 1 fix CONV-3 — calling refresh with already-fresh disk
        tokens does NOT hit the network; it just adopts the disk state.
        """
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        # Mock the endpoint but assert it is NEVER called
        token_route = mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "should-not-fire"})
        )

        result = await auth.refresh(fake_tokens)
        assert result.access_token == fake_tokens.access_token
        assert token_route.call_count == 0

    @pytest.mark.asyncio
    async def test_refresh_invalid_grant_is_terminal(self, auth_factory, expired_tokens, mock_httpx):
        auth = auth_factory()
        auth.save_tokens(expired_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token revoked"})
        )
        with pytest.raises(EtsyAuthError, match="invalid_grant"):
            await auth.refresh(expired_tokens)

    @pytest.mark.asyncio
    async def test_refresh_with_no_tokens_at_all_raises(self, auth_factory):
        """Cycle 1 fix SA-7 — Tokens with empty refresh_token can no longer
        be constructed. Test the equivalent state by passing None and having
        no on-disk tokens or env var fallback.
        """
        auth = auth_factory()
        with pytest.raises(EtsyAuthError, match="No refresh token"):
            await auth.refresh(None)

    @pytest.mark.asyncio
    async def test_refresh_other_error_raises_auth_error(self, auth_factory, expired_tokens, mock_httpx):
        auth = auth_factory()
        auth.save_tokens(expired_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(500, json={"error_description": "internal"})
        )
        with pytest.raises(EtsyAuthError, match="Token refresh failed"):
            await auth.refresh(expired_tokens)

    @pytest.mark.asyncio
    async def test_refresh_with_stale_arg_uses_disk_state(
        self, auth_factory, mock_httpx, token_endpoint_success
    ):
        """CONV-3: a stale in-memory Tokens arg must NOT leak its refresh_token
        into the token endpoint POST. The on-disk refresh_token is authoritative.
        """
        import urllib.parse

        auth = auth_factory()
        # Seed disk with an expired tokens whose refresh_token is DISK_RT
        disk_expired = Tokens(
            access_token="disk-access",
            refresh_token="DISK_RT",
            expires_at=int(time.time()) - 60,
            obtained_at=int(time.time()) - 3700,
        )
        auth.save_tokens(disk_expired)

        # Stale in-memory reference held by some coroutine — older rotation
        stale_tokens = Tokens(
            access_token="stale-access",
            refresh_token="STALE_RT",
            expires_at=0,
            obtained_at=0,
        )

        route = mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(200, json=token_endpoint_success)
        )

        await auth.refresh(stale_tokens)

        # Inspect the actual form body sent
        assert route.call_count == 1
        request = route.calls[0].request
        body = request.content.decode("utf-8")
        parsed = urllib.parse.parse_qs(body)
        assert parsed["refresh_token"] == ["DISK_RT"]
        assert "STALE_RT" not in body

    @pytest.mark.asyncio
    async def test_refresh_does_not_leak_secrets_in_logs(
        self, auth_factory, fake_tokens, mock_httpx, token_endpoint_success, caplog
    ):
        import logging

        caplog.set_level(logging.DEBUG)
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(return_value=httpx.Response(200, json=token_endpoint_success))
        await auth.refresh(fake_tokens)
        for record in caplog.records:
            assert token_endpoint_success["access_token"] not in record.getMessage()
            assert token_endpoint_success["refresh_token"] not in record.getMessage()


class TestGetAccessToken:
    @pytest.mark.asyncio
    async def test_returns_current_when_not_expired(self, auth_factory, fake_tokens):
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        token = await auth.get_access_token()
        assert token == fake_tokens.access_token

    @pytest.mark.asyncio
    async def test_refreshes_when_expired(self, auth_factory, expired_tokens, mock_httpx, token_endpoint_success):
        auth = auth_factory()
        auth.save_tokens(expired_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(return_value=httpx.Response(200, json=token_endpoint_success))
        token = await auth.get_access_token()
        assert token == token_endpoint_success["access_token"]

    @pytest.mark.asyncio
    async def test_raises_when_no_tokens(self, auth_factory):
        auth = auth_factory()
        with pytest.raises(EtsyAuthError, match="No tokens available"):
            await auth.get_access_token()


class TestRefreshLockSerialization:
    @pytest.mark.asyncio
    async def test_concurrent_refresh_serializes(
        self, auth_factory, expired_tokens, mock_httpx, token_endpoint_success
    ):
        """Two concurrent refreshes must serialize via the file lock — the second
        call should observe the freshly-rotated token instead of issuing a duplicate
        refresh that would invalidate the first rotation."""
        auth = auth_factory()
        auth.save_tokens(expired_tokens)

        call_count = {"n": 0}

        def _handler(request):
            call_count["n"] += 1
            return httpx.Response(200, json=token_endpoint_success)

        mock_httpx.post(ETSY_TOKEN_URL).mock(side_effect=_handler)

        # Fire two concurrent refreshes
        results = await asyncio.gather(
            auth.refresh(expired_tokens),
            auth.refresh(expired_tokens),
        )
        # Both should return valid tokens
        assert all(r.access_token == token_endpoint_success["access_token"] for r in results)
        # The lock should have prevented a duplicate refresh — exactly one network call
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Cycle 3 silent-failure regression guards
# ---------------------------------------------------------------------------


class TestSaveTokensChmodWarning:
    """Regression guard for Cycle 3 fix: save_tokens parent-dir chmod failure
    must log a warning, not silently pass. NFS / noexec mounts that refuse
    chmod could leave the token store more permissive than 0700 with no
    operator visibility."""

    def test_chmod_failure_logs_warning(self, auth_factory, fake_tokens, monkeypatch, caplog):
        import logging
        from pathlib import Path

        auth = auth_factory()
        # Force the parent-dir chmod call to raise OSError
        original_chmod = Path.chmod

        def fake_chmod(self, mode):
            if self == auth.token_path.parent:
                raise OSError("Operation not permitted (NFS mount)")
            return original_chmod(self, mode)

        monkeypatch.setattr(Path, "chmod", fake_chmod)
        caplog.set_level(logging.WARNING, logger="etsy_core.auth")

        # save_tokens must succeed despite the chmod failure (it's not critical)
        # but it MUST log a warning so the operator sees the permission drift
        auth.save_tokens(fake_tokens)

        warning_messages = [
            record.message for record in caplog.records if record.levelno >= logging.WARNING
        ]
        assert any(
            "Could not enforce 0700" in msg for msg in warning_messages
        ), f"Expected 'Could not enforce 0700' warning, got: {warning_messages}"
