"""Digital file manager — wraps Etsy ListingFile (digital downloads) endpoints.

4 operations:
- list: list all digital files on a listing
- get: get a single digital file by id
- upload: upload a new digital file (multipart)
- delete: delete a digital file from a listing

Managers return raw Etsy response dicts. Tool layer handles envelopes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class DigitalFileManager:
    """Manages Etsy ListingFile (digital downloads) operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    async def list(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/files"""
        return await self.client.get(f"/shops/{shop_id}/listings/{listing_id}/files")

    async def get(
        self,
        shop_id: int,
        listing_id: int,
        listing_file_id: int,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/files/{listing_file_id}"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/files/{listing_file_id}"
        )

    async def upload(
        self,
        shop_id: int,
        listing_id: int,
        *,
        file_path: str,
        name: str | None = None,
        rank: int | None = None,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/listings/{listing_id}/files (multipart)."""
        path = Path(file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Digital file not found: {file_path}")

        with path.open("rb") as fh:
            files = {"file": (path.name, fh.read(), "application/octet-stream")}
        data: dict[str, Any] = {"name": name or path.name}
        if rank is not None:
            data["rank"] = rank

        return await self.client.post(
            f"/shops/{shop_id}/listings/{listing_id}/files",
            data=data,
            files=files,
        )

    async def delete(
        self,
        shop_id: int,
        listing_id: int,
        listing_file_id: int,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/listings/{listing_id}/files/{listing_file_id}"""
        return await self.client.delete(
            f"/shops/{shop_id}/listings/{listing_id}/files/{listing_file_id}"
        )
