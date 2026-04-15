"""MCP tool module: listing_digital_files category.

4 tools:
- etsy_listing_digital_files_list
- etsy_listing_digital_files_get
- etsy_listing_digital_files_upload   (multipart, size warning in preview, destructive=False)
- etsy_listing_digital_files_delete   (destructive + confirm)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_digital_file_manager, get_server
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_digital_files_list",
    description="List all digital download files attached to an Etsy listing. Returns listing_file_id, "
    "filename, filesize, filesize_unit, rank, and create_timestamp for each.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_digital_files",
    permission_action="READ",
)
async def etsy_listing_digital_files_list(
    shop_id: int,
    listing_id: int,
) -> dict[str, Any]:
    """List digital files on a listing."""
    try:
        manager = get_digital_file_manager()
        data = await manager.list(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_digital_files_list(%s, %s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to list digital files: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_digital_files_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_digital_files_get",
    description="Get a single digital download file by listing_file_id.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_digital_files",
    permission_action="READ",
)
async def etsy_listing_digital_files_get(
    shop_id: int,
    listing_id: int,
    listing_file_id: int,
) -> dict[str, Any]:
    """Get a digital file by id."""
    try:
        manager = get_digital_file_manager()
        data = await manager.get(shop_id, listing_id, listing_file_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_digital_files_get failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to get digital file {listing_file_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_digital_files_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_digital_files_upload",
    description="Upload a digital download file to an Etsy listing (multipart). With confirm=False "
    "(default), returns a preview with file size and target listing. With confirm=True, executes the upload. "
    "Etsy enforces a per-file size cap (around 20 MB) and a per-listing total cap.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listing_digital_files",
    permission_action="CREATE",
)
async def etsy_listing_digital_files_upload(
    shop_id: int,
    listing_id: int,
    file_path: str,
    name: str | None = None,
    rank: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Upload a digital file to a listing."""
    try:
        if not file_path or not file_path.strip():
            return error_envelope("file_path must not be empty")

        path = Path(file_path).expanduser()
        if not path.exists() or not path.is_file():
            return error_envelope(f"File not found: {file_path}")

        size_bytes = path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        warnings: list[str] = []
        if size_mb > 20:
            warnings.append(
                f"File size is {size_mb:.1f} MB — Etsy's documented per-file limit is around 20 MB; "
                "the upload may be rejected."
            )
        elif size_mb > 15:
            warnings.append(
                f"File size is {size_mb:.1f} MB — close to Etsy's ~20 MB per-file limit."
            )

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "upload",
                "resource_type": "listing_digital_file",
                "resource_id": "(new)",
                "preview": {
                    "current": None,
                    "proposed": {
                        "shop_id": shop_id,
                        "listing_id": listing_id,
                        "file_path": str(path),
                        "name": name or path.name,
                        "rank": rank,
                        "size_bytes": size_bytes,
                        "size_mb": round(size_mb, 2),
                    },
                },
                "warnings": warnings,
                "message": (
                    f"Will upload digital file '{path.name}' ({size_mb:.1f} MB) to listing "
                    f"{listing_id}. Set confirm=true to execute."
                ),
            }

        manager = get_digital_file_manager()
        data = await manager.upload(
            shop_id,
            listing_id,
            file_path=str(path),
            name=name,
            rank=rank,
        )
        envelope = success_envelope(data, rate_limit=get_client().rate_limit_status())
        if warnings:
            envelope["warnings"] = warnings
        return envelope
    except EtsyError as exc:
        logger.error("etsy_listing_digital_files_upload failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to upload digital file: {exc.message}")
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        return error_envelope(f"Invalid upload request: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_digital_files_upload unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_digital_files_delete",
    description="Delete a digital download file from a listing. DESTRUCTIVE — the file is removed and "
    "buyers who have not yet downloaded it will lose access. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_digital_files",
    permission_action="DELETE",
)
async def etsy_listing_digital_files_delete(
    shop_id: int,
    listing_id: int,
    listing_file_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a digital file from a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "listing_digital_file",
                "resource_id": str(listing_file_id),
                "warnings": [
                    "Buyers who have not yet downloaded this file will lose access.",
                    "Digital file deletion is permanent and cannot be undone.",
                ],
                "message": (
                    f"Will DELETE digital file {listing_file_id} from listing {listing_id}. "
                    f"This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_digital_file_manager()
        data = await manager.delete(shop_id, listing_id, listing_file_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_digital_files_delete failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to delete digital file: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_digital_files_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
