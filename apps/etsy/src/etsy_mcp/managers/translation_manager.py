"""Translation manager — wraps Etsy ListingTranslation endpoints.

3 operations:
- get: fetch a single translation by language
- create_or_update: PUT a translation with fetch-merge semantics
- delete: delete a translation

Managers return raw Etsy response dicts. Tool layer handles envelopes.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient
from etsy_core.exceptions import EtsyResourceNotFound

logger = logging.getLogger(__name__)


class TranslationManager:
    """Manages Etsy ListingTranslation operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    async def get(
        self,
        shop_id: int,
        listing_id: int,
        language: str,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/translations/{language}"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/translations/{language}"
        )

    async def create_or_update(
        self,
        shop_id: int,
        listing_id: int,
        language: str,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """PUT /shops/{shop_id}/listings/{listing_id}/translations/{language}.

        Fetch-merge-put: tries to read the current translation; if it exists
        the caller's partial fields are layered on top and the full document
        is sent back. If it does not exist (404), this becomes a create.
        """
        current: dict[str, Any] = {}
        try:
            current = await self.get(shop_id, listing_id, language)
        except EtsyResourceNotFound:
            current = {}

        merged: dict[str, Any] = {}
        if "title" in (current or {}):
            merged["title"] = current.get("title")
        if "description" in (current or {}):
            merged["description"] = current.get("description")
        if "tags" in (current or {}):
            merged["tags"] = current.get("tags")

        if title is not None:
            merged["title"] = title
        if description is not None:
            merged["description"] = description
        if tags is not None:
            merged["tags"] = tags

        return await self.client.put(
            f"/shops/{shop_id}/listings/{listing_id}/translations/{language}",
            json=merged,
            idempotent=True,
        )

    async def delete(
        self,
        shop_id: int,
        listing_id: int,
        language: str,
    ) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/listings/{listing_id}/translations/{language}"""
        return await self.client.delete(
            f"/shops/{shop_id}/listings/{listing_id}/translations/{language}"
        )
