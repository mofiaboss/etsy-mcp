"""ListingTemplate — pydantic model for bulk create/update payloads.

Single source of truth for the shape a caller (LLM) passes into
`listings_bulk_create_from_template`. The model is intentionally strict:
field names match the Etsy v3 createDraftListing parameter set 1:1, so
templates can be forwarded to the API with minimal massaging.

Field symmetry test (in tests/) asserts every field here maps to a real
Etsy create-listing parameter and that no parameter is accidentally
exposed twice under different names.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Etsy's enumerated when_made values. Source:
# https://developer.etsy.com/documentation/reference#operation/createDraftListing
WHEN_MADE_VALUES: frozenset[str] = frozenset(
    {
        "made_to_order",
        "2020_2025",
        "2010_2019",
        "2006_2009",
        "before_2006",
        "2000_2005",
        "1990s",
        "1980s",
        "1970s",
        "1960s",
        "1950s",
        "1940s",
        "1930s",
        "1920s",
        "1910s",
        "1900s",
        "1800s",
        "1700s",
        "before_1700",
    }
)

WhoMade = Literal["i_did", "collective", "someone_else"]
ListingType = Literal["physical", "download", "both"]


class ListingTemplate(BaseModel):
    """Strict template for one listing in a bulk create payload.

    Required minimum: title, description, price, quantity, taxonomy_id,
    who_made, when_made, is_supply. Everything else is optional.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Required core fields
    title: str = Field(min_length=1, max_length=140)
    description: str = Field(min_length=1, max_length=13_000)
    price: float = Field(gt=0)
    quantity: int = Field(ge=0, le=999)
    taxonomy_id: int = Field(gt=0)
    who_made: WhoMade
    when_made: str
    is_supply: bool

    # Optional categorization
    tags: list[str] = Field(default_factory=list, max_length=13)
    materials: list[str] = Field(default_factory=list, max_length=13)
    shop_section_id: int | None = None
    shipping_profile_id: int | None = None
    return_policy_id: int | None = None
    production_partner_ids: list[int] = Field(default_factory=list)

    # Listing type
    type: ListingType | None = None

    # Personalization
    is_customizable: bool | None = None
    is_personalizable: bool | None = None
    personalization_is_required: bool | None = None
    personalization_char_count_max: int | None = Field(default=None, ge=0, le=1024)
    personalization_instructions: str | None = Field(default=None, max_length=8192)

    # Tax
    is_taxable: bool | None = None

    # Physical attributes
    item_weight: float | None = Field(default=None, gt=0)
    item_weight_unit: Literal["oz", "lb", "g", "kg"] | None = None
    item_length: float | None = Field(default=None, gt=0)
    item_width: float | None = Field(default=None, gt=0)
    item_height: float | None = Field(default=None, gt=0)
    item_dimensions_unit: Literal["in", "ft", "mm", "cm", "m", "yd", "inches"] | None = None

    # Processing time
    processing_min: int | None = Field(default=None, ge=0)
    processing_max: int | None = Field(default=None, ge=0)

    # Renew
    should_auto_renew: bool | None = None

    # Image binding hints (these are NOT sent on create — used by manager
    # if the caller wants follow-up image uploads handled separately by the
    # image_manager. Bulk create itself does NOT upload images; the LLM is
    # expected to call image tools after.)
    image_urls: list[str] = Field(default_factory=list)
    alt_texts: list[str] = Field(default_factory=list)

    # Free-form attributes (taxonomy-driven properties). Forwarded as-is
    # to the listing_properties API after create. Bulk create itself does
    # NOT apply these — caller must call listing_properties tools.
    attributes: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("when_made")
    @classmethod
    def _validate_when_made(cls, v: str) -> str:
        if v not in WHEN_MADE_VALUES:
            raise ValueError(
                f"when_made must be one of {sorted(WHEN_MADE_VALUES)}, got {v!r}"
            )
        return v

    @field_validator("tags", "materials")
    @classmethod
    def _validate_tag_strings(cls, v: list[str]) -> list[str]:
        # Etsy: tags/materials max 20 chars each, no special chars beyond a-z, 0-9, space, -
        for item in v:
            if not isinstance(item, str):
                raise ValueError("tags/materials must be strings")
            if len(item) > 20:
                raise ValueError(f"tag/material '{item}' exceeds 20-char limit")
            if not item.strip():
                raise ValueError("tags/materials must not be empty strings")
        return v

    def to_create_payload(self) -> dict[str, Any]:
        """Render this template as a dict ready for createDraftListing.

        Strips None values and the non-API fields (image_urls, alt_texts,
        attributes) which are handled by separate follow-up calls.
        """
        excluded = {"image_urls", "alt_texts", "attributes"}
        return {
            k: v
            for k, v in self.model_dump(exclude_none=True).items()
            if k not in excluded
        }
