"""Unit tests for etsy_core.retry."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from etsy_core.retry import (
    _extract_retry_after,
    _wait_retry_after_or_exponential,
    build_retry_config,
    is_retryable_http_error,
)


def _status_error(status: int, headers: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/x")
    response = httpx.Response(status_code=status, headers=headers or {}, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


class TestIsRetryableHttpError:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_retryable_statuses(self, status):
        assert is_retryable_http_error(_status_error(status)) is True

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_non_retryable_4xx(self, status):
        assert is_retryable_http_error(_status_error(status)) is False

    def test_timeout_is_retryable(self):
        exc = httpx.ReadTimeout("slow")
        assert is_retryable_http_error(exc) is True

    def test_connect_timeout_is_retryable(self):
        exc = httpx.ConnectTimeout("nope")
        assert is_retryable_http_error(exc) is True

    def test_unrelated_exception_not_retryable(self):
        assert is_retryable_http_error(ValueError("nope")) is False


class TestExtractRetryAfter:
    def test_returns_none_for_non_status_error(self):
        assert _extract_retry_after(ValueError("x")) is None

    def test_returns_none_when_header_absent(self):
        assert _extract_retry_after(_status_error(429)) is None

    def test_extracts_numeric_seconds(self):
        assert _extract_retry_after(_status_error(429, {"Retry-After": "5"})) == 5.0

    def test_clamps_high_to_300(self):
        assert _extract_retry_after(_status_error(429, {"Retry-After": "9999"})) == 300.0

    def test_clamps_low_to_1(self):
        assert _extract_retry_after(_status_error(429, {"Retry-After": "0"})) == 1.0

    def test_malformed_header_returns_none(self):
        assert _extract_retry_after(_status_error(429, {"Retry-After": "soon"})) is None


class TestWaitStrategy:
    def test_honors_retry_after_header(self):
        retry_state = MagicMock()
        retry_state.outcome.exception.return_value = _status_error(429, {"Retry-After": "7"})
        retry_state.attempt_number = 1
        wait = _wait_retry_after_or_exponential(retry_state)
        assert wait == 7.0

    def test_falls_back_to_exponential_without_header(self):
        retry_state = MagicMock()
        retry_state.outcome.exception.return_value = _status_error(500)
        retry_state.attempt_number = 1
        wait = _wait_retry_after_or_exponential(retry_state)
        assert wait > 0


class TestBuildRetryConfig:
    def test_default_max_attempts_three(self):
        cfg = build_retry_config()
        # tenacity stop_after_attempt(3) — verify the stop attribute carries 3
        assert cfg.stop.max_attempt_number == 3

    def test_custom_max_attempts(self):
        cfg = build_retry_config(max_attempts=5)
        assert cfg.stop.max_attempt_number == 5
