"""Shared pytest fixtures for etsy-core unit tests.

Provides:
- temp_config_dir: isolated XDG_CONFIG_HOME under tmp_path
- mock_httpx: respx router for stubbing all httpx calls
- deterministic_pkce: monkeypatched secrets.token_bytes for reproducible PKCE pairs
- fake_tokens: a Tokens instance with safe placeholder values
- auth_factory: builds an EtsyAuth pointed at a temp token store
"""

from __future__ import annotations

import secrets as _secrets
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest
import respx

from etsy_core.auth import EtsyAuth, Tokens


@pytest.fixture
def temp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated config dir — sets XDG_CONFIG_HOME to a tmp dir for the test."""
    cfg = tmp_path / "xdg_config"
    cfg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.delenv("ETSY_TOKEN_STORE", raising=False)
    monkeypatch.delenv("ETSY_REFRESH_TOKEN", raising=False)
    return cfg / "etsy-mcp"


@pytest.fixture
def mock_httpx() -> Iterator[respx.MockRouter]:
    """respx router that intercepts ALL httpx calls during the test."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def deterministic_pkce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch secrets.token_bytes for reproducible PKCE pairs."""

    def _fake_token_bytes(n: int) -> bytes:
        return b"\x00" * n

    monkeypatch.setattr(_secrets, "token_bytes", _fake_token_bytes)


@pytest.fixture
def fake_tokens() -> Tokens:
    """A non-expired Tokens instance with safe placeholder values."""
    now = int(time.time())
    return Tokens(
        access_token="fake-access-12345",
        refresh_token="fake-refresh-67890",
        expires_at=now + 3600,
        granted_scopes=frozenset({"shops_r", "listings_r"}),
        obtained_at=now,
    )


@pytest.fixture
def expired_tokens() -> Tokens:
    """An expired Tokens instance — triggers refresh on first use."""
    now = int(time.time())
    return Tokens(
        access_token="expired-access",
        refresh_token="valid-refresh",
        expires_at=now - 60,  # already expired
        granted_scopes=frozenset(),
        obtained_at=now - 3700,
    )


@pytest.fixture
def auth_factory(temp_config_dir: Path):
    """Factory that builds EtsyAuth instances pointed at the temp config dir."""

    def _make(keystring: str = "test-keystring") -> EtsyAuth:
        return EtsyAuth(
            keystring=keystring,
            token_path=temp_config_dir / "tokens.json",
        )

    return _make


@pytest.fixture
def token_endpoint_success() -> dict:
    """Default successful token endpoint response body."""
    return {
        "access_token": "new-access-token-abc",
        "refresh_token": "new-refresh-token-xyz",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "shops_r shops_w listings_r listings_w",
    }


def make_response(status: int, json_body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """Helper for building canned httpx.Response objects in tests."""
    return httpx.Response(status_code=status, json=json_body or {}, headers=headers or {})
