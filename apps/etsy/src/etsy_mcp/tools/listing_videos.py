"""MCP tool module: listing_videos category.

4 tools:
- etsy_listing_videos_list
- etsy_listing_videos_get
- etsy_listing_videos_upload   (multipart, size warning in preview, destructive=False)
- etsy_listing_videos_delete   (destructive + confirm)

All tools are thin wrappers: validate args -> delegate to VideoManager ->
format envelope -> return. Exceptions are caught and returned as error envelopes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from etsy_core.exceptions import EtsyError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from etsy_mcp.runtime import get_client, get_server, get_video_manager
from etsy_mcp.schemas import error_envelope, success_envelope

logger = logging.getLogger(__name__)

server = get_server()


# -----------------------------------------------------------------------------
# Read tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_videos_list",
    description="List all videos attached to an Etsy listing. Returns video_id, height, width, "
    "thumbnail_url, video_url, and state for each.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_videos",
    permission_action="READ",
)
async def etsy_listing_videos_list(shop_id: int, listing_id: int) -> dict[str, Any]:
    """List videos for a listing."""
    try:
        manager = get_video_manager()
        data = await manager.list(shop_id, listing_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error(
            "etsy_listing_videos_list(%s, %s) failed: %s",
            shop_id,
            listing_id,
            exc,
            exc_info=True,
        )
        return error_envelope(f"Failed to list videos: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_videos_list unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_videos_get",
    description="Get a single video on a listing by video_id.",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
    permission_category="listing_videos",
    permission_action="READ",
)
async def etsy_listing_videos_get(
    shop_id: int,
    listing_id: int,
    video_id: int,
) -> dict[str, Any]:
    """Get a video by id."""
    try:
        manager = get_video_manager()
        data = await manager.get(shop_id, listing_id, video_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_videos_get failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to get video {video_id}: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_videos_get unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


# -----------------------------------------------------------------------------
# Write tools
# -----------------------------------------------------------------------------


@server.tool(
    name="etsy_listing_videos_upload",
    description="Upload a video to an Etsy listing (multipart). With confirm=False (default), "
    "returns a preview showing the file size and target listing. With confirm=True, executes the upload. "
    "Etsy enforces video size and codec limits — large files may be rejected by the server.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    permission_category="listing_videos",
    permission_action="CREATE",
)
async def etsy_listing_videos_upload(
    shop_id: int,
    listing_id: int,
    file_path: str,
    name: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Upload a video to a listing."""
    try:
        if not file_path or not file_path.strip():
            return error_envelope("file_path must not be empty")

        path = Path(file_path).expanduser()
        if not path.exists() or not path.is_file():
            return error_envelope(f"File not found: {file_path}")

        size_bytes = path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        warnings: list[str] = []
        if size_mb > 100:
            warnings.append(
                f"File size is {size_mb:.1f} MB — Etsy may reject videos over its (undocumented) limit."
            )
        elif size_mb > 50:
            warnings.append(f"File size is {size_mb:.1f} MB — large upload, may be slow.")

        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "upload",
                "resource_type": "listing_video",
                "resource_id": "(new)",
                "preview": {
                    "current": None,
                    "proposed": {
                        "shop_id": shop_id,
                        "listing_id": listing_id,
                        "file_path": str(path),
                        "name": name,
                        "size_bytes": size_bytes,
                        "size_mb": round(size_mb, 2),
                    },
                },
                "warnings": warnings,
                "message": (
                    f"Will upload video '{path.name}' ({size_mb:.1f} MB) to listing "
                    f"{listing_id}. Set confirm=true to execute."
                ),
            }

        manager = get_video_manager()
        data = await manager.upload(
            shop_id,
            listing_id,
            file_path=str(path),
            name=name,
        )
        envelope = success_envelope(data, rate_limit=get_client().rate_limit_status())
        if warnings:
            envelope["warnings"] = warnings
        return envelope
    except EtsyError as exc:
        logger.error("etsy_listing_videos_upload failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to upload video: {exc.message}")
    except (ValidationError, ValueError, FileNotFoundError) as exc:
        return error_envelope(f"Invalid upload request: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_videos_upload unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")


@server.tool(
    name="etsy_listing_videos_delete",
    description="Delete a video from a listing. DESTRUCTIVE — the video is removed and cannot be "
    "recovered. Requires confirm=True to execute.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    ),
    permission_category="listing_videos",
    permission_action="DELETE",
)
async def etsy_listing_videos_delete(
    shop_id: int,
    listing_id: int,
    video_id: int,
    confirm: bool = False,
) -> dict[str, Any]:
    """Delete a video from a listing."""
    try:
        if not confirm:
            return {
                "success": True,
                "requires_confirmation": True,
                "action": "delete",
                "resource_type": "listing_video",
                "resource_id": str(video_id),
                "warnings": ["Video deletion is permanent and cannot be undone."],
                "message": (
                    f"Will DELETE video {video_id} from listing {listing_id}. "
                    f"This is destructive. Set confirm=true to execute."
                ),
            }

        manager = get_video_manager()
        data = await manager.delete(shop_id, listing_id, video_id)
        return success_envelope(data, rate_limit=get_client().rate_limit_status())
    except EtsyError as exc:
        logger.error("etsy_listing_videos_delete failed: %s", exc, exc_info=True)
        return error_envelope(f"Failed to delete video: {exc.message}")
    except (ValidationError, ValueError) as exc:
        return error_envelope(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.error("etsy_listing_videos_delete unexpected error", exc_info=True)
        return error_envelope(f"Unexpected error: {exc.__class__.__name__}")
