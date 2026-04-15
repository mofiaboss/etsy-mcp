"""Shared ShopSection field model.

Mirrors models/shop.py for the ShopSection resource. Used by
ShopManager.sections_update to enforce fetch-merge-put semantics without
silently dropping caller fields or wiping unspecified server fields.

Source: Etsy Open API v3 updateShopSection parameter set.
"""

from __future__ import annotations

from typing import Any

# Fields the caller is allowed to modify via shop_sections_update.
# ShopSection is a very small resource — only title and rank are user-settable.
MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "rank",
    }
)

# Fields the Etsy API populates and the caller cannot set.
READ_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "shop_section_id",
        "user_id",
        "active_listing_count",
        "absolute_url",
    }
)


def from_api(api_payload: dict[str, Any]) -> dict[str, Any]:
    """Pass-through normalizer for an Etsy shop section API response."""
    return dict(api_payload) if api_payload else {}


def to_api_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Filter a fetch-merge-put payload to fields safe for shop section update.

    Drops anything outside MUTABLE_FIELDS or inside READ_ONLY_FIELDS.
    """
    return {
        k: v
        for k, v in fields.items()
        if k in MUTABLE_FIELDS and k not in READ_ONLY_FIELDS
    }


def validate_update_fields(
    updates: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Split a caller-supplied updates dict into (allowed, rejected).

    Returns:
        (allowed_updates, rejected_field_names)
    """
    allowed: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in updates.items():
        if key in MUTABLE_FIELDS:
            allowed[key] = value
        else:
            rejected.append(key)
    return allowed, rejected
