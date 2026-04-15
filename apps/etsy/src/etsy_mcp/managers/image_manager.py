"""Image manager — wraps Etsy ShopListingImage endpoints.

7 operations:
- list: list all images on a listing (responses include alt_text)
- get: get a single image
- upload: POST multipart upload (file path or URL source)
- update_alt_text: try PATCH first, fall back to delete+reupload
- delete: DELETE an image
- reorder: PUT the full image rank order
- bulk operations are coordinated at the tool layer using update_alt_text

The most complex operation is update_alt_text. It first attempts a PATCH
request to the ShopListingImage endpoint. If Etsy returns 404/405 indicating
the endpoint does not exist (EtsyEndpointRemoved), it falls back to a
destructive delete + re-upload that preserves the original file content and
rank position. The fallback path is logged as a warning.

All operations return raw Etsy response dicts. Tool layer handles envelope
formatting and confirm gating.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from etsy_core.client import EtsyClient
from etsy_core.exceptions import (
    EtsyEndpointRemoved,
    EtsyError,
    EtsyResourceNotFound,
)

logger = logging.getLogger(__name__)


# Reasonable cap to keep us from streaming a 100MB image into memory.
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MiB


class ImageManager:
    """Manages Etsy ShopListingImage operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Reads
    # -------------------------------------------------------------------------

    async def list(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/images"""
        return await self.client.get(f"/shops/{shop_id}/listings/{listing_id}/images")

    async def get(
        self,
        shop_id: int,
        listing_id: int,
        listing_image_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/images/{listing_image_id}"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/images/{listing_image_id}"
        )

    # -------------------------------------------------------------------------
    # Upload (multipart)
    # -------------------------------------------------------------------------

    async def _resolve_image_source(self, image_source: str) -> tuple[bytes, str, str]:
        """Resolve a file path or URL into (bytes, filename, content_type).

        Accepts:
        - file:///abs/path or /abs/path
        - http://... or https://...
        """
        if not image_source or not isinstance(image_source, str):
            raise EtsyError("image_source must be a non-empty string")

        parsed = urlparse(image_source)
        scheme = parsed.scheme.lower()

        if scheme in ("http", "https"):
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
                resp = await http.get(image_source)
                resp.raise_for_status()
                content = resp.content
                if len(content) > MAX_IMAGE_BYTES:
                    raise EtsyError(
                        f"Downloaded image from {image_source} is {len(content)} bytes, "
                        f"exceeds max {MAX_IMAGE_BYTES}"
                    )
                content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                filename = Path(parsed.path).name or "image.jpg"
                return content, filename, content_type

        # File path: accept file:// or bare path
        path_str = parsed.path if scheme == "file" else image_source
        path = Path(path_str).expanduser()
        if not path.exists():
            raise EtsyError(f"image_source file not found: {path}")
        if not path.is_file():
            raise EtsyError(f"image_source is not a file: {path}")
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise EtsyError(
                f"image_source {path} is {size} bytes, exceeds max {MAX_IMAGE_BYTES}"
            )
        with path.open("rb") as fh:
            content = fh.read()

        # Best-effort content-type from extension
        ext = path.suffix.lower().lstrip(".")
        content_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }.get(ext, "image/jpeg")
        return content, path.name, content_type

    async def upload(
        self,
        shop_id: int,
        listing_id: int,
        *,
        image_source: str,
        rank: int = 1,
        alt_text: str | None = None,
        overwrite: bool = False,
        is_watermarked: bool = False,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/listings/{listing_id}/images (multipart).

        Resolves image_source into bytes (via download or file read), then
        sends multipart with the supported metadata fields. alt_text is set
        on creation when provided.
        """
        content, filename, content_type = await self._resolve_image_source(image_source)

        data: dict[str, Any] = {
            "rank": rank,
            "overwrite": "true" if overwrite else "false",
            "is_watermarked": "true" if is_watermarked else "false",
        }
        if alt_text is not None:
            data["alt_text"] = alt_text

        return await self.client.post(
            f"/shops/{shop_id}/listings/{listing_id}/images",
            files={"image": (filename, content, content_type)},
            data=data,
        )

    # -------------------------------------------------------------------------
    # Delete + reorder
    # -------------------------------------------------------------------------

    async def delete(
        self,
        shop_id: int,
        listing_id: int,
        listing_image_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/listings/{listing_id}/images/{listing_image_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/listings/{listing_id}/images/{listing_image_id}"
        )

    async def reorder(
        self,
        shop_id: int,
        listing_id: int,
        image_order: list[int],
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/listings/{listing_id}/images — full rank order."""
        return await self.client.put(
            f"/shops/{shop_id}/listings/{listing_id}/images",
            json={"listing_image_ids": image_order},
            idempotent=True,
        )

    # -------------------------------------------------------------------------
    # Alt text update — primary PATCH path with destructive fallback
    # -------------------------------------------------------------------------

    async def update_alt_text(
        self,
        shop_id: int,
        listing_id: int,
        listing_image_id: int,
        alt_text: str,
    ) -> dict[str, Any]:
        """Try PATCH first; fall back to delete + re-upload if PATCH unavailable.

        Returns:
            {"path_used": "patch" | "delete_reupload", "data": <etsy response>}
        """
        # ---- Method 1: PATCH ------------------------------------------------
        try:
            result = await self.client.patch(
                f"/shops/{shop_id}/listings/{listing_id}/images/{listing_image_id}",
                json={"alt_text": alt_text},
            )
            logger.info(
                "alt_text updated via PATCH for image %d (listing %d)",
                listing_image_id,
                listing_id,
            )
            return {"path_used": "patch", "data": result}
        except EtsyEndpointRemoved:
            # PATCH endpoint does not exist for ShopListingImage — fall through
            logger.warning(
                "PATCH endpoint unavailable for ShopListingImage; "
                "falling back to delete+reupload for image %d",
                listing_image_id,
            )
        except EtsyResourceNotFound:
            # Real 404 (image doesn't exist) — surface as-is
            raise

        # ---- Method 2: Delete + re-upload ----------------------------------
        current = await self.get(shop_id, listing_id, listing_image_id)
        image_url = (
            current.get("url_fullxfull")
            or current.get("url_570xN")
            or current.get("url_75x75")
        )
        if not image_url:
            raise EtsyError(
                "Cannot fall back to delete+reupload: current image has no retrievable URL"
            )
        original_rank = current.get("rank", 1)

        # Download original bytes BEFORE deleting (preserve content)
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
                resp = await http.get(image_url)
                resp.raise_for_status()
                image_bytes = resp.content
                if len(image_bytes) > MAX_IMAGE_BYTES:
                    raise EtsyError(
                        f"Original image is {len(image_bytes)} bytes, exceeds max {MAX_IMAGE_BYTES}"
                    )
                content_type = (
                    resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                )
        except httpx.HTTPError as exc:
            raise EtsyError(
                f"Failed to download original image content for fallback: {exc.__class__.__name__}"
            ) from exc

        # Delete current image
        await self.delete(shop_id, listing_id, listing_image_id)

        # Re-upload with new alt_text and original rank
        try:
            result = await self.client.post(
                f"/shops/{shop_id}/listings/{listing_id}/images",
                files={"image": ("image.jpg", image_bytes, content_type)},
                data={
                    "alt_text": alt_text,
                    "rank": original_rank,
                },
            )
        except Exception as exc:
            logger.error(
                "CRITICAL: image %d was deleted but re-upload failed (%s). "
                "The listing is now missing this image.",
                listing_image_id,
                exc,
            )
            raise EtsyError(
                f"Image {listing_image_id} was deleted but re-upload failed: "
                f"{exc.__class__.__name__}. The image is now MISSING from listing {listing_id}."
            ) from exc

        logger.warning(
            "Image %d recreated via delete+reupload (new id may differ; rank=%s)",
            listing_image_id,
            original_rank,
        )
        return {"path_used": "delete_reupload", "data": result}
