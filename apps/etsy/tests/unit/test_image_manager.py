"""Unit tests for ImageManager.update_alt_text.

The alt_text update path is the most dangerous code path in the image
manager — the previous implementation deleted BEFORE uploading, so any
upload failure permanently lost the image. These tests lock in the new
upload-first-then-delete semantics and every failure mode the fallback
path can surface.

Coverage:
- PATCH success (primary, non-destructive)
- PATCH fails with EtsyEndpointRemoved, fallback disabled → error
- PATCH fails with EtsyEndpointRemoved, fallback enabled → upload-first success
- PATCH fails with EtsyResourceNotFound but GET succeeds → disguised endpoint
  missing, fallback runs
- PATCH fails with EtsyResourceNotFound and GET also 404s → real missing
  resource, propagates
- Fallback upload fails → old image intact, clear error
- Fallback new image is not readable → old image intact, no rollback
- Fallback delete fails after upload → success with duplicate warning
- Content-type detection from CDN headers (png / webp / jpeg default)
- Fallback without allow_destructive_fallback raises the opt-in error
- Fallback with no retrievable URL on current image raises
- PATCH path returns correct envelope shape
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from etsy_core.exceptions import (
    EtsyEndpointRemoved,
    EtsyError,
    EtsyResourceNotFound,
)
from etsy_mcp.managers.image_manager import ImageManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def image_manager(mock_client: AsyncMock) -> ImageManager:
    return ImageManager(client=mock_client)


SHOP_ID = 111
LISTING_ID = 222
IMAGE_ID = 333
NEW_IMAGE_ID = 444


def _image_dict(image_id: int, rank: int = 1) -> dict[str, Any]:
    return {
        "listing_image_id": image_id,
        "listing_id": LISTING_ID,
        "rank": rank,
        "alt_text": "old alt",
        "url_fullxfull": f"https://etsy.test/img/{image_id}/full.jpg",
        "url_570xN": f"https://etsy.test/img/{image_id}/570.jpg",
        "url_75x75": f"https://etsy.test/img/{image_id}/75.jpg",
    }


class _FakeFetchResult:
    """Stand-in for the (bytes, content_type) tuple safe_fetch returns."""


def _patch_safe_fetch(monkeypatch: pytest.MonkeyPatch, body: bytes, content_type: str) -> None:
    async def _fake(url: str, *, max_bytes: int = 0) -> tuple[bytes, str]:
        return body, content_type

    monkeypatch.setattr(
        "etsy_mcp.managers.image_manager.safe_fetch", _fake
    )


# ---------------------------------------------------------------------------
# Primary PATCH path
# ---------------------------------------------------------------------------


async def test_update_alt_text_patch_success(
    image_manager: ImageManager, mock_client: AsyncMock
) -> None:
    """Happy path: PATCH succeeds, no fallback, envelope is shaped correctly."""
    mock_client.patch.return_value = {"listing_image_id": IMAGE_ID, "alt_text": "new alt"}

    result = await image_manager.update_alt_text(
        SHOP_ID, LISTING_ID, IMAGE_ID, "new alt"
    )

    mock_client.patch.assert_awaited_once_with(
        f"/shops/{SHOP_ID}/listings/{LISTING_ID}/images/{IMAGE_ID}",
        json={"alt_text": "new alt"},
    )
    assert result["path_used"] == "patch"
    assert result["new_listing_image_id"] is None
    assert result["old_listing_image_id"] == IMAGE_ID
    assert result["warnings"] == []
    assert result["data"]["listing_image_id"] == IMAGE_ID
    # PATCH path should NOT hit get/post/delete
    mock_client.get.assert_not_awaited()
    mock_client.post.assert_not_awaited()
    mock_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback gate — opt-in required
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_disabled_raises_clear_error(
    image_manager: ImageManager, mock_client: AsyncMock
) -> None:
    """When PATCH fails with EndpointRemoved and fallback is off, we raise with guidance."""
    mock_client.patch.side_effect = EtsyEndpointRemoved(
        "Method not allowed", status=405, path="/shops/1/listings/2/images/3"
    )

    with pytest.raises(EtsyError, match="allow_destructive_fallback=True"):
        await image_manager.update_alt_text(
            SHOP_ID, LISTING_ID, IMAGE_ID, "new alt", allow_destructive_fallback=False
        )
    # Fallback gate fires BEFORE any upload/delete touches Etsy
    mock_client.post.assert_not_awaited()
    mock_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback happy path
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_success(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback runs end-to-end: upload succeeds, new image readable, delete succeeds."""
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    # get() is called twice: fetch original, verify new image
    mock_client.get.side_effect = [
        _image_dict(IMAGE_ID, rank=3),  # current image for fetching URL + rank
        _image_dict(NEW_IMAGE_ID, rank=3),  # verification GET
    ]
    mock_client.post.return_value = {"listing_image_id": NEW_IMAGE_ID, "alt_text": "new alt"}
    mock_client.delete.return_value = {}

    _patch_safe_fetch(monkeypatch, b"PNGBYTES", "image/png")

    result = await image_manager.update_alt_text(
        SHOP_ID,
        LISTING_ID,
        IMAGE_ID,
        "new alt",
        allow_destructive_fallback=True,
    )

    assert result["path_used"] == "upload_then_delete"
    assert result["new_listing_image_id"] == NEW_IMAGE_ID
    assert result["old_listing_image_id"] == IMAGE_ID
    assert any("new image" in w.lower() for w in result["warnings"])

    # Ordering: post (upload) MUST happen before delete
    post_order = mock_client.mock_calls.index(
        next(c for c in mock_client.mock_calls if c[0] == "post")
    )
    delete_order = mock_client.mock_calls.index(
        next(c for c in mock_client.mock_calls if c[0] == "delete")
    )
    assert post_order < delete_order

    # Filename derived from content type should be .png, not .jpg
    _, kwargs = mock_client.post.await_args
    assert kwargs["files"]["image"][0] == "image.png"
    assert kwargs["files"]["image"][2] == "image/png"
    # Rank preserved as string
    assert kwargs["data"]["rank"] == "3"
    assert kwargs["data"]["alt_text"] == "new alt"
    # Old image deletion targeted the ORIGINAL id, not the new one
    mock_client.delete.assert_awaited_once_with(
        f"/shops/{SHOP_ID}/listings/{LISTING_ID}/images/{IMAGE_ID}"
    )


