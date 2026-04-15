"""Unit tests for etsy_core.auth (OAuth 2.0 + PKCE + token persistence)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest
import respx

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
            granted_scopes=["x", "y"],
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


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_rotates_tokens(self, auth_factory, fake_tokens, mock_httpx, token_endpoint_success):
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(return_value=httpx.Response(200, json=token_endpoint_success))

        new_tokens = await auth.refresh(fake_tokens)
        assert new_tokens.access_token == token_endpoint_success["access_token"]
        assert new_tokens.refresh_token == token_endpoint_success["refresh_token"]
        # Fresh instance reads the rotated token from disk
        on_disk = json.loads(auth.token_path.read_text())
        assert on_disk["refresh_token"] == token_endpoint_success["refresh_token"]

    @pytest.mark.asyncio
    async def test_refresh_invalid_grant_is_terminal(self, auth_factory, fake_tokens, mock_httpx):
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token revoked"})
        )
        with pytest.raises(EtsyAuthError, match="invalid_grant"):
            await auth.refresh(fake_tokens)

    @pytest.mark.asyncio
    async def test_refresh_with_no_refresh_token_raises(self, auth_factory):
        auth = auth_factory()
        empty = Tokens(access_token="x", refresh_token="", expires_at=0)
        with pytest.raises(EtsyAuthError, match="No refresh token"):
            await auth.refresh(empty)

    @pytest.mark.asyncio
    async def test_refresh_other_error_raises_auth_error(self, auth_factory, fake_tokens, mock_httpx):
        auth = auth_factory()
        auth.save_tokens(fake_tokens)
        mock_httpx.post(ETSY_TOKEN_URL).mock(
            return_value=httpx.Response(500, json={"error_description": "internal"})
        )
        with pytest.raises(EtsyAuthError, match="Token refresh failed"):
            await auth.refresh(fake_tokens)

    @pytest.mark.asyncio
    async def test_refresh_does_not_leak_secrets_in_logs(self, auth_factory, fake_tokens, mock_httpx, token_endpoint_success, caplog):
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
    async def test_concurrent_refresh_serializes(self, auth_factory, expired_tokens, mock_httpx, token_endpoint_success):
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
