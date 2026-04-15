"""Unit tests for etsy_core.exceptions."""

from __future__ import annotations

import pytest
from etsy_core.exceptions import (
    EtsyAuthError,
    EtsyEndpointRemoved,
    EtsyError,
    EtsyNotFound,
    EtsyPossiblyCompletedError,
    EtsyRateLimitError,
    EtsyResourceNotFound,
    EtsyServerError,
    EtsyValidationError,
    _extract_message,
    _redact_error_detail,
)
from etsy_core.redaction import REDACTED_PLACEHOLDER


class TestExtractMessage:
    def test_none_returns_empty_string(self):
        assert _extract_message(None) == ""

    def test_string_passthrough(self):
        assert _extract_message("plain message") == "plain message"

    def test_extracts_error_description_first(self):
        detail = {"error_description": "expected", "error": "fallback", "message": "ignored"}
        assert _extract_message(detail) == "expected"

    def test_extracts_error_when_no_description(self):
        assert _extract_message({"error": "the error"}) == "the error"

    def test_extracts_message_key(self):
        assert _extract_message({"message": "hello"}) == "hello"

    def test_extracts_detail_key(self):
        assert _extract_message({"detail": "details here"}) == "details here"

    def test_falls_back_to_first_string_value(self):
        assert _extract_message({"weird_key": "value", "n": 3}) == "value"

    def test_dict_with_no_string_values_returns_safe_fallback(self):
        result = _extract_message({"n": 3, "list": [1, 2]})
        assert "could not be safely extracted" in result

    def test_recurses_into_first_list_element(self):
        assert _extract_message([{"error_description": "first"}, {"error": "second"}]) == "first"

    def test_unknown_type_falls_through_to_str(self):
        assert _extract_message(42) == "42"


class TestRedactErrorDetail:
    def test_redacts_dict(self):
        out = _redact_error_detail({"access_token": "leaked", "ok": "fine"})
        assert out["access_token"] == REDACTED_PLACEHOLDER
        assert out["ok"] == "fine"

    def test_redacts_list_of_dicts(self):
        out = _redact_error_detail([{"email": "a@b.c"}])
        assert out[0]["email"] == REDACTED_PLACEHOLDER

    def test_string_passthrough(self):
        assert _redact_error_detail("plain string") == "plain string"

    def test_none_passthrough(self):
        assert _redact_error_detail(None) is None

    def test_tuple_preserves_type(self):
        out = _redact_error_detail(({"refresh_token": "r"},))
        assert isinstance(out, tuple)
        assert out[0]["refresh_token"] == REDACTED_PLACEHOLDER


class TestEtsyErrorBase:
    def test_str_format_with_all_fields(self):
        err = EtsyError("boom", status=500, path="/v3/foo", request_id="abc12345")
        s = str(err)
        assert "[abc12345]" in s
        assert "HTTP 500" in s
        assert "/v3/foo" in s
        assert "boom" in s

    def test_str_format_message_only(self):
        err = EtsyError("just a message")
        assert str(err) == "just a message"

    def test_detail_is_redacted_on_construction(self):
        err = EtsyError("m", detail={"access_token": "secret"})
        assert err.detail["access_token"] == REDACTED_PLACEHOLDER

    def test_str_does_not_emit_raw_detail(self):
        err = EtsyError("oops", detail={"refresh_token": "real-refresh-value-r12345"})
        assert "real-refresh-value-r12345" not in str(err)


class TestSubclassesInheritBase:
    @pytest.mark.parametrize(
        "cls",
        [
            EtsyAuthError,
            EtsyNotFound,
            EtsyResourceNotFound,
            EtsyEndpointRemoved,
            EtsyServerError,
            EtsyValidationError,
            EtsyPossiblyCompletedError,
        ],
    )
    def test_subclass_constructs_and_inherits(self, cls):
        err = cls("test message", status=400, path="/v3/x")
        assert isinstance(err, EtsyError)
        assert err.message == "test message"
        assert err.status == 400

    def test_resource_not_found_is_etsy_not_found(self):
        assert issubclass(EtsyResourceNotFound, EtsyNotFound)

    def test_endpoint_removed_is_etsy_not_found(self):
        assert issubclass(EtsyEndpointRemoved, EtsyNotFound)


class TestRateLimitError:
    def test_carries_retry_after_seconds(self):
        err = EtsyRateLimitError("rate limited", retry_after_seconds=5, status=429)
        assert err.retry_after_seconds == 5
        assert err.status == 429

    def test_retry_after_optional(self):
        err = EtsyRateLimitError("rate limited")
        assert err.retry_after_seconds is None
