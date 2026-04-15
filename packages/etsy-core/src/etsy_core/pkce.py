"""PKCE (Proof Key for Code Exchange) helpers for OAuth 2.0.

Implements RFC 7636. Etsy requires PKCE with S256 method for all public
clients (no client secret exposed in the authorization URL).

Flow:
    1. Generate a random code_verifier (43+ chars base64url)
    2. Derive code_challenge = base64url(SHA256(verifier))
    3. Include code_challenge in the authorization URL
    4. Exchange authorization code + code_verifier at the token endpoint
    5. Server verifies SHA256(verifier) == challenge

The verifier never leaves the client. Even if an attacker intercepts the
authorization code from the redirect URL, they can't exchange it without
the verifier.
"""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_code_verifier(byte_length: int = 32) -> str:
    """Generate a cryptographically random code verifier.

    Args:
        byte_length: Number of random bytes. Default 32 yields a 43-char
            base64url string. RFC 7636 §4.1 requires a verifier between 43
            and 128 characters, which corresponds to 32-96 bytes of entropy
            after base64url encoding (4 * ceil(n/3) characters).

    Returns:
        A URL-safe base64 string (no padding), 43-128 characters long,
        suitable for use as code_verifier.

    Raises:
        ValueError: if byte_length is outside [32, 96]. Etsy rejects
            verifiers outside the RFC 7636 bounds.
    """
    if byte_length < 32:
        raise ValueError(
            f"byte_length must be >= 32 to meet RFC 7636 minimum (43 chars), got {byte_length}"
        )
    if byte_length > 96:
        raise ValueError(
            f"byte_length must be <= 96 to meet RFC 7636 maximum (128 chars), got {byte_length}"
        )
    raw = secrets.token_bytes(byte_length)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def derive_code_challenge(verifier: str) -> str:
    """Derive the S256 code challenge from a verifier.

    Args:
        verifier: The code_verifier string (as returned by generate_code_verifier)

    Returns:
        A URL-safe base64 SHA256 hash (no padding) suitable for use as code_challenge.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_pkce_pair(byte_length: int = 32) -> tuple[str, str]:
    """Generate a matched (verifier, challenge) PKCE pair.

    Convenience wrapper around generate_code_verifier + derive_code_challenge.

    Args:
        byte_length: Verifier byte length (default 32 → 43-char verifier)

    Returns:
        Tuple of (verifier, challenge). Both are URL-safe base64 strings.
    """
    verifier = generate_code_verifier(byte_length)
    challenge = derive_code_challenge(verifier)
    return verifier, challenge


#: The only code challenge method this module supports. RFC 7636 also defines
#: "plain" but it's not secure for public clients. Etsy only accepts S256.
CODE_CHALLENGE_METHOD = "S256"


def generate_state(byte_length: int = 16) -> str:
    """Generate a random state parameter for CSRF protection.

    The state is included in the authorization URL and verified in the
    callback. This prevents CSRF attacks where an attacker tricks the user
    into completing an OAuth flow for the attacker's account.

    Args:
        byte_length: Number of random bytes. Default 16 = 128 bits.

    Returns:
        A URL-safe base64 string (no padding).
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(byte_length)).decode("ascii").rstrip("=")
