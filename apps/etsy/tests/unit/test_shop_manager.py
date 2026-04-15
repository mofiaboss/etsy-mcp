"""Unit tests for ShopManager.

Focus: prove that update() and sections_update() do real fetch-merge-put
and that read-only fields are rejected before any write. These tests exist
because the first cut of shop_manager.update() was fake fetch-merge-put and
would have wiped every unspecified shop field in production.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from etsy_core.exceptions import EtsyValidationError
from etsy_mcp.managers.shop_manager import ShopManager

# ---------------------------------------------------------------------------
# Read operations — trivial delegation
# ---------------------------------------------------------------------------


async def test_get_me_delegates_to_client(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    mock_client.get.return_value = {"shop_id": 123, "shop_name": "TestShop"}
    result = await shop_manager.get_me()
    mock_client.get.assert_awaited_once_with("/users/me/shops/")
    assert result == {"shop_id": 123, "shop_name": "TestShop"}


async def test_get_by_id_delegates_to_client(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    mock_client.get.return_value = {"shop_id": 42}
    result = await shop_manager.get_by_id(42)
    mock_client.get.assert_awaited_once_with("/shops/42")
    assert result["shop_id"] == 42


async def test_get_by_owner_user_id_delegates_to_client(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    mock_client.get.return_value = {"shop_id": 7}
    result = await shop_manager.get_by_owner_user_id(99)
    mock_client.get.assert_awaited_once_with("/users/99/shops")
    assert result["shop_id"] == 7


async def test_search_passes_params(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    mock_client.get.return_value = {"count": 0, "results": []}
    await shop_manager.search(shop_name="fancy", limit=10, offset=5)
    mock_client.get.assert_awaited_once_with(
        "/shops",
        params={"shop_name": "fancy", "limit": 10, "offset": 5},
    )


# ---------------------------------------------------------------------------
# update() — fetch-merge-put semantics
# ---------------------------------------------------------------------------


def _full_shop_fixture() -> dict[str, Any]:
    """A representative shop response with both mutable and read-only fields."""
    return {
        "shop_id": 42,
        "shop_name": "TestShop",
        "user_id": 999,
        "title": "Original title",
        "announcement": "Original announcement",
        "sale_message": "Original sale message",
        "digital_sale_message": "Original digital sale message",
        "policy_welcome": "Welcome!",
        "policy_payment": "Credit cards accepted",
        "policy_shipping": "Ships in 3-5 days",
        "policy_refunds": "30 day refunds",
        "policy_additional": "Additional policies",
        "policy_seller_info": "Seller info",
        "policy_privacy": "Privacy policy",
        "policy_has_private_receipt_info": False,
        "vacation_mode": False,
        "vacation_autoreply": None,
        # read-only
        "num_favorers": 150,
        "listing_active_count": 22,
        "url": "https://www.etsy.com/shop/TestShop",
        "currency_code": "USD",
    }


async def test_update_rejects_empty_updates(shop_manager: ShopManager) -> None:
    with pytest.raises(EtsyValidationError, match="must not be empty"):
        await shop_manager.update(42, {})


async def test_update_rejects_read_only_shop_id(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    with pytest.raises(EtsyValidationError, match="shop_id"):
        await shop_manager.update(42, {"shop_id": 99})
    # Should NOT have touched the client at all — fail before any network call
    mock_client.get.assert_not_called()
    mock_client.patch.assert_not_called()
    mock_client.put.assert_not_called()


async def test_update_rejects_read_only_user_id_and_lists_mutables(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    with pytest.raises(EtsyValidationError) as excinfo:
        await shop_manager.update(42, {"user_id": 1, "title": "New"})
    assert "user_id" in str(excinfo.value)
    # Caller should see the allowed set in the message for discoverability
    assert "title" in str(excinfo.value)
    mock_client.patch.assert_not_called()


async def test_update_rejects_num_favorers_and_url(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    with pytest.raises(EtsyValidationError):
        await shop_manager.update(42, {"num_favorers": 0, "url": "evil"})
    mock_client.patch.assert_not_called()


async def test_update_happy_path_fetch_merge_patch(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    """Single-field update should fetch, merge, and PATCH the merged dict."""
    current = _full_shop_fixture()
    mock_client.get.return_value = current
    mock_client.patch.return_value = {**current, "title": "New title"}

    result = await shop_manager.update(42, {"title": "New title"})

    # Fetched current state first
    mock_client.get.assert_awaited_once_with("/shops/42")
    # Patched with merged payload
    mock_client.patch.assert_awaited_once()
    path, = mock_client.patch.call_args.args
    assert path == "/shops/42"
    sent_payload = mock_client.patch.call_args.kwargs["json"]

    # Must include the overridden field
    assert sent_payload["title"] == "New title"
    # Must preserve other mutable fields from current state (the core bug fix)
    assert sent_payload["announcement"] == "Original announcement"
    assert sent_payload["policy_shipping"] == "Ships in 3-5 days"
    assert sent_payload["policy_refunds"] == "30 day refunds"
    assert sent_payload["vacation_mode"] is False
    # Must NOT leak read-only fields back to the server
    assert "shop_id" not in sent_payload
    assert "user_id" not in sent_payload
    assert "num_favorers" not in sent_payload
    assert "url" not in sent_payload
    assert "listing_active_count" not in sent_payload
    assert "currency_code" not in sent_payload

    assert result["title"] == "New title"


async def test_update_multi_field_merge(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    current = _full_shop_fixture()
    mock_client.get.return_value = current
    mock_client.patch.return_value = current

    await shop_manager.update(
        42,
        {
            "vacation_mode": True,
            "vacation_autoreply": "Back next week!",
            "announcement": "Closed temporarily",
        },
    )

    sent = mock_client.patch.call_args.kwargs["json"]
    assert sent["vacation_mode"] is True
    assert sent["vacation_autoreply"] == "Back next week!"
    assert sent["announcement"] == "Closed temporarily"
    # Untouched mutable fields still present
    assert sent["title"] == "Original title"
    assert sent["policy_welcome"] == "Welcome!"


async def test_update_does_not_use_put(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    """Regression guard: the original fake implementation called client.put.

    updateShop in Etsy Open API v3 is PATCH. If someone reverts this back to
    PUT this test will catch it.
    """
    mock_client.get.return_value = _full_shop_fixture()
    mock_client.patch.return_value = {}

    await shop_manager.update(42, {"title": "X"})

    mock_client.put.assert_not_called()
    mock_client.patch.assert_awaited_once()


# ---------------------------------------------------------------------------
# sections_update() — fetch-merge-put semantics
# ---------------------------------------------------------------------------


def _sections_fixture() -> dict[str, Any]:
    return {
        "count": 2,
        "results": [
            {
                "shop_section_id": 111,
                "title": "Jewelry",
                "rank": 1,
                "user_id": 999,
                "active_listing_count": 12,
            },
            {
                "shop_section_id": 222,
                "title": "Art",
                "rank": 2,
                "user_id": 999,
                "active_listing_count": 5,
            },
        ],
    }


async def test_sections_update_rejects_empty_updates(
    shop_manager: ShopManager,
) -> None:
    with pytest.raises(EtsyValidationError, match="must not be empty"):
        await shop_manager.sections_update(42, 111, {})


async def test_sections_update_rejects_read_only_fields(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    with pytest.raises(EtsyValidationError, match="user_id"):
        await shop_manager.sections_update(42, 111, {"user_id": 1})
    mock_client.put.assert_not_called()
    mock_client.get.assert_not_called()


async def test_sections_update_rejects_active_listing_count(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    with pytest.raises(EtsyValidationError):
        await shop_manager.sections_update(42, 111, {"active_listing_count": 99})
    mock_client.put.assert_not_called()


async def test_sections_update_missing_section_raises(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    mock_client.get.return_value = _sections_fixture()
    with pytest.raises(EtsyValidationError, match="not found"):
        await shop_manager.sections_update(42, 9999, {"title": "X"})
    mock_client.put.assert_not_called()


async def test_sections_update_happy_path_merges_rank(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    """Updating only title must preserve rank from current state."""
    mock_client.get.return_value = _sections_fixture()
    mock_client.put.return_value = {"shop_section_id": 111, "title": "New Name", "rank": 1}

    await shop_manager.sections_update(42, 111, {"title": "New Name"})

    mock_client.get.assert_awaited_once_with("/shops/42/sections")
    mock_client.put.assert_awaited_once()
    path, = mock_client.put.call_args.args
    assert path == "/shops/42/sections/111"
    sent = mock_client.put.call_args.kwargs["json"]
    assert sent["title"] == "New Name"
    # The key merge check: rank must be preserved from current state
    assert sent["rank"] == 1
    # Read-only fields must not leak
    assert "user_id" not in sent
    assert "active_listing_count" not in sent
    assert "shop_section_id" not in sent
    # Idempotent flag is set (safe to retry because we're sending full state)
    assert mock_client.put.call_args.kwargs["idempotent"] is True


async def test_sections_update_updating_rank_preserves_title(
    shop_manager: ShopManager, mock_client: AsyncMock
) -> None:
    mock_client.get.return_value = _sections_fixture()
    mock_client.put.return_value = {}

    await shop_manager.sections_update(42, 222, {"rank": 5})

    sent = mock_client.put.call_args.kwargs["json"]
    assert sent["rank"] == 5
    # Preserved from section 222 in the fixture
    assert sent["title"] == "Art"
