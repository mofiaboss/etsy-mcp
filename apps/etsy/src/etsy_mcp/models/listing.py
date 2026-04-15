"""Shared Listing field model.

Defines the canonical set of mutable vs read-only fields for an Etsy listing
so that the manager's fetch-merge-put update path can:

1. Reject any caller-supplied field that is not in MUTABLE_FIELDS (fail loud
   instead of silently dropping it on the server).
2. Strip server-generated read-only fields from the merged payload before
   sending it back via PATCH (Etsy will reject some of them).
3. Provide a single source of truth for the listings field set so that the
   ListingTemplate model (used by bulk create/update) and the update tool
   stay in sync.

Only the field name set matters here. We deliberately do NOT define a full
pydantic model of every Etsy listing field — Etsy adds and renames fields
constantly, and a full model would be a maintenance liability. The bulk
create path uses the strict ListingTemplate pydantic model; the update path
uses dict-shaped patches gated by MUTABLE_FIELDS.
"""

from __future__ import annotations

from typing import Any

# Fields the caller is allowed to modify via listings_update / bulk_update.
# Sourced from the Etsy v3 ShopListing schema (createDraftListing +
# updateListing parameter sets, intersected). Conservative on purpose:
# it is safer to reject a legitimate field and force a PR than to allow a
# field we have not vetted.
MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "price",
        "quantity",
        "tags",
        "materials",
        "shop_section_id",
        "taxonomy_id",
        "who_made",
        "when_made",
        "is_supply",
        "is_customizable",
        "is_personalizable",
        "personalization_is_required",
        "personalization_char_count_max",
        "personalization_instructions",
        "is_taxable",
        "shipping_profile_id",
        "return_policy_id",
        "production_partner_ids",
        "image_ids",
        "item_weight",
        "item_weight_unit",
        "item_length",
        "item_width",
        "item_height",
        "item_dimensions_unit",
        "processing_min",
        "processing_max",
        "should_auto_renew",
        "type",  # physical | download | both
        "state",  # active | inactive | draft (changed via dedicated tools)
        "featured_rank",
        "has_variations",
    }
)

# Fields the Etsy API populates and the caller cannot set. We strip these
# from the merged payload before PATCHing to avoid 400s.
READ_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "listing_id",
        "user_id",
        "shop_id",
        "url",
        "num_favorers",
        "non_taxable",
        "is_private",
        "creation_timestamp",
        "created_timestamp",
        "ending_timestamp",
        "original_creation_timestamp",
        "last_modified_timestamp",
        "updated_timestamp",
        "state_timestamp",
        "views",
        "currency_code",
        "language",
        "skus",
        "style",
        "translations",
        "production_partners",
        "taxonomy_path",
        "shipping_profile",
        "user",
        "shop",
        "images",
        "videos",
        "inventory",
    }
)


def from_api(api_payload: dict[str, Any]) -> dict[str, Any]:
    """Pass-through normalizer for an Etsy listing API response.

    Reserved for future field renames / shape changes. Today this is the
    identity function — the manager already returns raw API dicts.
    """
    return dict(api_payload) if api_payload else {}


def to_api_create(template: dict[str, Any]) -> dict[str, Any]:
    """Filter a create payload to fields Etsy accepts on createDraftListing.

    Drops anything in READ_ONLY_FIELDS plus None values (Etsy rejects nulls
    on most fields).
    """
    return {
        k: v
        for k, v in template.items()
        if k not in READ_ONLY_FIELDS and v is not None
    }


def to_api_update(merged: dict[str, Any]) -> dict[str, Any]:
    """Filter a fetch-merge-put payload to fields safe for PATCH.

    Drops:
    - Anything in READ_ONLY_FIELDS
    - Anything outside MUTABLE_FIELDS (defensive — server will reject anyway)
    - None values
    """
    return {
        k: v
        for k, v in merged.items()
        if k in MUTABLE_FIELDS and k not in READ_ONLY_FIELDS and v is not None
    }


def validate_update_fields(updates: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Split a caller-supplied updates dict into (allowed, rejected).

    Returns:
        (allowed_updates, rejected_field_names)

    Used by listings_update tool so the caller sees exactly which fields
    were dropped instead of having them silently disappear.
    """
    allowed: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in updates.items():
        if key in MUTABLE_FIELDS:
            allowed[key] = value
        else:
            rejected.append(key)
    return allowed, rejected
