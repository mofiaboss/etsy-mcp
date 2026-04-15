"""Safe HTTP client wrapper that blocks SSRF.

Used by any etsy-mcp code path that fetches arbitrary user-provided URLs
(e.g., image_source for listing_images_upload, video_source, digital_file_source).

Blocks:
- Non-HTTPS (unless ETSY_ALLOW_HTTP_FETCH=1, for local testing only)
- file:// and ftp:// schemes
- RFC1918 private IPs (10/8, 172.16/12, 192.168/16)
- Link-local (169.254.0.0/16) - blocks AWS/GCP metadata endpoints
- Loopback (127.0.0.0/8, ::1)
- IPv6 private ranges (fc00::/7, fe80::/10)
- Cloud metadata service hostnames (169.254.169.254, metadata.google.internal, etc.)
- URLs with embedded credentials
- Responses exceeding max_bytes
- Redirects to any blocked target (each hop is revalidated)
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

BLOCKED_HOSTS = frozenset({
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "169.254.170.2",  # ECS container credentials
    "fd00:ec2::254",  # IMDSv2 IPv6
})

DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB hard cap
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_REDIRECTS = 5


class UnsafeURLError(Exception):
    """Raised when a URL is blocked by SSRF protections."""


def _is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> tuple[bool, str]:
    """Check if an IP address is in a blocked range. Returns (blocked, reason)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_blocked_ip(ip.ipv4_mapped)
    if ip.is_loopback:
        return True, "loopback address"
    if ip.is_link_local:
        return True, "link-local address (blocks cloud metadata)"
    if ip.is_private:
        return True, "RFC1918 private address"
    if ip.is_reserved:
        return True, "reserved address"
    if ip.is_multicast:
        return True, "multicast address"
    if ip.is_unspecified:
        return True, "unspecified address"
    return False, ""


def validate_fetch_url(url: str) -> str:
    """Validate that a URL is safe to fetch.

    Returns the URL if OK, raises UnsafeURLError otherwise.

    Checks:
    1. Scheme must be https (or http if ETSY_ALLOW_HTTP_FETCH=1)
    2. No embedded credentials (user:pass@)
    3. Hostname is not in BLOCKED_HOSTS
    4. Hostname resolves to a non-private/non-loopback/non-link-local IP
    """
    if not isinstance(url, str) or not url:
        raise UnsafeURLError("URL must be a non-empty string")

    parsed = urlparse(url)

    # 1. Scheme check
    allow_http = os.environ.get("ETSY_ALLOW_HTTP_FETCH", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if parsed.scheme == "https":
        pass
    elif parsed.scheme == "http" and allow_http:
        pass
    else:
        raise UnsafeURLError(
            f"URL scheme not allowed: {parsed.scheme!r}. Must be https "
            f"(set ETSY_ALLOW_HTTP_FETCH=1 for local http testing)."
        )

    # 2. No basic auth in URL (defense against smuggled credentials)
    if parsed.username or parsed.password:
        raise UnsafeURLError("URL with embedded credentials is not allowed")

    # 3. Hostname extraction
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError(f"URL has no hostname: {url}")

    # 4. Hostname allowlist check (pre-DNS — catches well-known metadata names)
    if hostname.lower() in BLOCKED_HOSTS:
        raise UnsafeURLError(
            f"Hostname is in the blocked list (cloud metadata): {hostname}"
        )

    # 5. DNS resolution + IP check (every resolved address must pass)
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Cannot resolve hostname {hostname}: {exc}") from exc

    if not infos:
        raise UnsafeURLError(f"No addresses resolved for hostname {hostname}")

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        # Strip IPv6 zone id if present (e.g., "fe80::1%eth0")
        if "%" in ip_str:
            ip_str = ip_str.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise UnsafeURLError(f"Cannot parse resolved IP {ip_str!r}: {exc}") from exc
        blocked, reason = _is_blocked_ip(ip)
        if blocked:
            raise UnsafeURLError(
                f"Hostname {hostname} resolves to {ip} which is blocked: {reason}"
            )

    return url


def _enforce_content_length(
    content_length: str | None, max_bytes: int
) -> None:
    """Raise UnsafeURLError if declared content-length exceeds max_bytes."""
    if not content_length:
        return
    try:
        declared = int(content_length)
    except ValueError:
        return
    if declared > max_bytes:
        raise UnsafeURLError(
            f"Response too large: content-length {declared} > max {max_bytes}"
        )


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    max_bytes: int,
) -> httpx.Response:
    """Send a single GET (no auto-redirect), streaming into memory with size cap."""
    # Use a streamed request so we can enforce max_bytes without loading
    # an unbounded response into memory.
    async with client.stream("GET", url) as response:
        _enforce_content_length(
            response.headers.get("content-length"), max_bytes
        )
        buf = bytearray()
        async for chunk in response.aiter_bytes():
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise UnsafeURLError(
                    f"Response too large: exceeded max {max_bytes} bytes during stream"
                )
        # Build a non-streamed Response copy with the collected body so the
        # caller can inspect headers/status after the context manager closes.
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=bytes(buf),
            request=response.request,
        )


async def safe_fetch(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> tuple[bytes, str]:
    """Fetch a URL with SSRF protection + size cap + per-hop redirect validation.

    Returns (body_bytes, content_type).

    Raises:
        UnsafeURLError: if any hop fails validation or response is too large
        httpx.HTTPError: for transport / non-2xx status errors
    """
    current_url = validate_fetch_url(url)

    # Explicitly disable httpx redirect handling — we follow manually so every
    # hop is revalidated against SSRF rules.
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False
    ) as client:
        for hop in range(max_redirects + 1):
            response = await _fetch_one(client, current_url, max_bytes)

            # Manual redirect handling
            if response.status_code in (301, 302, 303, 307, 308):
                if hop >= max_redirects:
                    raise UnsafeURLError(
                        f"Exceeded maximum redirect count ({max_redirects})"
                    )
                location = response.headers.get("location")
                if not location:
                    raise UnsafeURLError(
                        f"Redirect ({response.status_code}) with no Location header"
                    )
                # Resolve relative Location against current URL
                next_url = urljoin(current_url, location)
                logger.debug(
                    "safe_fetch following redirect %d -> %s",
                    response.status_code,
                    next_url,
                )
                current_url = validate_fetch_url(next_url)
                continue

            # Not a redirect — enforce non-error status, return
            response.raise_for_status()
            content_type = response.headers.get(
                "content-type", "application/octet-stream"
            )
            return bytes(response.content), content_type

        # Should be unreachable (loop exits via return or raise), but be defensive
        raise UnsafeURLError(
            f"Exceeded maximum redirect count ({max_redirects})"
        )
