"""MCP tool module: listing_images category.

7 tools:
- etsy_listing_images_list
- etsy_listing_images_get
- etsy_listing_images_upload
- etsy_listing_images_update_alt_text
- etsy_listing_images_bulk_update_alt_text  (BULK PRIMITIVE)
- etsy_listing_images_delete
- etsy_listing_images_reorder

All tools are thin wrappers: validate args -> delegate to ImageManager ->
format envelope -> return. Exceptions are caught and returned as error
envelopes. Destructive operations require confirm=True.

Bulk primitive rule applies — this module makes no decisions about WHICH
alt_text to set or HOW to write it. Callers (LLM) provide the values.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_image_manager, get_server
from etsy_mcp.schemas import (
    error_envelope,
    partial_success_envelope,
    success_envelope,
)

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_images_list",
    description="List all images on an Etsy listing. Each image includes its alt_text field, "
    "rank, dimensions, and CDN URLs. Use this to audit alt_text coverage across a shop.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_images",
    permission_action="READ",
)
async def etsy_listing_images_list(shop_id: int, listing_id: int) -> dict[str, Any]:
    """List images on a listing."""
    try:
        manager = get_image_manager()
        data = await manager.list(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_images_list(%s, %s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to list images for listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_images_get",
    description="Get a single image on an Etsy listing by listing_image_id. Includes alt_text.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_images",
    permission_action="READ",
)
async def etsy_listing_images_get(
    shop_id: int,
    listing_id: int,
    listing_image_id: int,
) -> dict[str, Any]:
    """Get a single listing image."""
    try:
        manager = get_image_manager()
        data = await manager.get(shop_id, listing_id, listing_image_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_images_get(%s, %s, %s) failed: %s",
            shop_id,
            listing_id,
            listing_image_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to get image {listing_image_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_images_upload",
    description="Upload an image to an Etsy listing. image_source can be a local file path "
    "(file:///abs/path or /abs/path) or an HTTP(S) URL — the manager downloads URL sources "
    "to memory and forwards them as multipart. alt_text is optional but recommended on creation. "
    "rank controls position (1 is primary). With confirm=False (default), returns a preview.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listing_images",
    permission_action="CREATE",
)
async def etsy_listing_images_upload(
    shop_id: int,
    listing_id: int,
    image_source: str,
    rank: int = 1,
    alt_text: str | None = None,
    overwrite: bool = False,
    is_watermarked: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Upload an image to a listing."""
    try:
        if not image_source or not image_source.strip():
            return error_envelope("image_source must not be empty")
        if rank < 1:
            return error_envelope("rank must be >= 1")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "listing_image",
                "resource_id": "(new)",
                "preview": {
                    "current": None,
                    "proposed": {
                        "shop_id": shop_id,
                        "listing_id": listing_id,
                        "image_source": image_source,
                        "rank": rank,
                        "alt_text": alt_text,
                        "overwrite": overwrite,
                        "is_watermarked": is_watermarked,
                    },
                },
                "message": (
                    f"Will upload image to listing {listing_id} at rank {rank}"
                    f"{' with alt_text' if alt_text else ' (no alt_text)'}. "
                    "Set confirm=true to execute."
                ),
            }

        manager = get_image_manager()
        data = await manager.upload(
            shop_id,
            listing_id,
            image_source=image_source,
            rank=rank,
            alt_text=alt_text,
            overwrite=overwrite,
            is_watermarked=is_watermarked,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_images_upload(%s, %s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to upload image: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_upload unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_images_update_alt_text",
    description="Update the alt_text on a single listing image. The implementation tries a "
    "PATCH endpoint first; if Etsy does not expose PATCH for ShopListingImage, it falls back "
    "to a DESTRUCTIVE delete + re-upload (preserving original file bytes and rank). "
    "If the fallback path's re-upload fails, the image will be MISSING from the listing. "
    "Requires confirm=True. The new image_id may differ from the original after fallback.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listing_images",
    permission_action="UPDATE",
)
async def etsy_listing_images_update_alt_text(
    shop_id: int,
    listing_id: int,
    listing_image_id: int,
    alt_text: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Update alt_text on a single image (try PATCH then fallback)."""
    try:
        if alt_text is None:
            return error_envelope("alt_text must be provided (use empty string to clear)")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "listing_image",
                "resource_id": str(listing_image_id),
                "preview": {
                    "proposed": {"alt_text": alt_text},
                },
                "warnings": [
                    "Primary path: PATCH endpoint (non-destructive).",
                    "Fallback path (if PATCH unavailable): DELETE + re-upload. "
                    "Rank is preserved but the listing_image_id will change. "
                    "If re-upload fails, the image will be MISSING from the listing.",
                ],
                "message": (
                    f"Will update alt_text on image {listing_image_id} (listing {listing_id}). "
                    "May fall back to destructive delete+reupload. Set confirm=true to execute."
                ),
            }

        manager = get_image_manager()
        result = await manager.update_alt_text(shop_id, listing_id, listing_image_id, alt_text)
        return success_envelope(
            {
                "path_used": result["path_used"],
                "image": result["data"],
            },
            rate_limit=get_client().rate_limit_status(),
        )
    except EtsyError as exc:
        logger.error(
            "etsy_listing_images_update_alt_text(%s, %s, %s) failed: %s",
            shop_id,
            listing_id,
            listing_image_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to update alt_text: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_update_alt_text unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_images_bulk_update_alt_text",
    description="BULK PRIMITIVE: update alt_text on many images across listings in one call. "
    "updates is a list of {listing_id, listing_image_id, alt_text} dicts. Each item is "
    "processed via the same try-PATCH-then-fallback logic as the single-item tool. "
    "Returns a partial-success envelope with per-item path_used ('patch' or 'delete_reupload'). "
    "DESTRUCTIVE if any item falls back. Requires confirm=True. This tool makes NO decisions "
    "about content — the caller (LLM) must already know which alt_text to set on each image.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listing_images",
    permission_action="UPDATE",
)
async def etsy_listing_images_bulk_update_alt_text(
    shop_id: int,
    updates: list[dict[str, Any]],
    confirm: bool = False,
) -> dict[str, Any]:
    """Bulk update alt_text across many images."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")
        if not isinstance(updates, list):
            return error_envelope("updates must be a list of dicts")

        # Validate shape
        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(updates):
            if not isinstance(item, dict):
                return error_envelope(f"updates[{idx}] must be a dict")
            try:
                listing_id = int(item["listing_id"])
                listing_image_id = int(item["listing_image_id"])
                alt_text = item["alt_text"]
            except (KeyError, TypeError, ValueError) as exc:
                return error_envelope(
                    f"updates[{idx}] missing required keys "
                    f"(listing_id, listing_image_id, alt_text): {exc}"
                )
            if alt_text is None:
                return error_envelope(
                    f"updates[{idx}].alt_text must be provided (use empty string to clear)"
                )
            normalized.append(
                {
                    "listing_id": listing_id,
                    "listing_image_id": listing_image_id,
                    "alt_text": alt_text,
                }
            )

        if not confirm:
            sample = normalized[:3]
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "bulk_update",
                "resource_type": "listing_image",
                "resource_id": f"({len(normalized)} images)",
                "preview": {
                    "total": len(normalized),
                    "sample": sample,
                },
                "warnings": [
                    "Each item attempts PATCH first; on PATCH unavailability the fallback "
                    "is DESTRUCTIVE delete + re-upload.",
                    "If fallback re-upload fails for any item, that image will be MISSING "
                    "from its listing. Per-item results are reported in the response.",
                    "Bulk operations consume rate-limit budget proportional to item count "
                    "(2-3x per item if fallback path is active).",
                ],
                "message": (
                    f"Will update alt_text on {len(normalized)} images in shop {shop_id}. "
                    "Set confirm=true to execute."
                ),
            }

        manager = get_image_manager()
        updated: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for item in normalized:
            listing_id = item["listing_id"]
            listing_image_id = item["listing_image_id"]
            alt_text = item["alt_text"]
            try:
                result = await manager.update_alt_text(
                    shop_id, listing_id, listing_image_id, alt_text
                )
                updated.append(
                    {
                        "listing_id": listing_id,
                        "listing_image_id": listing_image_id,
                        "status": "success",
                        "path_used": result.get("path_used"),
                    }
                )
            except EtsyError as exc:
                logger.error(
                    "bulk_update_alt_text item failed (listing %s image %s): %s",
                    listing_id,
                    listing_image_id,
                    exc,
                )
                failed.append(
                    {
                        "listing_id": listing_id,
                        "listing_image_id": listing_image_id,
                        "status": "error",
                        "error": exc.message,
                    }
                )
            except Exception as exc:
                logger.error(
                    "bulk_update_alt_text item unexpected error (listing %s image %s)",
                    listing_id,
                    listing_image_id,
                    exc_info=True,
                )
                failed.append(
                    {
                        "listing_id": listing_id,
                        "listing_image_id": listing_image_id,
                        "status": "error",
                        "error": f"Unexpected error: {exc.__class__.__name__}",
                    }
                )

        return partial_success_envelope(
            updated=updated,
            failed=failed,
            rate_limit=get_client().rate_limit_status(),
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_bulk_update_alt_text unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_images_delete",
    description="Delete an image from an Etsy listing. DESTRUCTIVE — the image is removed "
    "from the listing immediately. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_images",
    permission_action="DELETE",
)
async def etsy_listing_images_delete(
    shop_id: int,
    listing_id: int,
    listing_image_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a listing image."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "listing_image",
                "resource_id": str(listing_image_id),
                "warnings": [
                    "This permanently removes the image from the listing.",
                    "Remaining images may shift in rank order.",
                ],
                "message": (
                    f"Will DELETE image {listing_image_id} from listing {listing_id}. "
                    "Set confirm=true to execute."
                ),
            }

        manager = get_image_manager()
        data = await manager.delete(shop_id, listing_id, listing_image_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_images_delete(%s, %s, %s) failed: %s",
            shop_id,
            listing_id,
            listing_image_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to delete image {listing_image_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_images_reorder",
    description="Reorder all images on a listing by passing the full ordered list of "
    "listing_image_ids. The first id becomes rank 1 (primary). Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_images",
    permission_action="UPDATE",
)
async def etsy_listing_images_reorder(
    shop_id: int,
    listing_id: int,
    image_order: list[int],
    confirm: bool = False,
) -> dict[str, Any]:
    """Reorder a listing's images."""
    try:
        if not image_order:
            return error_envelope("image_order must not be empty")
        if not isinstance(image_order, list):
            return error_envelope("image_order must be a list of listing_image_ids")
        try:
            normalized_order = [int(i) for i in image_order]
        except (TypeError, ValueError) as exc:
            return error_envelope(f"image_order entries must be integers: {exc}")
        if len(set(normalized_order)) != len(normalized_order):
            return error_envelope("image_order contains duplicate ids")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "listing_image_order",
                "resource_id": str(listing_id),
                "preview": {
                    "proposed": {"image_order": normalized_order},
                },
                "message": (
                    f"Will reorder {len(normalized_order)} images on listing {listing_id} "
                    f"(new primary: {normalized_order[0]}). Set confirm=true to execute."
                ),
            }

        manager = get_image_manager()
        data = await manager.reorder(shop_id, listing_id, normalized_order)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_images_reorder(%s, %s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to reorder images: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_images_reorder unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
