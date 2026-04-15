"""Unit tests for etsy_core.pkce (RFC 7636 PKCE helpers)."""

from __future__ import annotations

import base64
import hashlib

import pytest
from etsy_core.pkce import (
    CODE_CHALLENGE_METHOD,
    derive_code_challenge,
    generate_code_verifier,
    generate_pkce_pair,
    generate_state,
)


class TestGenerateCodeVerifier:
    def test_default_length_is_43_chars(self):
        # 32 bytes base64url-encoded (no padding) = 43 chars
        verifier = generate_code_verifier()
        assert len(verifier) == 43

    def test_meets_rfc7636_minimum(self):
        verifier = generate_code_verifier()
        assert len(verifier) >= 43

    def test_url_safe_chars_only(self):
        verifier = generate_code_verifier()
        # Base64url alphabet only — no +, /, =
        assert all(c.isalnum() or c in "-_" for c in verifier)

    def test_no_padding(self):
        assert "=" not in generate_code_verifier()

    def test_byte_length_below_minimum_raises(self):
        with pytest.raises(ValueError, match="must be >= 32"):
            generate_code_verifier(byte_length=16)

    def test_byte_length_above_max_raises(self):
        with pytest.raises(ValueError, match="<= 96"):
            generate_code_verifier(byte_length=97)
        with pytest.raises(ValueError, match="<= 96"):
            generate_code_verifier(byte_length=200)

    def test_larger_byte_length_yields_longer_verifier(self):
        v32 = generate_code_verifier(32)
        v64 = generate_code_verifier(64)
        assert len(v64) > len(v32)


class TestDeriveCodeChallenge:
    def test_challenge_is_sha256_of_verifier(self):
        verifier = "test-verifier-12345"
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        assert derive_code_challenge(verifier) == expected

    def test_challenge_is_43_chars(self):
        # SHA256 = 32 bytes → 43 chars base64url no padding
        assert len(derive_code_challenge("any-input")) == 43

    def test_challenge_has_no_padding(self):
        assert "=" not in derive_code_challenge("anything")

    def test_challenge_is_url_safe(self):
        c = derive_code_challenge("test")
        assert all(ch.isalnum() or ch in "-_" for ch in c)


class TestPkcePair:
    def test_pair_is_matched(self):
        verifier, challenge = generate_pkce_pair()
        assert challenge == derive_code_challenge(verifier)

    def test_default_method_is_s256(self):
        assert CODE_CHALLENGE_METHOD == "S256"


class TestPkceDeterminism:
    def test_deterministic_with_zeroed_secrets(self, deterministic_pkce):
        v1, c1 = generate_pkce_pair()
        v2, c2 = generate_pkce_pair()
        assert v1 == v2
        assert c1 == c2

    def test_zero_seed_yields_known_verifier(self, deterministic_pkce):
        # 32 zero bytes → base64url("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        verifier = generate_code_verifier()
        assert verifier == "A" * 43


class TestGenerateState:
    def test_default_is_url_safe(self):
        state = generate_state()
        assert all(c.isalnum() or c in "-_" for c in state)

    def test_default_length_is_22_chars(self):
        # 16 bytes base64url-encoded (no padding) = 22 chars
        assert len(generate_state()) == 22

    def test_no_padding(self):
        assert "=" not in generate_state()

    def test_deterministic_with_zeroed_secrets(self, deterministic_pkce):
        assert generate_state() == generate_state()
