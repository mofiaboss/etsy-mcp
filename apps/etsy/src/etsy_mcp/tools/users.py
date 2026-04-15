"""MCP tool module: users category.

5 tools:
- etsy_user_get_me              (profile_r)
- etsy_user_get_by_id           (profile_r)
- etsy_user_addresses_list      (address_r)
- etsy_user_addresses_get       (address_r)
- etsy_user_addresses_delete    (address_w, destructive, confirm required)
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_server, get_user_manager
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()

# -----------------------------------------------------------------------------
# Read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_user_get_me",
    description="Get the authenticated user's profile. Returns user_id, login_name, primary_email, "
    "creation timestamp, etc. Requires the profile_r OAuth scope. Use this to discover your own "
    "user_id for subsequent calls.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="users",
    permission_action="READ",
)
async def etsy_user_get_me() -> dict[str, Any]:
    """Get the authenticated user."""
    try:
        manager = get_user_manager()
        data = await manager.get_me()
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_user_get_me failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to get current user: {exc.message}")
    except Exception as exc:
        logger.error("etsy_user_get_me unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_user_get_by_id",
    description="Get an Etsy user by their user_id. Returns public profile fields. Requires the "
    "profile_r OAuth scope.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="users",
    permission_action="READ",
)
async def etsy_user_get_by_id(user_id: int) -> dict[str, Any]:
    """Get a user by user_id."""
    try:
        manager = get_user_manager()
        data = await manager.get_by_id(user_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_user_get_by_id(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(f"Failed to get user {user_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid user_id: {exc}")
    except Exception as exc:
        logger.error("etsy_user_get_by_id unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_user_addresses_list",
    description="List all saved shipping addresses for a user. Requires the address_r OAuth scope. "
    "Address data includes name, street, city, state, zip, country — treated as sensitive by F3 redaction.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="users",
    permission_action="READ",
)
async def etsy_user_addresses_list(user_id: int) -> dict[str, Any]:
    """List user addresses."""
    try:
        manager = get_user_manager()
        data = await manager.addresses_list(user_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_user_addresses_list(%s) failed: %s", user_id, exc, exc_info=True)
        return error_envelope(f"Failed to list addresses for user {user_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid user_id: {exc}")
    except Exception as exc:
        logger.error("etsy_user_addresses_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_user_addresses_get",
    description="Get a specific saved shipping address by user_address_id. Requires the address_r "
    "OAuth scope. Address fields are subject to F3 redaction.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="users",
    permission_action="READ",
)
async def etsy_user_addresses_get(
    user_id: int,
    user_address_id: int,
) -> dict[str, Any]:
    """Get a user address."""
    try:
        manager = get_user_manager()
        data = await manager.addresses_get(user_id, user_address_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_user_addresses_get(%s, %s) failed: %s",
            user_id,
            user_address_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to get address {user_address_id} for user {user_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_user_addresses_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_user_addresses_delete",
    description="Delete a saved shipping address. DESTRUCTIVE and irreversible. Requires the "
    "address_w OAuth scope. With confirm=False (default), returns a preview. With confirm=True, "
    "executes the deletion.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="users",
    permission_action="DELETE",
)
async def etsy_user_addresses_delete(
    user_id: int,
    user_address_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a user address."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "user_address",
                "resource_id": str(user_address_id),
                "warnings": [
                    "Deletion is permanent. The address cannot be recovered after deletion.",
                ],
                "preview": {
                    "user_id": user_id,
                    "user_address_id": user_address_id,
                },
                "message": (
                    f"Will DELETE user_address {user_address_id} for user {user_id}. "
                    "This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_user_manager()
        data = await manager.addresses_delete(user_id, user_address_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_user_addresses_delete(%s, %s) failed: %s",
            user_id,
            user_address_id,
            exc,
            exc_info=True,
        )
        return error_envelope(
            f"Failed to delete address {user_address_id}: {exc.message}"
        )
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid input: {exc}")
    except Exception as exc:
        logger.error("etsy_user_addresses_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
