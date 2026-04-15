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
    EtsyValidationError,
)
from etsy_core.safe_http import UnsafeURLError, safe_fetch

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
            try:
                content, raw_content_type = await safe_fetch(
                    image_source, max_bytes=MAX_IMAGE_BYTES
                )
            except UnsafeURLError as exc:
                raise EtsyValidationError(
                    f"image_source URL rejected by SSRF protection: {exc}"
                ) from exc
            except httpx.HTTPError as exc:
                raise EtsyError(
                    f"Failed to download image_source {image_source}: "
                    f"{exc.__class__.__name__}"
                ) from exc
            content_type = (raw_content_type or "image/jpeg").split(";")[0].strip()
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
    # Alt text update — primary PATCH path with upload-first destructive fallback
    # -------------------------------------------------------------------------

    async def update_alt_text(
        self,
        shop_id: int,
        listing_id: int,
        listing_image_id: int,
        alt_text: str,
        *,
        allow_destructive_fallback: bool = False,
    ) -> dict[str, Any]:
        """Update alt_text on a listing image.

        Primary path: PATCH the existing image metadata. Fast, non-destructive.

        Fallback path (requires ``allow_destructive_fallback=True``): if Etsy
        does not support PATCH on listing images, upload a new image first
        (with the updated alt_text and preserved content type), verify the
        upload succeeded, THEN delete the old image. This upload-first order
        is rollback-safe: if upload fails, the old image is untouched and we
        surface a clear error.

        The PATCH path can fail with:
        - ``EtsyEndpointRemoved`` (405 or 404 on a non-numeric path) —
          unambiguous "endpoint verb not supported"; proceed to fallback.
        - ``EtsyResourceNotFound`` — ambiguous on non-GET; could be a real
          404 or a disguised "endpoint unsupported". We verify with a GET
          on the same resource. If GET succeeds, the resource exists and
          the PATCH verb is unsupported → proceed to fallback. If GET also
          404s, it's a real missing resource → re-raise.

        Returns:
            dict with keys:
            - ``path_used``: ``"patch"`` | ``"upload_then_delete"``
            - ``data``: updated or newly-uploaded image dict
            - ``new_listing_image_id``: new image id if fallback ran, else ``None``
            - ``old_listing_image_id``: the original image id
            - ``warnings``: list of human-readable warning strings
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
            return {
                "path_used": "patch",
                "data": result,
                "new_listing_image_id": None,
                "old_listing_image_id": listing_image_id,
                "warnings": [],
            }
        except EtsyEndpointRemoved as exc:
            # Unambiguous: Etsy returned 405, or 404 on a non-numeric path.
            logger.info(
                "Image PATCH unavailable (%s); considering fallback for image %d",
                exc.message,
                listing_image_id,
            )
        except EtsyResourceNotFound as exc:
            # Ambiguous on non-GET: could be a real 404 or disguised endpoint-not-supported.
            # Verify by GETting the resource.
            try:
                await self.client.get(
                    f"/shops/{shop_id}/listings/{listing_id}/images/{listing_image_id}"
                )
            except EtsyResourceNotFound:
                # Resource really is missing — propagate the original error.
                raise exc
            logger.info(
                "Image %d PATCH failed with 404 but GET succeeds; "
                "treating as endpoint-verb-unsupported and considering fallback",
                listing_image_id,
            )

        # ---- Fallback gate --------------------------------------------------
        if not allow_destructive_fallback:
            raise EtsyError(
                f"Cannot update alt_text on image {listing_image_id}: "
                f"Etsy does not support the PATCH verb on listing images. "
                f"Re-run with allow_destructive_fallback=True to use the "
                f"upload-first-then-delete workaround (briefly creates a "
                f"duplicate image before removing the original; may change "
                f"the listing_image_id)."
            )

        # ---- Method 2: Upload-first, then delete ---------------------------
        current = await self.get(shop_id, listing_id, listing_image_id)
        image_url = (
            current.get("url_fullxfull")
            or current.get("url_570xN")
            or current.get("url_75x75")
        )
        if not image_url:
            raise EtsyError(
                f"Cannot run destructive fallback: image {listing_image_id} "
                f"has no retrievable URL"
            )
        original_rank = current.get("rank", 1)

        # Download original bytes + detect content type from the CDN response.
        # Uses safe_fetch even for Etsy-provided CDN URLs (defense in depth
        # against redirect chains mapping to internal hosts or content-length
        # abuse). The old image is still intact if this fails — no rollback.
        try:
            image_bytes, raw_content_type = await safe_fetch(
                image_url, max_bytes=MAX_IMAGE_BYTES
            )
        except UnsafeURLError as exc:
            raise EtsyError(
                f"Etsy CDN image URL rejected by SSRF protection: {exc}. "
                f"Old image {listing_image_id} is still intact — no rollback needed."
            ) from exc
        except httpx.HTTPError as exc:
            raise EtsyError(
                f"Failed to download original image content for fallback: "
                f"{exc.__class__.__name__}. Old image {listing_image_id} is "
                f"still intact — no rollback needed."
            ) from exc
        content_type = (
            (raw_content_type or "image/jpeg").split(";")[0].strip().lower()
        )

        # Derive a sane filename from the detected content type so we don't
        # downgrade PNG/WebP to image.jpg and force Etsy to re-encode.
        ext_map = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/pjpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        ext = ext_map.get(content_type, "jpg")
        filename = f"image.{ext}"

        # Upload new image FIRST — do not touch the old one yet.
        try:
            new_image = await self.client.post(
                f"/shops/{shop_id}/listings/{listing_id}/images",
                files={"image": (filename, image_bytes, content_type)},
                data={
                    "alt_text": alt_text,
                    "rank": str(original_rank),
                },
            )
        except EtsyError as exc:
            # Upload failed — old image is still intact. No rollback needed.
            raise EtsyError(
                f"Alt_text update via fallback failed at upload step: "
                f"{exc.message}. Old image {listing_image_id} is still intact "
                f"— no rollback needed."
            ) from exc

        new_listing_image_id = new_image.get("listing_image_id")
        if not new_listing_image_id:
            raise EtsyError(
                f"Upload succeeded but new image has no listing_image_id; "
                f"aborting before delete. Old image {listing_image_id} is "
                f"still intact."
            )

        # Verify new image is reachable before we delete the old one.
        try:
            await self.get(shop_id, listing_id, int(new_listing_image_id))
        except EtsyError as exc:
            raise EtsyError(
                f"New image {new_listing_image_id} was uploaded but is not yet "
                f"readable: {exc.message}. Old image {listing_image_id} is "
                f"still intact; no rollback performed. Retry this operation later."
            ) from exc

        # Delete old image. If this fails we're left with a duplicate — surface
        # a warning but return successfully so the caller knows the alt_text is
        # live on the new image.
        try:
            await self.delete(shop_id, listing_id, listing_image_id)
        except EtsyError as exc:
            logger.warning(
                "Delete of old image %d failed after successful upload of new image %d: %s",
                listing_image_id,
                new_listing_image_id,
                exc.message,
            )
            return {
                "path_used": "upload_then_delete",
                "data": new_image,
                "new_listing_image_id": int(new_listing_image_id),
                "old_listing_image_id": listing_image_id,
                "warnings": [
                    f"Upload succeeded but delete of old image {listing_image_id} "
                    f"failed ({exc.message}). The listing now has a DUPLICATE image. "
                    f"Manual cleanup required: delete image {listing_image_id} via "
                    f"the Etsy dashboard or call etsy_listing_images_delete."
                ],
            }

        logger.warning(
            "Image %d replaced via upload-then-delete with new image %d (rank=%s)",
            listing_image_id,
            new_listing_image_id,
            original_rank,
        )
        return {
            "path_used": "upload_then_delete",
            "data": new_image,
            "new_listing_image_id": int(new_listing_image_id),
            "old_listing_image_id": listing_image_id,
            "warnings": [
                f"Original image {listing_image_id} was replaced with new image "
                f"{new_listing_image_id} (same file, new alt_text). Rank preserved "
                f"as {original_rank}. Callers tracking the old listing_image_id "
                f"(e.g. variation-image maps) must update to the new id."
            ],
        }