# ---------------------------------------------------------------------------
# Fallback: upload failure — old image preserved
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_upload_failure_preserves_old(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If upload fails, we MUST NOT delete the old image."""
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    mock_client.get.return_value = _image_dict(IMAGE_ID)
    mock_client.post.side_effect = EtsyError("Etsy image cap exceeded", status=400)
    _patch_safe_fetch(monkeypatch, b"JPEGBYTES", "image/jpeg")

    with pytest.raises(EtsyError, match="still intact"):
        await image_manager.update_alt_text(
            SHOP_ID,
            LISTING_ID,
            IMAGE_ID,
            "new alt",
            allow_destructive_fallback=True,
        )

    # CRITICAL: delete must NOT have been called
    mock_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback: new image not readable after upload
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_verify_fails_preserves_old(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload succeeds, new image not readable → abort, preserve old."""
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    mock_client.get.side_effect = [
        _image_dict(IMAGE_ID),
        EtsyResourceNotFound("new image not found yet", status=404),
    ]
    mock_client.post.return_value = {"listing_image_id": NEW_IMAGE_ID}
    _patch_safe_fetch(monkeypatch, b"JPG", "image/jpeg")

    with pytest.raises(EtsyError, match="not yet\\s*readable"):
        await image_manager.update_alt_text(
            SHOP_ID,
            LISTING_ID,
            IMAGE_ID,
            "new alt",
            allow_destructive_fallback=True,
        )

    mock_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback: delete fails after upload — success with duplicate warning
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_delete_failure_returns_with_warning(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload+verify succeed, delete fails → return success with duplicate warning."""
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    mock_client.get.side_effect = [
        _image_dict(IMAGE_ID, rank=2),
        _image_dict(NEW_IMAGE_ID, rank=2),
    ]
    mock_client.post.return_value = {"listing_image_id": NEW_IMAGE_ID}
    mock_client.delete.side_effect = EtsyError("temporary outage", status=503)
    _patch_safe_fetch(monkeypatch, b"JPG", "image/jpeg")

    result = await image_manager.update_alt_text(
        SHOP_ID,
        LISTING_ID,
        IMAGE_ID,
        "new alt",
        allow_destructive_fallback=True,
    )

    assert result["path_used"] == "upload_then_delete"
    assert result["new_listing_image_id"] == NEW_IMAGE_ID
    assert any("DUPLICATE" in w for w in result["warnings"])
    assert any(str(IMAGE_ID) in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Real 404 vs disguised 404
# ---------------------------------------------------------------------------


async def test_update_alt_text_real_404_propagates(
    image_manager: ImageManager, mock_client: AsyncMock
) -> None:
    """PATCH 404 + GET 404 → the resource truly is missing, re-raise."""
    mock_client.patch.side_effect = EtsyResourceNotFound(
        "missing", status=404, path=f"/shops/{SHOP_ID}/listings/{LISTING_ID}/images/{IMAGE_ID}"
    )
    mock_client.get.side_effect = EtsyResourceNotFound("really missing", status=404)

    with pytest.raises(EtsyResourceNotFound, match="missing"):
        await image_manager.update_alt_text(
            SHOP_ID,
            LISTING_ID,
            IMAGE_ID,
            "new alt",
            allow_destructive_fallback=True,
        )

    # No destructive work performed
    mock_client.post.assert_not_awaited()
    mock_client.delete.assert_not_awaited()


async def test_update_alt_text_disguised_404_runs_fallback(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH 404 but GET succeeds → endpoint verb unsupported, run fallback."""
    mock_client.patch.side_effect = EtsyResourceNotFound("not found", status=404)
    # First GET: verification after PATCH 404 (the "is it really missing?" probe).
    # Second GET: fetch current image for fallback (URL + rank).
    # Third GET: verify new image is readable.
    mock_client.get.side_effect = [
        _image_dict(IMAGE_ID),  # verification probe — resource exists
        _image_dict(IMAGE_ID),  # fetch for fallback
        _image_dict(NEW_IMAGE_ID),  # post-upload verify
    ]
    mock_client.post.return_value = {"listing_image_id": NEW_IMAGE_ID}
    mock_client.delete.return_value = {}
    _patch_safe_fetch(monkeypatch, b"JPG", "image/jpeg")

    result = await image_manager.update_alt_text(
        SHOP_ID,
        LISTING_ID,
        IMAGE_ID,
        "new alt",
        allow_destructive_fallback=True,
    )

    assert result["path_used"] == "upload_then_delete"
    assert mock_client.get.await_count == 3


# ---------------------------------------------------------------------------
# Content-type derivation: webp must not be downgraded to jpg
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_webp_preserves_content_type(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    mock_client.get.side_effect = [
        _image_dict(IMAGE_ID),
        _image_dict(NEW_IMAGE_ID),
    ]
    mock_client.post.return_value = {"listing_image_id": NEW_IMAGE_ID}
    mock_client.delete.return_value = {}
    _patch_safe_fetch(monkeypatch, b"RIFFWEBP", "image/webp; charset=binary")

    await image_manager.update_alt_text(
        SHOP_ID, LISTING_ID, IMAGE_ID, "alt", allow_destructive_fallback=True
    )

    _, kwargs = mock_client.post.await_args
    assert kwargs["files"]["image"][0] == "image.webp"
    # Header charset param is stripped and value is lowercased
    assert kwargs["files"]["image"][2] == "image/webp"


# ---------------------------------------------------------------------------
# Fallback: current image has no URL to download from
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_no_url_raises(
    image_manager: ImageManager, mock_client: AsyncMock
) -> None:
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    # Current image has no URL fields at all
    mock_client.get.return_value = {"listing_image_id": IMAGE_ID, "rank": 1}

    with pytest.raises(EtsyError, match="no retrievable URL"):
        await image_manager.update_alt_text(
            SHOP_ID,
            LISTING_ID,
            IMAGE_ID,
            "new alt",
            allow_destructive_fallback=True,
        )

    mock_client.post.assert_not_awaited()
    mock_client.delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback: upload succeeds but response missing listing_image_id
# ---------------------------------------------------------------------------


async def test_update_alt_text_fallback_missing_new_id_aborts_before_delete(
    image_manager: ImageManager,
    mock_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_client.patch.side_effect = EtsyEndpointRemoved("gone", status=405, path="/p")
    mock_client.get.return_value = _image_dict(IMAGE_ID)
    mock_client.post.return_value = {}  # no listing_image_id
    _patch_safe_fetch(monkeypatch, b"JPG", "image/jpeg")

    with pytest.raises(EtsyError, match="no listing_image_id"):
        await image_manager.update_alt_text(
            SHOP_ID,
            LISTING_ID,
            IMAGE_ID,
            "new alt",
            allow_destructive_fallback=True,
        )

    mock_client.delete.assert_not_awaited()
