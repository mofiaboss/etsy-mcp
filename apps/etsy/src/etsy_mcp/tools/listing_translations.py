"""MCP tool module: listing_translations category.

3 tools:
- etsy_listing_translations_get
- etsy_listing_translations_create_or_update   (PUT with fetch-merge semantics + preview)
- etsy_listing_translations_delete             (destructive + confirm)
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError, EtsyResourceNotFound
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_server, get_translation_manager
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Read tool
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_translations_get",
    description="Get a single translation for a listing in a specific language. "
    "Returns title, description, and tags in that language. Language is an ISO 639-1 code (e.g. 'en', 'fr', 'de').",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_translations",
    permission_action="READ",
)
async def etsy_listing_translations_get(
    shop_id: int,
    listing_id: int,
    language: str,
) -> dict[str, Any]:
    """Get a translation."""
    try:
        if not language or not language.strip():
            return error_envelope("language must not be empty")
        manager = get_translation_manager()
        data = await manager.get(shop_id, listing_id, language.strip())
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_translations_get(%s, %s, %s) failed: %s",
            shop_id,
            listing_id,
            language,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to get translation: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_translations_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_translations_create_or_update",
    description="Create or update a listing translation for a specific language. Uses fetch-merge-put: "
    "pass only the fields you want to set/change. If the translation does not yet exist, this creates it. "
    "With confirm=False (default), returns a preview. With confirm=True, executes the PUT.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_translations",
    permission_action="UPDATE",
)
async def etsy_listing_translations_create_or_update(
    shop_id: int,
    listing_id: int,
    language: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create or update a translation."""
    try:
        if not language or not language.strip():
            return error_envelope("language must not be empty")
        if title is None and description is None and tags is None:
            return error_envelope("At least one of title/description/tags must be provided")

        manager = get_translation_manager()
        language = language.strip()

        if not confirm:
            current: dict[str, Any] | None = None
            try:
                current = await manager.get(shop_id, listing_id, language)
            except EtsyResourceNotFound:
                current = None

            proposed: dict[str, Any] = {}
            if title is not None:
                proposed["title"] = title
            if description is not None:
                proposed["description"] = description
            if tags is not None:
                proposed["tags"] = tags

            current_relevant = (
                {k: current.get(k) for k in proposed.keys()} if current else None
            )
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create" if current is None else "update",
                "resource_type": "listing_translation",
                "resource_id": f"{listing_id}/{language}",
                "preview": {
                    "current": current_relevant,
                    "proposed": proposed,
                },
                "message": (
                    f"Will {'create' if current is None else 'update'} translation "
                    f"({language}) on listing {listing_id}. Set confirm=true to execute."
                ),
            }

        data = await manager.create_or_update(
            shop_id,
            listing_id,
            language,
            title=title,
            description=description,
            tags=tags,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_translations_create_or_update failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to create/update translation: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid translation payload: {exc}")
    except Exception as exc:
        logger.error(
            "etsy_listing_translations_create_or_update unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_translations_delete",
    description="Delete a listing translation for a specific language. DESTRUCTIVE — the translation "
    "is permanently removed. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_translations",
    permission_action="DELETE",
)
async def etsy_listing_translations_delete(
    shop_id: int,
    listing_id: int,
    language: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a translation."""
    try:
        if not language or not language.strip():
            return error_envelope("language must not be empty")
        language = language.strip()

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "listing_translation",
                "resource_id": f"{listing_id}/{language}",
                "warnings": [
                    "Buyers in this locale will no longer see the translated copy."
                ],
                "message": (
                    f"Will DELETE translation ({language}) from listing {listing_id}. "
                    f"This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_translation_manager()
        data = await manager.delete(shop_id, listing_id, language)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_translations_delete failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to delete translation: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_translations_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
