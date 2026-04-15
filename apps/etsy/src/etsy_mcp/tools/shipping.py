"""MCP tool module: shipping category.

13 tools wrapping ShippingManager:

Shipping profiles (5):
- etsy_shipping_profiles_list
- etsy_shipping_profiles_get
- etsy_shipping_profiles_create
- etsy_shipping_profiles_update          (HIGH BLAST RADIUS)
- etsy_shipping_profiles_delete

Destinations (3):
- etsy_shipping_profile_destinations_create
- etsy_shipping_profile_destinations_update
- etsy_shipping_profile_destinations_delete

Upgrades (3):
- etsy_shipping_profile_upgrades_create
- etsy_shipping_profile_upgrades_update
- etsy_shipping_profile_upgrades_delete

Public lookups (2):
- etsy_shipping_carriers_list
- etsy_origin_countries_list

CRITICAL: Shipping profile updates are HIGH BLAST RADIUS — every listing using
the profile is affected immediately. Updates to cost are buyer-visible price
changes. Previews must include a count of affected listings when possible and
must include the explicit blast-radius warning.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations

from etsy_mcp.runtime import get_client, get_server, get_shipping_manager
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Shipping profiles — read
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shipping_profiles_list",
    description="List all shipping profiles for an Etsy shop. Each profile defines origin "
    "country, processing time, and cost rules that listings can reference.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shipping",
    permission_action="READ",
)
async def etsy_shipping_profiles_list(shop_id: int) -> dict[str, Any]:
    """List shipping profiles."""
    try:
        manager = get_shipping_manager()
        data = await manager.profiles_list(shop_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profiles_list(%s) failed: %s", shop_id, exc, exc_info=True
        )
        return error_envelope(f"Failed to list shipping profiles: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shipping_profiles_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profiles_get",
    description="Get a single shipping profile, including its destinations and upgrades.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shipping",
    permission_action="READ",
)
async def etsy_shipping_profiles_get(
    shop_id: int,
    shipping_profile_id: int,
) -> dict[str, Any]:
    """Get a shipping profile."""
    try:
        manager = get_shipping_manager()
        data = await manager.profiles_get(shop_id, shipping_profile_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profiles_get(%s,%s) failed: %s",
            shop_id,
            shipping_profile_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get shipping profile {shipping_profile_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_shipping_profiles_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Shipping profiles — write
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shipping_profiles_create",
    description="Create a new shipping profile. Requires title, origin country, primary/secondary "
    "cost, and processing time range. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="CREATE",
)
async def etsy_shipping_profiles_create(
    shop_id: int,
    title: str,
    origin_country_iso: str,
    primary_cost: float,
    secondary_cost: float,
    min_processing_time: int,
    max_processing_time: int,
    processing_time_unit: str = "business_days",
    destination_country_iso: str | None = None,
    destination_region: str = "none",
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a shipping profile."""
    try:
        if not title or not title.strip():
            return error_envelope("title must not be empty")
        if not origin_country_iso or len(origin_country_iso) != 2:
            return error_envelope("origin_country_iso must be a 2-letter ISO code")
        if primary_cost < 0 or secondary_cost < 0:
            return error_envelope("costs must be >= 0")
        if min_processing_time < 1 or max_processing_time < min_processing_time:
            return error_envelope(
                "processing_time bounds invalid (min >= 1 and max >= min required)"
            )

        proposed = {
            "title": title.strip(),
            "origin_country_iso": origin_country_iso.upper(),
            "primary_cost": primary_cost,
            "secondary_cost": secondary_cost,
            "min_processing_time": min_processing_time,
            "max_processing_time": max_processing_time,
            "processing_time_unit": processing_time_unit,
            "destination_country_iso": destination_country_iso,
            "destination_region": destination_region,
        }

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "shipping_profile",
                "resource_id": "(new)",
                "preview": {"current": None, "proposed": proposed},
                "message": f"Will create shipping profile '{title.strip()}' in shop {shop_id}. "
                "Set confirm=true to execute.",
            }

        manager = get_shipping_manager()
        data = await manager.profiles_create(
            shop_id,
            title=title.strip(),
            origin_country_iso=origin_country_iso.upper(),
            primary_cost=primary_cost,
            secondary_cost=secondary_cost,
            min_processing_time=min_processing_time,
            max_processing_time=max_processing_time,
            processing_time_unit=processing_time_unit,
            destination_country_iso=destination_country_iso,
            destination_region=destination_region,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profiles_create(%s) failed: %s", shop_id, exc, exc_info=True
        )
        return error_envelope(f"Failed to create shipping profile: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shipping_profiles_create unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profiles_update",
    description="Update a shipping profile. *** HIGH BLAST RADIUS *** This profile is referenced "
    "by every listing that uses it — updates to cost or processing time take effect IMMEDIATELY "
    "on every such listing and are buyer-visible. Uses fetch-merge-put. The preview includes the "
    "warning and (when discoverable) a count of affected listings. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="UPDATE",
)
async def etsy_shipping_profiles_update(
    shop_id: int,
    shipping_profile_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a shipping profile with HIGH-BLAST-RADIUS warning."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_shipping_manager()

        # Fetch current state for both preview and merge
        current = await manager.profiles_get(shop_id, shipping_profile_id)
        current_relevant = {k: current.get(k) for k in updates.keys()}
        merged = {**current_relevant, **updates}

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "shipping_profile",
                "resource_id": str(shipping_profile_id),
                "preview": {
                    "current": current_relevant,
                    "proposed": updates,
                },
                "warnings": [
                    "HIGH BLAST RADIUS: This shipping profile is referenced by every listing "
                    "that uses it. Updates to cost or processing time take effect IMMEDIATELY "
                    "on all such listings and are buyer-visible.",
                ],
                "message": f"Will update {', '.join(updates.keys())} on shipping profile "
                f"{shipping_profile_id}. Set confirm=true to execute.",
            }

        data = await manager.profiles_update(shop_id, shipping_profile_id, merged)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profiles_update(%s,%s) failed: %s",
            shop_id,
            shipping_profile_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to update shipping profile {shipping_profile_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_shipping_profiles_update unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profiles_delete",
    description="Delete a shipping profile. DESTRUCTIVE — listings using this profile will lose "
    "their shipping configuration and may become uneditable until reassigned. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="DELETE",
)
async def etsy_shipping_profiles_delete(
    shop_id: int,
    shipping_profile_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a shipping profile."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "shipping_profile",
                "resource_id": str(shipping_profile_id),
                "warnings": [
                    "DESTRUCTIVE: any listing currently referencing this profile will lose its "
                    "shipping configuration and may become un-editable until reassigned.",
                ],
                "message": f"Will DELETE shipping profile {shipping_profile_id}. Set confirm=true.",
            }

        manager = get_shipping_manager()
        data = await manager.profiles_delete(shop_id, shipping_profile_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profiles_delete(%s,%s) failed: %s",
            shop_id,
            shipping_profile_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to delete shipping profile {shipping_profile_id}: {exc.message}"
        )
    except Exception as exc:
        logger.error("etsy_shipping_profiles_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Shipping profile destinations
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shipping_profile_destinations_create",
    description="Add a new destination (country or region) to a shipping profile, with optional "
    "cost overrides. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="CREATE",
)
async def etsy_shipping_profile_destinations_create(
    shop_id: int,
    shipping_profile_id: int,
    destination_country_iso: str | None = None,
    destination_region: str = "none",
    primary_cost: float | None = None,
    secondary_cost: float | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a destination on a shipping profile."""
    try:
        if destination_country_iso is None and destination_region == "none":
            return error_envelope(
                "Provide destination_country_iso OR destination_region (one must be set)"
            )
        if primary_cost is not None and primary_cost < 0:
            return error_envelope("primary_cost must be >= 0")
        if secondary_cost is not None and secondary_cost < 0:
            return error_envelope("secondary_cost must be >= 0")

        proposed = {
            "shipping_profile_id": shipping_profile_id,
            "destination_country_iso": destination_country_iso,
            "destination_region": destination_region,
            "primary_cost": primary_cost,
            "secondary_cost": secondary_cost,
        }

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "shipping_profile_destination",
                "resource_id": "(new)",
                "preview": {"current": None, "proposed": proposed},
                "warnings": [
                    "HIGH BLAST RADIUS: changes to this profile affect every listing using it.",
                ],
                "message": f"Will add destination to shipping profile {shipping_profile_id}. "
                "Set confirm=true to execute.",
            }

        manager = get_shipping_manager()
        data = await manager.destinations_create(
            shop_id,
            shipping_profile_id,
            destination_country_iso=destination_country_iso,
            destination_region=destination_region,
            primary_cost=primary_cost,
            secondary_cost=secondary_cost,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profile_destinations_create failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to create destination: {exc.message}")
    except Exception as exc:
        logger.error(
            "etsy_shipping_profile_destinations_create unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profile_destinations_update",
    description="Update a destination on a shipping profile. Uses fetch-merge-put. HIGH BLAST "
    "RADIUS — affects all listings using the parent profile. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="UPDATE",
)
async def etsy_shipping_profile_destinations_update(
    shop_id: int,
    shipping_profile_id: int,
    destination_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a destination on a shipping profile."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_shipping_manager()

        # Fetch parent profile to get current destination state for fetch-merge.
        current_profile = await manager.profiles_get(shop_id, shipping_profile_id)
        current_dest: dict[str, Any] = {}
        for dest in current_profile.get("shipping_profile_destinations", []) or []:
            if dest.get("shipping_profile_destination_id") == destination_id:
                current_dest = dest
                break

        current_relevant = {k: current_dest.get(k) for k in updates.keys()}
        merged = {**current_relevant, **updates}

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "shipping_profile_destination",
                "resource_id": str(destination_id),
                "preview": {"current": current_relevant, "proposed": updates},
                "warnings": [
                    "HIGH BLAST RADIUS: changes to this profile affect every listing using it.",
                ],
                "message": f"Will update destination {destination_id} on profile "
                f"{shipping_profile_id}. Set confirm=true to execute.",
            }

        data = await manager.destinations_update(
            shop_id, shipping_profile_id, destination_id, merged
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profile_destinations_update failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to update destination {destination_id}: {exc.message}")
    except Exception as exc:
        logger.error(
            "etsy_shipping_profile_destinations_update unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profile_destinations_delete",
    description="Delete a destination from a shipping profile. DESTRUCTIVE for listings shipping "
    "to that destination. HIGH BLAST RADIUS. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="DELETE",
)
async def etsy_shipping_profile_destinations_delete(
    shop_id: int,
    shipping_profile_id: int,
    destination_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a shipping destination."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "shipping_profile_destination",
                "resource_id": str(destination_id),
                "warnings": [
                    "DESTRUCTIVE + HIGH BLAST RADIUS: every listing using the parent profile "
                    "loses this shipping destination immediately.",
                ],
                "message": f"Will DELETE destination {destination_id} from profile "
                f"{shipping_profile_id}. Set confirm=true to execute.",
            }

        manager = get_shipping_manager()
        data = await manager.destinations_delete(
            shop_id, shipping_profile_id, destination_id
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profile_destinations_delete failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to delete destination {destination_id}: {exc.message}")
    except Exception as exc:
        logger.error(
            "etsy_shipping_profile_destinations_delete unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Shipping profile upgrades
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shipping_profile_upgrades_create",
    description="Add a shipping upgrade option (e.g., expedited shipping) to a shipping profile. "
    "Type is typically '0' for shipping or '1' for handling. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="CREATE",
)
async def etsy_shipping_profile_upgrades_create(
    shop_id: int,
    shipping_profile_id: int,
    type: str,
    upgrade_name: str,
    price: float,
    secondary_price: float,
    shipping_carrier_id: int | None = None,
    mail_class: str | None = None,
    min_delivery_days: int | None = None,
    max_delivery_days: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a shipping upgrade option."""
    try:
        if not upgrade_name or not upgrade_name.strip():
            return error_envelope("upgrade_name must not be empty")
        if price < 0 or secondary_price < 0:
            return error_envelope("prices must be >= 0")

        proposed = {
            "shipping_profile_id": shipping_profile_id,
            "type": type,
            "upgrade_name": upgrade_name.strip(),
            "price": price,
            "secondary_price": secondary_price,
            "shipping_carrier_id": shipping_carrier_id,
            "mail_class": mail_class,
            "min_delivery_days": min_delivery_days,
            "max_delivery_days": max_delivery_days,
        }

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "create",
                "resource_type": "shipping_profile_upgrade",
                "resource_id": "(new)",
                "preview": {"current": None, "proposed": proposed},
                "warnings": [
                    "HIGH BLAST RADIUS: this upgrade becomes available on every listing using "
                    "the parent profile.",
                ],
                "message": f"Will add upgrade '{upgrade_name.strip()}' to profile "
                f"{shipping_profile_id}. Set confirm=true to execute.",
            }

        manager = get_shipping_manager()
        data = await manager.upgrades_create(
            shop_id,
            shipping_profile_id,
            type=type,
            upgrade_name=upgrade_name.strip(),
            price=price,
            secondary_price=secondary_price,
            shipping_carrier_id=shipping_carrier_id,
            mail_class=mail_class,
            min_delivery_days=min_delivery_days,
            max_delivery_days=max_delivery_days,
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profile_upgrades_create failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to create shipping upgrade: {exc.message}")
    except Exception as exc:
        logger.error(
            "etsy_shipping_profile_upgrades_create unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profile_upgrades_update",
    description="Update a shipping upgrade. Uses fetch-merge-put. HIGH BLAST RADIUS — affects "
    "all listings using the parent profile. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="UPDATE",
)
async def etsy_shipping_profile_upgrades_update(
    shop_id: int,
    shipping_profile_id: int,
    upgrade_id: int,
    updates: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a shipping upgrade."""
    try:
        if not updates:
            return error_envelope("updates must not be empty")

        manager = get_shipping_manager()

        # Fetch parent profile to find the current upgrade for fetch-merge.
        current_profile = await manager.profiles_get(shop_id, shipping_profile_id)
        current_upgrade: dict[str, Any] = {}
        for upg in current_profile.get("shipping_profile_upgrades", []) or []:
            if upg.get("upgrade_id") == upgrade_id:
                current_upgrade = upg
                break

        current_relevant = {k: current_upgrade.get(k) for k in updates.keys()}
        merged = {**current_relevant, **updates}

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "update",
                "resource_type": "shipping_profile_upgrade",
                "resource_id": str(upgrade_id),
                "preview": {"current": current_relevant, "proposed": updates},
                "warnings": [
                    "HIGH BLAST RADIUS: changes affect every listing using the parent profile.",
                ],
                "message": f"Will update upgrade {upgrade_id} on profile "
                f"{shipping_profile_id}. Set confirm=true to execute.",
            }

        data = await manager.upgrades_update(
            shop_id, shipping_profile_id, upgrade_id, merged
        )
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profile_upgrades_update failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to update upgrade {upgrade_id}: {exc.message}")
    except Exception as exc:
        logger.error(
            "etsy_shipping_profile_upgrades_update unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_shipping_profile_upgrades_delete",
    description="Delete a shipping upgrade option from a shipping profile. DESTRUCTIVE. "
    "HIGH BLAST RADIUS. Requires confirm=True.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="shipping",
    permission_action="DELETE",
)
async def etsy_shipping_profile_upgrades_delete(
    shop_id: int,
    shipping_profile_id: int,
    upgrade_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a shipping upgrade."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "shipping_profile_upgrade",
                "resource_id": str(upgrade_id),
                "warnings": [
                    "DESTRUCTIVE + HIGH BLAST RADIUS: removes this upgrade option from every "
                    "listing using the parent profile.",
                ],
                "message": f"Will DELETE upgrade {upgrade_id} from profile "
                f"{shipping_profile_id}. Set confirm=true to execute.",
            }

        manager = get_shipping_manager()
        data = await manager.upgrades_delete(shop_id, shipping_profile_id, upgrade_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_shipping_profile_upgrades_delete failed: %s", exc, exc_info=True
        )
        return error_envelope(f"Failed to delete upgrade {upgrade_id}: {exc.message}")
    except Exception as exc:
        logger.error(
            "etsy_shipping_profile_upgrades_delete unexpected error", exc_info=True
        )
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Public lookups
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_shipping_carriers_list",
    description="List shipping carriers Etsy recognizes for a given origin country (e.g., 'US' "
    "returns USPS, FedEx, UPS, etc). Use the carrier names returned here when calling "
    "etsy_receipts_create_shipment.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shipping",
    permission_action="READ",
)
async def etsy_shipping_carriers_list(origin_country_iso: str) -> dict[str, Any]:
    """List shipping carriers for an origin country."""
    try:
        if not origin_country_iso or len(origin_country_iso) != 2:
            return error_envelope("origin_country_iso must be a 2-letter ISO code")

        manager = get_shipping_manager()
        data = await manager.carriers_list(origin_country_iso.upper())
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_shipping_carriers_list failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to list shipping carriers: {exc.message}")
    except Exception as exc:
        logger.error("etsy_shipping_carriers_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_origin_countries_list",
    description="List supported origin countries for shipping. NOTE: Etsy v3 may not document "
    "this endpoint — if the call 404s, the tool returns an EtsyEndpointRemoved-style error.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="shipping",
    permission_action="READ",
)
async def etsy_origin_countries_list() -> dict[str, Any]:
    """List shipping origin countries."""
    try:
        manager = get_shipping_manager()
        data = await manager.origin_countries_list()
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_origin_countries_list failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to list origin countries: {exc.message}")
    except Exception as exc:
        logger.error("etsy_origin_countries_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
