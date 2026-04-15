"""Unit tests for etsy_core.client.EtsyClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from etsy_core.auth import EtsyAuth, Tokens
from etsy_core.client import DEFAULT_BASE_URL, EtsyClient
from etsy_core.exceptions import (
    EtsyAuthError,
    EtsyEndpointRemoved,
    EtsyError,
    EtsyPossiblyCompletedError,
    EtsyRateLimitError,
    EtsyResourceNotFound,
    EtsyServerError,
    EtsyValidationError,
)


@pytest.fixture
def client(auth_factory, fake_tokens, tmp_path) -> EtsyClient:
    """An EtsyClient wired to a temp auth + temp daily counter."""
    auth = auth_factory()
    auth.save_tokens(fake_tokens)
    return EtsyClient(
        auth=auth,
        rate_limit_per_second=100.0,  # avoid pacing in unit tests
        daily_budget=10_000,
        daily_counter_path=tmp_path / "daily.json",
    )


class TestGetRetries:
    @pytest.mark.asyncio
    async def test_get_retries_on_429_then_succeeds(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/users/me/shops"
        route = mock_httpx.get(url).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "rate"}),
                httpx.Response(200, json={"shop_id": 42}),
            ]
        )
        result = await client.get("/users/me/shops")
        assert result == {"shop_id": 42}
        assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_get_retries_on_5xx_then_succeeds(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings/1"
        route = mock_httpx.get(url).mock(
            side_effect=[
                httpx.Response(503, json={}),
                httpx.Response(200, json={"listing_id": 1}),
            ]
        )
        result = await client.get("/listings/1")
        assert result["listing_id"] == 1
        assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_get_exhausted_retries_raises_server_error(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings/1"
        mock_httpx.get(url).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        with pytest.raises(EtsyServerError):
            await client.get("/listings/1")


class TestPostNoRetry:
    @pytest.mark.asyncio
    async def test_post_does_not_retry_on_5xx(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings"
        route = mock_httpx.post(url).mock(return_value=httpx.Response(500, json={"error": "boom"}))
        with pytest.raises(EtsyServerError):
            await client.post("/listings", json={"title": "test"})
        assert route.call_count == 1  # exactly one attempt

    @pytest.mark.asyncio
    async def test_post_timeout_raises_possibly_completed(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings"
        mock_httpx.post(url).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(EtsyPossiblyCompletedError, match="MAY have completed"):
            await client.post("/listings", json={"title": "test"})


class TestExceptionMapping:
    @pytest.mark.asyncio
    async def test_401_maps_to_auth_error(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings"
        mock_httpx.post(url).mock(return_value=httpx.Response(401, json={"error_description": "bad token"}))
        with pytest.raises(EtsyAuthError, match="Unauthorized"):
            await client.post("/listings", json={})

    @pytest.mark.asyncio
    async def test_403_includes_scope_hint(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings"
        mock_httpx.post(url).mock(return_value=httpx.Response(403, json={"error_description": "denied"}))
        with pytest.raises(EtsyAuthError, match="scope"):
            await client.post("/listings", json={})

    @pytest.mark.asyncio
    async def test_404_with_numeric_segment_is_resource_not_found(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings/12345"
        mock_httpx.get(url).mock(return_value=httpx.Response(404, json={"error_description": "missing"}))
        with pytest.raises(EtsyResourceNotFound):
            await client.get("/listings/12345")

    @pytest.mark.asyncio
    async def test_404_without_numeric_segment_is_endpoint_removed(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/legacy/forwarding"
        mock_httpx.get(url).mock(return_value=httpx.Response(404, json={"error_description": "gone"}))
        with pytest.raises(EtsyEndpointRemoved):
            await client.get("/legacy/forwarding")

    @pytest.mark.asyncio
    async def test_400_maps_to_validation_error(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings"
        mock_httpx.post(url).mock(return_value=httpx.Response(400, json={"error_description": "missing field"}))
        with pytest.raises(EtsyValidationError, match="Validation"):
            await client.post("/listings", json={})

    @pytest.mark.asyncio
    async def test_429_after_retries_maps_to_rate_limit(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings/1"
        mock_httpx.get(url).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "1"}, json={"error_description": "slow down"})
        )
        with pytest.raises(EtsyRateLimitError):
            await client.get("/listings/1")


class TestRateLimitStatus:
    def test_rate_limit_status_shape(self, client):
        status = client.rate_limit_status()
        assert "remaining_today" in status
        assert "reset_at_utc" in status
        assert "warning" in status
        assert isinstance(status["remaining_today"], int)
        assert status["reset_at_utc"].endswith("Z")

    def test_rate_limit_status_warning_null_when_low_usage(self, client):
        # Fresh client — 0 calls used, no warning
        assert client.rate_limit_status()["warning"] is None


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_releases_http_client(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/users/me/shops"
        mock_httpx.get(url).mock(return_value=httpx.Response(200, json={"shop_id": 1}))
        await client.get("/users/me/shops")
        assert client._http is not None
        await client.close()
        assert client._http is None

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, client):
        await client.close()
        await client.close()  # second call should not raise


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_204_returns_empty_dict(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings/1"
        mock_httpx.get(url).mock(return_value=httpx.Response(204))
        result = await client.get("/listings/1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_invalid_json_raises_etsy_error(self, client, mock_httpx):
        url = f"{DEFAULT_BASE_URL}/listings/1"
        mock_httpx.get(url).mock(return_value=httpx.Response(200, content=b"not json"))
        with pytest.raises(EtsyError, match="parse JSON"):
            await client.get("/listings/1")
