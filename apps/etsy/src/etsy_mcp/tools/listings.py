"""MCP tool module: listings category.

19 tools (10 read, 9 write):

Read:
- etsy_listings_list_by_shop
- etsy_listings_list_by_shop_receipt
- etsy_listings_list_by_shop_section
- etsy_listings_list_by_shop_return_policy
- etsy_listings_list_by_ids
- etsy_listings_search_active
- etsy_listings_get_featured
- etsy_listings_get
- etsy_listings_list_translations
- etsy_listings_list_return_policies

Write:
- etsy_listings_create_draft
- etsy_listings_bulk_create_from_template     (BULK PRIMITIVE)
- etsy_listings_update                        (fetch-merge-put + verification)
- etsy_listings_bulk_update_from_template     (BULK PRIMITIVE)
- etsy_listings_delete
- etsy_listings_activate
- etsy_listings_deactivate
- etsy_listings_copy
- etsy_listings_update_variation_images

All tools are thin wrappers: validate args -> delegate to ListingManager
-> format envelope -> return. Exceptions are caught and returned as error
envelopes. Every mutation defaults to confirm=False and returns a preview.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.models.listing import MUTABLE_FIELDS
from etsy_mcp.models.listing_template import ListingTemplate
from etsy_mcp.runtime import get_client, get_listing_manager, get_server
from etsy_mcp.schemas import (
    error_envelope,
    partial_success_envelope,
    success_envelope,
    update_with_verification_envelope,
)

logger = logging.getLogger(__name__)

server = get_server()


# =============================================================================
# READ tools
# =============================================================================


@server.tool(
    name="etsy_listings_list_by_shop",
    description="List a shop's listings, paginated. Supports optional state filter "
    "(active|inactive|draft|expired|sold_out) and sort_on (created|price|updated|score). "
    "Use limit + offset for pagination (max limit 100).",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_by_shop(
    shop_id: int,
    limit: int = 25,
    offset: int = 0,
    state: str | None = None,
    sort_on: str | None = None,
) -> dict[str, Any]:
    """List listings by shop."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_listing_manager()
        data = await manager.list_by_shop(
            shop_id, limit=limit, offset=offset, state=state, sort_on=sort_on
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listings_list_by_shop(%s) failed: %s", shop_id, exc, exc_info=True)
        return error_envelope(f"Failed to list shop {shop_id} listings: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_by_shop unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_list_by_shop_receipt",
    description="List the listings attached to a specific receipt (order). "
    "Use to inspect what a buyer actually purchased on a given receipt_id.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_by_shop_receipt(
    shop_id: int,
    receipt_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List listings on a receipt."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_listing_manager()
        data = await manager.list_by_shop_receipt(
            shop_id, receipt_id, limit=limit, offset=offset
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_list_by_shop_receipt(%s,%s) failed: %s",
            shop_id, receipt_id, exc, exc_info=True,
        )
        return error_envelope(
            f"Failed to list listings for receipt {receipt_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_by_shop_receipt unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_list_by_shop_section",
    description="List listings within a specific shop section. Useful for auditing "
    "section coverage or moving listings between sections.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_by_shop_section(
    shop_id: int,
    shop_section_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List listings in a shop section."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_listing_manager()
        data = await manager.list_by_shop_section(
            shop_id, shop_section_id, limit=limit, offset=offset
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_list_by_shop_section(%s,%s) failed: %s",
            shop_id, shop_section_id, exc, exc_info=True,
        )
        return error_envelope(
            f"Failed to list listings for section {shop_section_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_by_shop_section unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_list_by_shop_return_policy",
    description="List listings that use a specific return policy. Useful for impact "
    "analysis before editing or deleting a return policy.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_by_shop_return_policy(
    shop_id: int,
    return_policy_id: int,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """List listings using a return policy."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_listing_manager()
        data = await manager.list_by_shop_return_policy(
            shop_id, return_policy_id, limit=limit, offset=offset
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_list_by_shop_return_policy(%s,%s) failed: %s",
            shop_id, return_policy_id, exc, exc_info=True,
        )
        return error_envelope(
            f"Failed to list listings for return policy {return_policy_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_by_shop_return_policy unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_list_by_ids",
    description="Bulk-fetch listings by a list of listing_ids. PRIMARY tool for "
    "competitor research — pass 1-100 listing IDs to read all of them in a single "
    "API call. Returns full listing details including tags, materials, attributes.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_by_ids(listing_ids: list[int]) -> dict[str, Any]:
    """Bulk-get listings by IDs."""
    try:
        if not listing_ids:
            return error_envelope("listing_ids must not be empty")
        if len(listing_ids) > 100:
            return error_envelope("listing_ids may contain at most 100 IDs per call")
        if not all(isinstance(i, int) for i in listing_ids):
            return error_envelope("listing_ids must all be integers")

        manager = get_listing_manager()
        data = await manager.list_by_ids(listing_ids)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listings_list_by_ids failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to bulk-fetch listings: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_by_ids unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_search_active",
    description="Public search across active Etsy listings by keyword and/or taxonomy. "
    "PRIMARY tool for competitor discovery and tag mining. Filters: keywords, taxonomy_id, "
    "min_price, max_price. Sort: score|price|created|updated; sort_order asc|desc. "
    "Max limit 100.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_search_active(
    keywords: str | None = None,
    taxonomy_id: int | None = None,
    limit: int = 25,
    offset: int = 0,
    min_price: float | None = None,
    max_price: float | None = None,
    sort_on: str | None = None,
    sort_order: str | None = None,
) -> dict[str, Any]:
    """Search active listings."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")
        if keywords is None and taxonomy_id is None:
            return error_envelope("at least one of keywords or taxonomy_id is required")
        if min_price is not None and min_price < 0:
            return error_envelope("min_price must be >= 0")
        if max_price is not None and max_price < 0:
            return error_envelope("max_price must be >= 0")
        if (
            min_price is not None
            and max_price is not None
            and min_price > max_price
        ):
            return error_envelope("min_price must be <= max_price")

        manager = get_listing_manager()
        data = await manager.search_active(
            keywords=keywords,
            taxonomy_id=taxonomy_id,
            limit=limit,
            offset=offset,
            min_price=min_price,
            max_price=max_price,
            sort_on=sort_on,
            sort_order=sort_order,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listings_search_active failed: %s", exc, exc_info=True)
        return error_envelope(f"Active listing search failed: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_search_active unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_get_featured",
    description="Get Etsy's featured listings. NOTE: this endpoint may not exist in "
    "Etsy v3 — if it returns 404 the tool returns a graceful error envelope.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_get_featured(
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Get featured listings."""
    try:
        if limit < 1 or limit > 100:
            return error_envelope("limit must be between 1 and 100")
        if offset < 0:
            return error_envelope("offset must be >= 0")

        manager = get_listing_manager()
        data = await manager.get_featured(limit=limit, offset=offset)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listings_get_featured failed: %s", exc, exc_info=True)
        return error_envelope(
            f"Failed to get featured listings (endpoint may not exist): {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_get_featured unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_get",
    description="Get a single listing by listing_id. Returns full listing detail "
    "including tags, materials, taxonomy_id, who_made, when_made, prices, etc.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_get(listing_id: int) -> dict[str, Any]:
    """Get a listing by ID."""
    try:
        manager = get_listing_manager()
        data = await manager.get(listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listings_get(%s) failed: %s", listing_id, exc, exc_info=True)
        return error_envelope(f"Failed to get listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid listing_id: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_list_translations",
    description="Get a listing's translation for a specific language code (e.g. 'fr', 'de'). "
    "Returns the translated title, description, tags. Requires shop_id + listing_id + language.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_translations(
    shop_id: int,
    listing_id: int,
    language: str,
) -> dict[str, Any]:
    """Get a listing's translation for a language."""
    try:
        if not language or not language.strip():
            return error_envelope("language must not be empty (e.g. 'fr', 'de', 'es')")

        manager = get_listing_manager()
        data = await manager.list_translations(shop_id, listing_id, language.strip())
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_list_translations(%s,%s,%s) failed: %s",
            shop_id, listing_id, language, exc, exc_info=True,
        )
        return error_envelope(
            f"Failed to get translation for listing {listing_id} ({language}): {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_translations unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_list_return_policies",
    description="List a shop's return policies. Use the returned return_policy_id values "
    "when creating or updating listings that need a return policy attached.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listings",
    permission_action="READ",
)
async def etsy_listings_list_return_policies(shop_id: int) -> dict[str, Any]:
    """List shop return policies."""
    try:
        manager = get_listing_manager()
        data = await manager.list_return_policies(shop_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_list_return_policies(%s) failed: %s",
            shop_id, exc, exc_info=True,
        )
        return error_envelope(
            f"Failed to list return policies for shop {shop_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_list_return_policies unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# =============================================================================
# WRITE tools (preview-then-confirm)
# =============================================================================


@server.tool(
    name="etsy_listings_create_draft",
    description="Create a single draft listing in a shop. Required: shop_id, title, "
    "description, price, quantity, taxonomy_id, who_made (i_did|collective|someone_else), "
    "when_made (Etsy enum), is_supply. Optional: tags (max 13), materials (max 13), "
    "shipping_profile_id, shop_section_id. With confirm=False (default), returns a preview. "
    "With confirm=True, creates the listing in DRAFT state.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="CREATE",
)
async def etsy_listings_create_draft(
    shop_id: int,
    title: str,
    description: str,
    price: float,
    quantity: int,
    taxonomy_id: int,
    who_made: str,
    when_made: str,
    is_supply: bool,
    tags: list[str] | None = None,
    materials: list[str] | None = None,
    shipping_profile_id: int | None = None,
    shop_section_id: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a draft listing."""
    try:
        # Validate against the same template the bulk path uses so that
        # single-listing creates and bulk creates have identical semantics.
        try:
            template = ListingTemplate(
                title=title,
                description=description,
                price=price,
                quantity=quantity,
                taxonomy_id=taxonomy_id,
                who_made=who_made,  # type: ignore[arg-type]
                when_made=when_made,
                is_supply=is_supply,
                tags=tags or [],
                materials=materials or [],
                shipping_profile_id=shipping_profile_id,
                shop_section_id=shop_section_id,
            )
        except ValidationError as exc:
            return error_envelope(f"Listing validation failed: {exc}")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "listing",
                "resource_id": "(new)",
                "preview": {
                    "shop_id": shop_id,
                    "proposed": template.to_create_payload(),
                    "state_after_create": "draft",
                },
                "message": (
                    f"Will create draft listing '{title}' in shop {shop_id}. "
                    f"Listing will be created in DRAFT state (not visible until activated). "
                    f"Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        payload = template.to_create_payload()
        data = await manager.create_draft(shop_id, **payload)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listings_create_draft failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to create draft listing: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_create_draft unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_bulk_create_from_template",
    description="BULK PRIMITIVE: Create multiple draft listings from a list of templates. "
    "Each template must be a dict with the ListingTemplate shape (title, description, "
    "price, quantity, taxonomy_id, who_made, when_made, is_supply, optional tags/materials/etc). "
    "Per-item error isolation — one bad template does NOT abort the batch. Returns a "
    "partial-success envelope with `created` and `failed` arrays. Listings are created in "
    "DRAFT state. Requires confirm=True. Preview shows count + sample rendering.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="CREATE",
)
async def etsy_listings_bulk_create_from_template(
    shop_id: int,
    templates: list[dict[str, Any]],
    confirm: bool = False,
) -> dict[str, Any]:
    """Bulk create draft listings from templates."""
    try:
        if not templates:
            return error_envelope("templates must not be empty")
        if not isinstance(templates, list):
            return error_envelope("templates must be a list of dicts")
        if len(templates) > 100:
            return error_envelope(
                "templates list may contain at most 100 entries per call "
                "(rate-limit safety)"
            )

        # Validate all templates up front to surface schema errors before
        # we even hit the API. Validation errors here block the entire call.
        validated: list[ListingTemplate] = []
        validation_errors: list[dict[str, Any]] = []
        for idx, raw in enumerate(templates):
            try:
                validated.append(ListingTemplate(**raw))
            except ValidationError as exc:
                validation_errors.append(
                    {
                        "index": idx,
                        "title": raw.get("title") if isinstance(raw, dict) else None,
                        "error": str(exc),
                    }
                )

        if validation_errors:
            return error_envelope(
                f"{len(validation_errors)} of {len(templates)} templates failed validation. "
                f"Fix and retry. No listings were created.",
                detail={"validation_errors": validation_errors},
            )

        if not confirm:
            sample = validated[0].to_create_payload() if validated else None
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "bulk_create",
                "resource_type": "listing",
                "resource_id": f"({len(validated)} new)",
                "preview": {
                    "shop_id": shop_id,
                    "count": len(validated),
                    "sample_rendered": sample,
                    "all_titles": [t.title for t in validated],
                    "state_after_create": "draft",
                },
                "warnings": [
                    f"Will create {len(validated)} draft listings in shop {shop_id}.",
                    "All listings start in DRAFT state (not visible until activated).",
                    "Per-item error isolation: partial failures will return a partial-success envelope.",
                    "Image uploads, properties, and inventory are NOT handled here — call those tools after.",
                ],
                "message": (
                    f"Will bulk-create {len(validated)} draft listings in shop {shop_id}. "
                    f"Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        result = await manager.bulk_create_from_template(
            shop_id, [t.model_dump() for t in validated]
        )
        return partial_success_envelope(
            created=result["created"],
            failed=result["failed"],
            rate_limit=get_client().rate_limit_status(),
        )
    except EtsyError as exc:
        logger.error("etsy_listings_bulk_create_from_template failed: %s", exc, exc_info=True)
        return error_envelope(f"Bulk create failed: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_bulk_create_from_template unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_update",
    description="Update a single listing's mutable fields with fetch-merge-PATCH. "
    "Pass only the fields you want to change — current values are preserved. "
    "After PATCH, the tool polls Etsy with a backoff (0.5s, 1s, 2s) to verify the "
    "applied state and surfaces any divergence. With confirm=False (default), returns "
    "a diff preview. With confirm=True, executes the update and returns "
    "{requested, applied, diverged, ignored, warnings}.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="UPDATE",
)
async def etsy_listings_update(
    shop_id: int,
    listing_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a listing with fetch-merge-put + verification."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")
        if not isinstance(updates, dict):
            return error_envelope("updates must be a dict of field_name -> new_value")

        # Surface rejected fields immediately so the caller knows what's allowed
        rejected = [k for k in updates.keys() if k not in MUTABLE_FIELDS]
        allowed = {k: v for k, v in updates.items() if k in MUTABLE_FIELDS}
        if not allowed:
            return error_envelope(
                f"No mutable fields in updates. Rejected: {rejected}. "
                f"Allowed fields: {sorted(MUTABLE_FIELDS)}"
            )

        manager = get_listing_manager()

        if not confirm:
            # Preview: fetch current state and show diff
            current = await manager.get(listing_id)
            current_relevant = {k: current.get(k) for k in allowed.keys()}
            warnings = []
            if rejected:
                warnings.append(
                    f"These fields will be IGNORED (not in mutable set): {rejected}"
                )
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "listing",
                "resource_id": str(listing_id),
                "preview": {
                    "current": current_relevant,
                    "proposed": allowed,
                    "rejected_fields": rejected,
                },
                "warnings": warnings,
                "message": (
                    f"Will update {sorted(allowed.keys())} on listing {listing_id}. "
                    f"Set confirm=true to execute."
                ),
            }

        result = await manager.update(shop_id, listing_id, updates)
        return update_with_verification_envelope(
            requested=result["requested"],
            applied=result["applied"],
            diverged=result["diverged"],
            ignored=result["ignored"],
            warnings=result["warnings"],
            rate_limit=get_client().rate_limit_status(),
        )
    except EtsyError as exc:
        logger.error(
            "etsy_listings_update(%s,%s) failed: %s",
            shop_id, listing_id, exc, exc_info=True,
        )
        return error_envelope(f"Failed to update listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_bulk_update_from_template",
    description="BULK PRIMITIVE: Update multiple listings via per-listing fetch-merge-PATCH. "
    "Each entry must be {listing_id: int, patch_fields: dict}. Per-listing error isolation. "
    "Returns a partial-success envelope with `updated` (each carrying applied/diverged/ignored) "
    "and `failed` arrays. Used for catalog-wide SEO refresh workflows. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="UPDATE",
)
async def etsy_listings_bulk_update_from_template(
    shop_id: int,
    updates: list[dict[str, Any]],
    confirm: bool = False,
) -> dict[str, Any]:
    """Bulk update listings via fetch-merge-put."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")
        if not isinstance(updates, list):
            return error_envelope("updates must be a list of {listing_id, patch_fields} dicts")
        if len(updates) > 100:
            return error_envelope(
                "updates list may contain at most 100 entries per call (rate-limit safety)"
            )

        # Pre-validate shapes
        shape_errors: list[dict[str, Any]] = []
        for idx, entry in enumerate(updates):
            if not isinstance(entry, dict):
                shape_errors.append({"index": idx, "error": "entry must be a dict"})
                continue
            if not isinstance(entry.get("listing_id"), int):
                shape_errors.append({"index": idx, "error": "listing_id (int) is required"})
                continue
            patch = entry.get("patch_fields")
            if not patch or not isinstance(patch, dict):
                shape_errors.append(
                    {"index": idx, "error": "patch_fields (non-empty dict) is required"}
                )
                continue
            invalid = [k for k in patch.keys() if k not in MUTABLE_FIELDS]
            if invalid and not any(k in MUTABLE_FIELDS for k in patch.keys()):
                shape_errors.append(
                    {
                        "index": idx,
                        "listing_id": entry.get("listing_id"),
                        "error": f"all patch_fields are non-mutable: {invalid}",
                    }
                )

        if shape_errors:
            return error_envelope(
                f"{len(shape_errors)} of {len(updates)} entries failed shape validation. "
                f"Fix and retry. No listings were updated.",
                detail={"shape_errors": shape_errors},
            )

        if not confirm:
            # Sample preview: fetch current state for the first listing and
            # render a diff so the caller can see the shape of what will happen.
            sample_diff = None
            try:
                manager = get_listing_manager()
                first = updates[0]
                current = await manager.get(first["listing_id"])
                sample_diff = {
                    "listing_id": first["listing_id"],
                    "current": {k: current.get(k) for k in first["patch_fields"].keys()},
                    "proposed": first["patch_fields"],
                }
            except EtsyError as exc:
                logger.warning("preview sample fetch failed: %s", exc)
                sample_diff = {"error": f"sample fetch failed: {exc.message}"}

            return {
                "success": True,
                "requires_confirmation": True,
                "action": "bulk_update",
                "resource_type": "listing",
                "resource_id": f"({len(updates)} listings)",
                "preview": {
                    "shop_id": shop_id,
                    "count": len(updates),
                    "listing_ids": [u["listing_id"] for u in updates],
                    "sample_diff": sample_diff,
                },
                "warnings": [
                    f"Will update {len(updates)} listings via per-listing fetch-merge-PATCH.",
                    "Per-item error isolation: partial failures return a partial-success envelope.",
                    "Each listing is verified post-update; divergence is surfaced per listing.",
                    "Non-mutable fields in patch_fields will be silently dropped.",
                ],
                "message": (
                    f"Will bulk-update {len(updates)} listings in shop {shop_id}. "
                    f"Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        result = await manager.bulk_update_from_template(shop_id, updates)
        return partial_success_envelope(
            updated=result["updated"],
            failed=result["failed"],
            rate_limit=get_client().rate_limit_status(),
        )
    except EtsyError as exc:
        logger.error("etsy_listings_bulk_update_from_template failed: %s", exc, exc_info=True)
        return error_envelope(f"Bulk update failed: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error(
            "etsy_listings_bulk_update_from_template unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_delete",
    description="DELETE a listing. DESTRUCTIVE and IRREVERSIBLE. The listing is permanently "
    "removed from the shop. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="DELETE",
)
async def etsy_listings_delete(
    shop_id: int,
    listing_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "listing",
                "resource_id": str(listing_id),
                "warnings": [
                    "DELETE is permanent and irreversible.",
                    "All listing images, videos, inventory, and translations are removed.",
                    "Existing receipts that reference this listing will retain their snapshot data.",
                ],
                "message": (
                    f"Will DELETE listing {listing_id} from shop {shop_id}. "
                    f"This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        data = await manager.delete(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_delete(%s,%s) failed: %s",
            shop_id, listing_id, exc, exc_info=True,
        )
        return error_envelope(f"Failed to delete listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_activate",
    description="Activate a listing (state=active). Makes the listing publicly visible "
    "and available for purchase. Requires confirm=True. Reversible via deactivate.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="UPDATE",
)
async def etsy_listings_activate(
    shop_id: int,
    listing_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Activate a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "activate",
                "resource_type": "listing",
                "resource_id": str(listing_id),
                "warnings": [
                    "Listing will become publicly visible and purchasable.",
                    "Activation may consume a listing fee depending on shop billing.",
                ],
                "message": (
                    f"Will ACTIVATE listing {listing_id} in shop {shop_id}. "
                    f"Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        data = await manager.activate(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_activate(%s,%s) failed: %s",
            shop_id, listing_id, exc, exc_info=True,
        )
        return error_envelope(f"Failed to activate listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_activate unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_deactivate",
    description="Deactivate a listing (state=inactive). REVENUE IMPACT — listing is no "
    "longer purchasable. Reversible via activate. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,  # revenue impact
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="UPDATE",
)
async def etsy_listings_deactivate(
    shop_id: int,
    listing_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Deactivate a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "deactivate",
                "resource_type": "listing",
                "resource_id": str(listing_id),
                "warnings": [
                    "REVENUE IMPACT: Listing will no longer be purchasable.",
                    "Listing remains in the shop and can be re-activated.",
                    "Existing carts containing this listing may be affected.",
                ],
                "message": (
                    f"Will DEACTIVATE listing {listing_id} in shop {shop_id}. "
                    f"This has revenue impact. Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        data = await manager.deactivate(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_deactivate(%s,%s) failed: %s",
            shop_id, listing_id, exc, exc_info=True,
        )
        return error_envelope(f"Failed to deactivate listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_deactivate unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_copy",
    description="Copy an existing listing into a new draft listing. The copy inherits "
    "title/description/price/etc but starts in DRAFT state. Useful for creating variants "
    "of a successful listing. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="CREATE",
)
async def etsy_listings_copy(
    shop_id: int,
    listing_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Copy a listing into a new draft."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "copy",
                "resource_type": "listing",
                "resource_id": f"copy_of_{listing_id}",
                "preview": {
                    "source_listing_id": listing_id,
                    "shop_id": shop_id,
                    "state_after_copy": "draft",
                },
                "message": (
                    f"Will COPY listing {listing_id} into a new DRAFT listing in shop {shop_id}. "
                    f"Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        data = await manager.copy(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_copy(%s,%s) failed: %s",
            shop_id, listing_id, exc, exc_info=True,
        )
        return error_envelope(f"Failed to copy listing {listing_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listings_copy unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listings_update_variation_images",
    description="Update the variation_images mapping on a listing (which image shows "
    "for each property/value combination). variation_images is a list of dicts, each "
    "with property_id, value_id, image_id. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listings",
    permission_action="UPDATE",
)
async def etsy_listings_update_variation_images(
    shop_id: int,
    listing_id: int,
    variation_images: list[dict[str, Any]],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update variation images on a listing."""
    try:
        if not isinstance(variation_images, list):
            return error_envelope("variation_images must be a list of dicts")
        if not variation_images:
            return error_envelope("variation_images must not be empty")
        for idx, entry in enumerate(variation_images):
            if not isinstance(entry, dict):
                return error_envelope(f"variation_images[{idx}] must be a dict")
            for required in ("property_id", "value_id", "image_id"):
                if required not in entry:
                    return error_envelope(
                        f"variation_images[{idx}] missing required field '{required}'"
                    )

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update_variation_images",
                "resource_type": "listing",
                "resource_id": str(listing_id),
                "preview": {
                    "shop_id": shop_id,
                    "count": len(variation_images),
                    "proposed": variation_images,
                },
                "warnings": [
                    "This replaces the entire variation_images mapping for the listing.",
                    "Image IDs must already exist on the listing — upload images first via listing_images tools.",
                ],
                "message": (
                    f"Will update {len(variation_images)} variation image mappings on listing "
                    f"{listing_id}. Set confirm=true to execute."
                ),
            }

        manager = get_listing_manager()
        data = await manager.update_variation_images(shop_id, listing_id, variation_images)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listings_update_variation_images(%s,%s) failed: %s",
            shop_id, listing_id, exc, exc_info=True,
        )
        return error_envelope(
            f"Failed to update variation images on listing {listing_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error(
            "etsy_listings_update_variation_images unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
