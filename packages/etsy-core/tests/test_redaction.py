"""Unit tests for etsy_core.redaction (F3 secret redaction)."""

from __future__ import annotations

import pytest
from etsy_core.redaction import (
    REDACTED_PLACEHOLDER,
    SENSITIVE_FIELDS,
    redact_sensitive,
    redact_string,
)


class TestSensitiveFieldsCoverage:
    def test_oauth_token_fields_present(self):
        for field in ("access_token", "refresh_token", "shared_secret", "keystring", "client_secret"):
            assert field in SENSITIVE_FIELDS

    def test_buyer_pii_fields_present(self):
        for field in ("email", "first_name", "last_name", "name"):
            assert field in SENSITIVE_FIELDS

    def test_user_id_fields_present(self):
        """Cycle 1 fix CONV-2 — only `etsy_user_id` is redacted, NOT `user_id`.

        `user_id` is Etsy's public buyer/user primary key. Redacting it would
        gut every receipt/transaction/review response. Only the PII-adjacent
        `etsy_user_id` is in the sensitive set.
        """
        assert "etsy_user_id" in SENSITIVE_FIELDS
        assert "user_id" not in SENSITIVE_FIELDS

    def test_user_id_passes_through_redaction(self):
        """Cycle 1 fix CONV-2 — verify a real receipt-shaped payload preserves user_id."""
        receipt = {
            "receipt_id": 12345,
            "user_id": 67890,  # MUST NOT be redacted
            "buyer_user_id": 67890,
            "name": "Alice Smith",  # MUST be redacted (buyer PII)
            "email": "alice@example.com",  # MUST be redacted
        }
        out = redact_sensitive(receipt)
        assert out["receipt_id"] == 12345
        assert out["user_id"] == 67890  # preserved
        assert out["buyer_user_id"] == 67890  # preserved
        assert out["name"] == REDACTED_PLACEHOLDER  # redacted
        assert out["email"] == REDACTED_PLACEHOLDER  # redacted

    def test_client_id_passes_through_redaction(self):
        """Cycle 1 fix CONV-2 — `client_id` is no longer redacted."""
        out = redact_sensitive({"client_id": "abc123", "client_secret": "shhh"})
        assert out["client_id"] == "abc123"  # preserved
        assert out["client_secret"] == REDACTED_PLACEHOLDER  # still redacted

    def test_legacy_authcode_carried_forward(self):
        assert "authCode" in SENSITIVE_FIELDS


class TestRedactSensitiveDicts:
    def test_redacts_top_level_secret(self):
        out = redact_sensitive({"shop_id": 1, "access_token": "secret"})
        assert out["shop_id"] == 1
        assert out["access_token"] == REDACTED_PLACEHOLDER

    def test_preserves_non_sensitive_values(self):
        out = redact_sensitive({"shop_id": 12345, "title": "My Listing", "price": 9.99})
        assert out == {"shop_id": 12345, "title": "My Listing", "price": 9.99}

    def test_redacts_nested_dict(self):
        data = {"outer": {"refresh_token": "abc", "harmless": True}}
        out = redact_sensitive(data)
        assert out["outer"]["refresh_token"] == REDACTED_PLACEHOLDER
        assert out["outer"]["harmless"] is True

    def test_returns_new_structure_does_not_mutate(self):
        original = {"access_token": "real-token"}
        _ = redact_sensitive(original)
        assert original["access_token"] == "real-token"

    def test_redacts_email_in_buyer_record(self):
        out = redact_sensitive({"buyer": {"email": "buyer@example.com", "first_name": "Jane"}})
        assert out["buyer"]["email"] == REDACTED_PLACEHOLDER
        assert out["buyer"]["first_name"] == REDACTED_PLACEHOLDER

    def test_none_value_for_sensitive_field_not_redacted(self):
        # None means "not set" — redacting it would be misleading
        out = redact_sensitive({"access_token": None})
        assert out["access_token"] is None


class TestRedactSensitiveCollections:
    def test_redacts_list_of_dicts(self):
        out = redact_sensitive([{"email": "a@b.c"}, {"email": "x@y.z"}])
        assert out[0]["email"] == REDACTED_PLACEHOLDER
        assert out[1]["email"] == REDACTED_PLACEHOLDER

    def test_redacts_tuple_preserves_type(self):
        out = redact_sensitive(({"access_token": "t"},))
        assert isinstance(out, tuple)
        assert out[0]["access_token"] == REDACTED_PLACEHOLDER

    def test_redacts_deeply_nested(self):
        data = {"a": [{"b": {"c": [{"refresh_token": "r"}]}}]}
        out = redact_sensitive(data)
        assert out["a"][0]["b"]["c"][0]["refresh_token"] == REDACTED_PLACEHOLDER


class TestRedactSensitivePrimitives:
    @pytest.mark.parametrize("value", [None, 0, 1, "string", 1.5, True, False])
    def test_primitives_passthrough(self, value):
        assert redact_sensitive(value) == value

    def test_empty_dict_passthrough(self):
        assert redact_sensitive({}) == {}

    def test_empty_list_passthrough(self):
        assert redact_sensitive([]) == []


class TestRedactString:
    def test_no_replacements_is_noop(self):
        assert redact_string("anything goes") == "anything goes"

    def test_replaces_known_secret(self):
        out = redact_string("Bearer secret-token-value", replacements={"secret-token-value": "[REDACTED]"})
        assert "secret-token-value" not in out
        assert "[REDACTED]" in out

    def test_replaces_multiple_secrets(self):
        text = "key=AAA secret=BBB"
        out = redact_string(text, replacements={"AAA": "[A]", "BBB": "[B]"})
        assert out == "key=[A] secret=[B]"

    def test_empty_secret_string_is_skipped(self):
        # Empty key would replace every position — guard must skip it
        out = redact_string("hello world", replacements={"": "[X]"})
        assert out == "hello world"
