"""Shared pytest fixtures for etsy_mcp app-level unit tests.

Provides:
- mock_client: AsyncMock EtsyClient stand-in with async get/post/put/patch/delete
- shop_manager: ShopManager wired to mock_client
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from etsy_mcp.managers.shop_manager import ShopManager


@pytest.fixture
def mock_client() -> AsyncMock:
    """AsyncMock EtsyClient — individual tests set .return_value per call."""
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.patch = AsyncMock()
    client.delete = AsyncMock()
    return client


@pytest.fixture
def shop_manager(mock_client: AsyncMock) -> ShopManager:
    """ShopManager bound to the mock_client fixture."""
    return ShopManager(client=mock_client)
