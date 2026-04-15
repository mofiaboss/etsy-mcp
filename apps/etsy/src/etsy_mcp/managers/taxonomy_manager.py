"""Taxonomy manager — wraps Etsy buyer + seller taxonomy endpoints.

5 operations:
- buyer_nodes_list: GET /buyer-taxonomy/nodes
- buyer_node_properties_get: GET /buyer-taxonomy/nodes/{taxonomy_id}/properties
- seller_nodes_list: GET /seller-taxonomy/nodes
- seller_node_properties_get: GET /seller-taxonomy/nodes/{taxonomy_id}/properties
- node_search: client-side walk to find nodes by name (no Etsy search endpoint exists)

Taxonomy endpoints are PUBLIC — no OAuth scope required — but still go through
EtsyClient for rate limiting + daily budget tracking.
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class TaxonomyManager:
    """Manages Etsy taxonomy (buyer + seller) read operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # Buyer taxonomy
    # -------------------------------------------------------------------------

    async def buyer_nodes_list(self) -> dict[str, Any]:
        """GET /buyer-taxonomy/nodes — full buyer taxonomy tree."""
        return await self.client.get("/buyer-taxonomy/nodes")

    async def buyer_node_properties_get(self, taxonomy_id: int) -> dict[str, Any]:
        """GET /buyer-taxonomy/nodes/{taxonomy_id}/properties"""
        return await self.client.get(f"/buyer-taxonomy/nodes/{taxonomy_id}/properties")

    # -------------------------------------------------------------------------
    # Seller taxonomy
    # -------------------------------------------------------------------------

    async def seller_nodes_list(self) -> dict[str, Any]:
        """GET /seller-taxonomy/nodes — full seller taxonomy tree."""
        return await self.client.get("/seller-taxonomy/nodes")

    async def seller_node_properties_get(self, taxonomy_id: int) -> dict[str, Any]:
        """GET /seller-taxonomy/nodes/{taxonomy_id}/properties"""
        return await self.client.get(f"/seller-taxonomy/nodes/{taxonomy_id}/properties")

    # -------------------------------------------------------------------------
    # Helper: client-side search
    # -------------------------------------------------------------------------

    async def node_search(self, query: str, variant: str = "seller") -> dict[str, Any]:
        """Client-side search through the taxonomy tree.

        Walks the seller (default) or buyer taxonomy and returns nodes whose
        name contains the query (case-insensitive). Etsy does NOT expose a
        taxonomy search endpoint — this is pure local filtering.
        """
        if variant == "seller":
            nodes = await self.client.get("/seller-taxonomy/nodes")
        elif variant == "buyer":
            nodes = await self.client.get("/buyer-taxonomy/nodes")
        else:
            raise ValueError(f"variant must be 'seller' or 'buyer', got {variant!r}")

        query_lower = query.lower()
        matches: list[dict[str, Any]] = []

        def walk(node: dict[str, Any], path: str = "") -> None:
            name = node.get("name", "")
            current_path = f"{path}/{name}" if path else name
            if query_lower in name.lower():
                matches.append(
                    {
                        "taxonomy_id": node.get("id"),
                        "name": name,
                        "path": current_path,
                        "level": node.get("level", 0),
                    }
                )
            for child in node.get("children", []) or []:
                walk(child, current_path)

        for root in nodes.get("results", []) or []:
            walk(root)

        return {
            "query": query,
            "variant": variant,
            "matches": matches,
            "count": len(matches),
        }
