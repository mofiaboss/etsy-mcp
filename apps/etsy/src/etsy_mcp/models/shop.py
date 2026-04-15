"""Shared Shop field model.

Defines the canonical set of mutable vs read-only fields for an Etsy Shop so
that the manager's fetch-merge-put update path can:

1. Reject any caller-supplied field that is not in MUTABLE_FIELDS (fail loud
   instead of silently dropping it on the server or — far worse — sending a
   partial payload that wipes every unspecified field).
2. Strip server-generated read-only fields from the merged payload before
   sending it back via PATCH (Etsy will reject some of them).
3. Provide a single source of truth mirroring models/listing.py so managers
   stay consistent across resources.

Only the field name set matters here. We deliberately do NOT define a full
pydantic model of every Etsy shop field — Etsy adds and renames fields
constantly, and a full model would be a maintenance liability. The update
path uses dict-shaped patches gated by MUTABLE_FIELDS.

Source: Etsy Open API v3 updateShop parameter set
(https://developer.etsy.com/documentation/reference#operation/updateShop).
Conservative on purpose: a legitimate field mistakenly rejected forces a PR
to widen the set, which is much safer than silently sending a server-side
field we have not vetted.
"""

from __future__ import annotations

from typing import Any

# Fields the caller is allowed to modify via shops_update. Intersected from
# the updateShop request body schema. If Etsy adds a new mutable field,
# extend this set explicitly — never use a wildcard.
MUTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "announcement",
        "sale_message",
        "digital_sale_message",
        "policy_welcome",
        "policy_payment",
        "policy_shipping",
        "policy_refunds",
        "policy_additional",
        "policy_seller_info",
        "policy_privacy",
        "policy_has_private_receipt_info",
        "vacation_mode",
        "vacation_autoreply",
    }
)

# Fields the Etsy API populates and the caller cannot set. We strip these
# from the merged payload before PATCHing to avoid 400s, and we use this set
# to produce clear error messages when a caller tries to update one.
READ_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "shop_id",
        "shop_name",
        "user_id",
        "creation_tsz",
        "created_timestamp",
        "currency_code",
        "is_vacation",
        "listing_active_count",
        "digital_listing_count",
        "login_name",
        "accepts_custom_requests",
        "url",
        "image_url_760x100",
        "num_favorers",
        "languages",
        "icon_url_fullxfull",
        "is_using_structured_policies",
        "has_onboarded_structured_policies",
        "include_dispute_form_link",
        "is_direct_checkout_onboarded",
        "is_etsy_payments_onboarded",
        "is_opted_into_buyer_promise",
        "is_calculated_eligible",
        "is_shop_us_based",
        "transaction_sold_count",
        "shipping_label_count",
        "average_rating_score",
        "update_date",
        "updated_timestamp",
    }
)


def from_api(api_payload: dict[str, Any]) -> dict[str, Any]:
    """Pass-through normalizer for an Etsy shop API response.

    Reserved for future field renames / shape changes. Today this is the
    identity function — the manager already returns raw API dicts.
    """
    return dict(api_payload) if api_payload else {}


def to_api_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Filter a fetch-merge-put payload to fields safe for Etsy shop update.

    Drops:
    - Anything in READ_ONLY_FIELDS
    - Anything outside MUTABLE_FIELDS (defensive — server will reject anyway)

    Unlike listings, we preserve None values because Etsy shop policy fields
    can legitimately be cleared to null (e.g., clearing vacation_autoreply).
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

    Used by ShopManager.update so the caller sees exactly which fields were
    dropped — instead of having them silently disappear (and then wiping
    every unspecified field on the server).
    """
    allowed: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in updates.items():
        if key in MUTABLE_FIELDS:
            allowed[key] = value
        else:
            rejected.append(key)
    return allowed, rejected
