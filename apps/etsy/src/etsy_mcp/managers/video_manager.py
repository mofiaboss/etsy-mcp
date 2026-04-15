"""Video manager — wraps Etsy ListingVideo endpoints.

4 operations:
- list: list all videos on a listing
- get: get a single video by id
- upload: upload a new video to a listing (multipart)
- delete: delete a video from a listing

All operations return raw Etsy response dicts. Tool layer handles envelope
formatting. Managers do not redact — EtsyClient already redacts in logs and
the tool envelope helpers redact in output.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class VideoManager:
    """Manages Etsy ListingVideo operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    async def list(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/videos"""
        return await self.client.get(f"/shops/{shop_id}/listings/{listing_id}/videos")

    async def get(self, shop_id: int, listing_id: int, video_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/videos/{video_id}"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/videos/{video_id}"
        )

    async def upload(
        self,
        shop_id: int,
        listing_id: int,
        *,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/listings/{listing_id}/videos (multipart)."""
        path = Path(file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Video file not found: {file_path}")

        with path.open("rb") as fh:
            files = {"video": (path.name, fh.read(), "application/octet-stream")}
        data: dict[str, Any] = {}
        if name:
            data["name"] = name

        return await self.client.post(
            f"/shops/{shop_id}/listings/{listing_id}/videos",
            data=data or None,
            files=files,
        )

    async def delete(self, shop_id: int, listing_id: int, video_id: int) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/listings/{listing_id}/videos/{video_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/listings/{listing_id}/videos/{video_id}"
        )
