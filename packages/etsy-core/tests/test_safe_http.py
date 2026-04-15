"""Tests for etsy_core.safe_http — SSRF protections + streaming size cap."""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest
import respx
from etsy_core.safe_http import (
    BLOCKED_HOSTS,
    UnsafeURLError,
    _is_blocked_ip,
    safe_fetch,
    validate_fetch_url,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_getaddrinfo(ip: str) -> Any:
    """Return a getaddrinfo replacement that always resolves to `ip`."""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET

    def _fn(host: str, port: Any, *args: Any, **kwargs: Any) -> Any:
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    return _fn


@pytest.fixture(autouse=True)
def _clear_http_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ETSY_ALLOW_HTTP_FETCH", raising=False)


# ---------------------------------------------------------------------------
# validate_fetch_url — scheme / hostname / IP checks
# ---------------------------------------------------------------------------


def test_validate_blocks_file_scheme() -> None:
    with pytest.raises(UnsafeURLError, match="scheme not allowed"):
        validate_fetch_url("file:///etc/passwd")


def test_validate_blocks_ftp_scheme() -> None:
    with pytest.raises(UnsafeURLError, match="scheme not allowed"):
        validate_fetch_url("ftp://example.com/evil")


def test_validate_blocks_http_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with pytest.raises(UnsafeURLError, match="scheme not allowed"):
        validate_fetch_url("http://example.com/thing.jpg")


def test_validate_allows_http_when_env_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ETSY_ALLOW_HTTP_FETCH", "1")
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    assert (
        validate_fetch_url("http://example.com/thing.jpg")
        == "http://example.com/thing.jpg"
    )


def test_validate_allows_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    assert (
        validate_fetch_url("https://example.com/a.png")
        == "https://example.com/a.png"
    )


def test_validate_blocks_hostname_in_blocklist() -> None:
    with pytest.raises(UnsafeURLError, match="blocked list"):
        validate_fetch_url("https://metadata.google.internal/compute/v1/")


def test_validate_blocks_aws_imds_ip_hostname() -> None:
    with pytest.raises(UnsafeURLError, match="blocked list"):
        validate_fetch_url("https://169.254.169.254/latest/meta-data/")


def test_validate_blocks_ecs_credentials_ip() -> None:
    with pytest.raises(UnsafeURLError, match="blocked list"):
        validate_fetch_url("https://169.254.170.2/v2/credentials/")


def test_validate_blocks_rfc1918_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.0.0.5"))
    with pytest.raises(UnsafeURLError, match="RFC1918"):
        validate_fetch_url("https://evil.example.com/x")


def test_validate_blocks_link_local_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("169.254.169.254"))
    with pytest.raises(UnsafeURLError, match="link-local"):
        validate_fetch_url("https://totally-public.example.com/x")


def test_validate_blocks_loopback_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("127.0.0.1"))
    with pytest.raises(UnsafeURLError, match="loopback"):
        validate_fetch_url("https://fake.example.com/x")


def test_validate_blocks_ipv6_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("::1"))
    with pytest.raises(UnsafeURLError, match="loopback"):
        validate_fetch_url("https://fake.example.com/x")


def test_validate_blocks_ipv6_private_fc00(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("fc00::1"))
    with pytest.raises(UnsafeURLError, match="RFC1918|private"):
        validate_fetch_url("https://fake.example.com/x")


def test_validate_blocks_embedded_credentials() -> None:
    with pytest.raises(UnsafeURLError, match="embedded credentials"):
        validate_fetch_url("https://user:pass@example.com/x")


def test_validate_blocks_unresolvable_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    with pytest.raises(UnsafeURLError, match="Cannot resolve"):
        validate_fetch_url("https://nonexistent.example.com/x")


def test_validate_blocks_empty_url() -> None:
    with pytest.raises(UnsafeURLError):
        validate_fetch_url("")


def test_is_blocked_ip_ipv4_mapped_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    """IPv4-mapped IPv6 addresses (::ffff:10.0.0.1) must be unwrapped and blocked."""
    import ipaddress

    ip = ipaddress.ip_address("::ffff:10.0.0.1")
    blocked, reason = _is_blocked_ip(ip)
    assert blocked
    assert "RFC1918" in reason or "private" in reason


