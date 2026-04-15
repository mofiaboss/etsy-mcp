"""Unit tests for ListingManager.update() post-PATCH verification paths.

These cover the three outcomes of _poll_verify:
1. All GET attempts fail → verification_unavailable=True
2. First GET succeeds with matching state → verification_unavailable=False, clean applied
3. First GET succeeds with diverged state → verification_unavailable=False, diverged populated

Cycle 1 review fix CONV: the manager must distinguish "cannot verify" from
"diverged" so callers aren't misled when eventual consistency or network
failures make verification impossible.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from etsy_core.exceptions import EtsyError
from etsy_mcp.managers.listing_manager import ListingManager


@pytest.fixture
def listing_manager(mock_client: AsyncMock) -> ListingManager:
    return ListingManager(client=mock_client)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Collapse the verification backoff so tests don't wait real wall-clock time."""
    import asyncio

    async def _instant(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


async def test_update_returns_verification_unavailable_when_all_polls_fail(
    listing_manager: ListingManager, mock_client: AsyncMock
) -> None:
    # First GET (fetch-for-merge) succeeds with current state; all subsequent
    # GETs (the 3 backoff polls + final poll) raise EtsyError so that
    # _poll_verify reports verify_ok=False.
    current_state = {"listing_id": 7, "price": 9, "title": "t"}

    call_count = {"n": 0}

    async def _get_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return current_state
        raise EtsyError("transient GET failure")

    mock_client.get.side_effect = _get_side_effect
    mock_client.patch.return_value = {"listing_id": 7}

    result = await listing_manager.update(42, 7, {"price": 10})

    assert result["verification_unavailable"] is True
    assert result["applied"] == {}
    assert result["diverged"] == {}
    assert any(
        w.startswith("PATCH was accepted by Etsy") for w in result["warnings"]
    )
    # PATCH was still attempted exactly once
    mock_client.patch.assert_awaited_once()
    # Verify we attempted the full poll cycle (1 fetch + 3 backoff + 1 final)
    assert call_count["n"] >= 4


async def test_update_returns_verification_ok_when_first_poll_succeeds(
    listing_manager: ListingManager, mock_client: AsyncMock
) -> None:
    # First GET is the fetch-for-merge, subsequent GETs are poll-verify.
    # Return the matching state for ALL GETs so the verify loop converges early.
    merged_state = {"listing_id": 7, "price": 10, "title": "t"}
    mock_client.get.return_value = merged_state
    mock_client.patch.return_value = merged_state

    result = await listing_manager.update(42, 7, {"price": 10})

    assert result["verification_unavailable"] is False
    assert result["applied"] == {"price": 10}
    assert result["diverged"] == {}


async def test_update_returns_diverged_when_first_poll_succeeds_with_different_value(
    listing_manager: ListingManager, mock_client: AsyncMock
) -> None:
    # Etsy normalizes price 10 -> 11 (server-side transformation).
    # Every GET should return the diverged state so the verify loop
    # exhausts the backoff without converging, then reports diverged.
    diverged_state = {"listing_id": 7, "price": 11}
    mock_client.get.return_value = diverged_state
    mock_client.patch.return_value = diverged_state

    result = await listing_manager.update(42, 7, {"price": 10})

    assert result["verification_unavailable"] is False
    assert result["diverged"] == {
        "price": {"requested": 10, "applied": 11},
    }


# ---------------------------------------------------------------------------
# Cycle 3 silent-failure regression guards: bulk isolation logging
# ---------------------------------------------------------------------------


class TestBulkIsolationLogsTraceback:
    """Cycle 3 fix P1-7: bulk update/create except Exception blocks must log
    with exc_info=True AND include str(exc) in the failed dict (not just
    the class name). The previous version silently dropped the traceback
    AND the exception message, leaving operators with only the exception
    class name to debug a 3am bulk failure."""

    @pytest.mark.asyncio
    async def test_bulk_create_unexpected_exception_logs_traceback(self, caplog):
        from unittest.mock import AsyncMock

        from etsy_core.client import EtsyClient
        from etsy_mcp.managers.listing_manager import ListingManager

        client = AsyncMock(spec=EtsyClient)
        manager = ListingManager(client)

        # Force an unexpected exception inside the per-item create path.
        # We use a template that passes pydantic validation but causes the
        # downstream client.post call to raise an unexpected RuntimeError.
        client.post = AsyncMock(side_effect=RuntimeError("boom: schema mismatch"))

        templates = [
            {
                "title": "test listing",
                "description": "desc",
                "price": 10.0,
                "quantity": 1,
                "taxonomy_id": 1,
                "who_made": "i_did",
                "when_made": "made_to_order",
                "is_supply": False,
                "shipping_profile_id": 1,
            }
        ]

        import logging

        caplog.set_level(logging.ERROR, logger="etsy_mcp.managers.listing_manager")
        result = await manager.bulk_create_from_template(shop_id=42, templates=templates)

        # The failed dict should include the actual exception message
        assert len(result["failed"]) == 1
        failed_item = result["failed"][0]
        assert "boom: schema mismatch" in failed_item["error"], (
            f"Expected str(exc) in error field, got: {failed_item['error']}"
        )
        assert failed_item["error_type"] == "RuntimeError"

        # And the logger should have captured a traceback
        traceback_records = [
            r for r in caplog.records if r.exc_info is not None
        ]
        assert traceback_records, "Expected a logger.exception() call with exc_info"

    @pytest.mark.asyncio
    async def test_bulk_update_unexpected_exception_logs_traceback(self, caplog):
        from unittest.mock import AsyncMock

        from etsy_core.client import EtsyClient
        from etsy_mcp.managers.listing_manager import ListingManager

        client = AsyncMock(spec=EtsyClient)
        manager = ListingManager(client)
        # Force update() to raise an unexpected error
        manager.update = AsyncMock(side_effect=RuntimeError("boom: state corrupt"))

        updates = [{"listing_id": 999, "patch_fields": {"price": 5.0}}]

        import logging

        caplog.set_level(logging.ERROR, logger="etsy_mcp.managers.listing_manager")
        result = await manager.bulk_update_from_template(shop_id=42, updates=updates)

        assert len(result["failed"]) == 1
        failed_item = result["failed"][0]
        assert "boom: state corrupt" in failed_item["error"]
        assert failed_item["error_type"] == "RuntimeError"

        traceback_records = [r for r in caplog.records if r.exc_info is not None]
        assert traceback_records, "Expected a logger.exception() call with exc_info"