# ---------------------------------------------------------------------------
# safe_fetch — streaming, size cap, redirect per-hop validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_safe_fetch_returns_body_and_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with respx.mock(assert_all_called=False) as router:
        router.get("https://cdn.example.com/a.png").mock(
            return_value=httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\nfake",
                headers={"content-type": "image/png"},
            )
        )
        body, ctype = await safe_fetch("https://cdn.example.com/a.png")
        assert body == b"\x89PNG\r\n\x1a\nfake"
        assert ctype == "image/png"


@pytest.mark.asyncio
async def test_safe_fetch_enforces_content_length_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with respx.mock(assert_all_called=False) as router:
        router.get("https://cdn.example.com/big").mock(
            return_value=httpx.Response(
                200,
                content=b"x" * 2000,
                headers={"content-type": "application/octet-stream", "content-length": "2000"},
            )
        )
        with pytest.raises(UnsafeURLError, match="content-length"):
            await safe_fetch("https://cdn.example.com/big", max_bytes=1000)


@pytest.mark.asyncio
async def test_safe_fetch_enforces_streamed_size_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When content-length is missing, streaming must still enforce max_bytes."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with respx.mock(assert_all_called=False) as router:
        # respx will still advertise content-length; craft a response without one.
        router.get("https://cdn.example.com/nolen").mock(
            return_value=httpx.Response(
                200,
                content=b"y" * 5000,
                headers={"content-type": "application/octet-stream"},
            )
        )
        with pytest.raises(UnsafeURLError, match="too large"):
            await safe_fetch("https://cdn.example.com/nolen", max_bytes=1000)


@pytest.mark.asyncio
async def test_safe_fetch_follows_redirect_and_revalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 301 to a safe host should succeed and return the redirected body."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with respx.mock(assert_all_called=False) as router:
        router.get("https://a.example.com/x").mock(
            return_value=httpx.Response(
                301, headers={"location": "https://b.example.com/x"}
            )
        )
        router.get("https://b.example.com/x").mock(
            return_value=httpx.Response(
                200, content=b"final", headers={"content-type": "image/jpeg"}
            )
        )
        body, ctype = await safe_fetch("https://a.example.com/x")
        assert body == b"final"
        assert ctype == "image/jpeg"


@pytest.mark.asyncio
async def test_safe_fetch_redirect_to_private_ip_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 302 to a hostname resolving to 10.0.0.1 must be blocked per-hop."""
    call_count = {"n": 0}

    def _resolver(host: str, *args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        if "evil" in host:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0))
            ]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _resolver)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://start.example.com/x").mock(
            return_value=httpx.Response(
                302, headers={"location": "https://evil.example.com/x"}
            )
        )
        with pytest.raises(UnsafeURLError, match="RFC1918"):
            await safe_fetch("https://start.example.com/x")


@pytest.mark.asyncio
async def test_safe_fetch_redirect_to_metadata_host_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with respx.mock(assert_all_called=False) as router:
        router.get("https://start.example.com/x").mock(
            return_value=httpx.Response(
                302,
                headers={"location": "https://169.254.169.254/latest/meta-data/"},
            )
        )
        with pytest.raises(UnsafeURLError, match="blocked list"):
            await safe_fetch("https://start.example.com/x")


@pytest.mark.asyncio
async def test_safe_fetch_max_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("8.8.8.8"))
    with respx.mock(assert_all_called=False) as router:
        # Loop: each hop redirects to the next numbered hop
        for i in range(10):
            router.get(f"https://h{i}.example.com/x").mock(
                return_value=httpx.Response(
                    302,
                    headers={"location": f"https://h{i + 1}.example.com/x"},
                )
            )
        with pytest.raises(UnsafeURLError, match="redirect count"):
            await safe_fetch(
                "https://h0.example.com/x", max_redirects=3
            )


@pytest.mark.asyncio
async def test_safe_fetch_blocked_url_raises_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation must fail before any HTTP request is issued."""
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://metadata.google.internal/x").mock(
            return_value=httpx.Response(200)
        )
        with pytest.raises(UnsafeURLError):
            await safe_fetch("https://metadata.google.internal/x")
        assert not route.called


def test_blocked_hosts_covers_known_metadata_targets() -> None:
    """Regression: ensure the obvious cloud metadata targets stay in the blocklist."""
    for host in ("169.254.169.254", "169.254.170.2", "metadata.google.internal"):
        assert host in BLOCKED_HOSTS
