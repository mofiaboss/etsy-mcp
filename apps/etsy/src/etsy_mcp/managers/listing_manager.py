"""Listing manager — wraps Etsy ShopListing endpoints.

19 operations, one per tool, plus internal helpers for bulk operations.

Read operations:
- list_by_shop
- list_by_shop_receipt
- list_by_shop_section
- list_by_shop_return_policy
- list_by_ids
- search_active
- get_featured
- get
- list_translations
- list_return_policies

Write operations:
- create_draft
- bulk_create_from_template
- update                    (fetch-merge-put with verification poll)
- bulk_update_from_template (per-listing fetch-merge-put)
- delete
- activate
- deactivate
- copy
- update_variation_images

All methods return raw Etsy response dicts (or composite dicts for bulk
ops). The tool layer handles envelope formatting and confirm-gating.
Managers do not redact — F3 redaction lives in EtsyClient logs and in the
schemas envelope helpers used by the tool layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from etsy_core.client import EtsyClient
from etsy_core.exceptions import EtsyError, EtsyValidationError

from etsy_mcp.models.listing import (
    MUTABLE_FIELDS,
    to_api_create,
    to_api_update,
    validate_update_fields,
)
from etsy_mcp.models.listing_template import ListingTemplate

logger = logging.getLogger(__name__)


class ListingManager:
    """Manages Etsy ShopListing resources.

    Architectural notes:
    - Bulk methods iterate sequentially and isolate per-item errors. They
      do NOT parallelize because the EtsyClient's token bucket would just
      serialize them anyway, and sequential iteration gives deterministic
      ordering for partial-success reporting.
    - update() uses fetch-merge-put: GET current state, merge caller patch,
      strip read-only fields, PATCH the full object, then poll-verify the
      applied state. Polling backoff: [0.5, 1.0, 2.0] seconds.
    """

    # Polling backoff for post-update verification (eventual consistency)
    _UPDATE_VERIFY_BACKOFF = (0.5, 1.0, 2.0)

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # =========================================================================
    # READ operations
    # =========================================================================

    async def list_by_shop(
        self,
        shop_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
        state: str | None = None,
        sort_on: str | None = None,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings — paginated listings for a shop."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if state is not None:
            params["state"] = state
        if sort_on is not None:
            params["sort_on"] = sort_on
        return await self.client.get(f"/shops/{shop_id}/listings", params=params)

    async def list_by_shop_receipt(
        self,
        shop_id: int,
        receipt_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/receipts/{receipt_id}/listings — listings on a receipt."""
        return await self.client.get(
            f"/shops/{shop_id}/receipts/{receipt_id}/listings",
            params={"limit": limit, "offset": offset},
        )

    async def list_by_shop_section(
        self,
        shop_id: int,
        shop_section_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/shop-sections/listings — listings in a section."""
        return await self.client.get(
            f"/shops/{shop_id}/shop-sections/listings",
            params={
                "shop_section_ids": shop_section_id,
                "limit": limit,
                "offset": offset,
            },
        )

    async def list_by_shop_return_policy(
        self,
        shop_id: int,
        return_policy_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/policies/return/{return_policy_id}/listings"""
        return await self.client.get(
            f"/shops/{shop_id}/policies/return/{return_policy_id}/listings",
            params={"limit": limit, "offset": offset},
        )

    async def list_by_ids(self, listing_ids: list[int]) -> dict[str, Any]:
        """GET /listings/batch — bulk-fetch listings by ID.

        Etsy expects comma-separated `listing_ids` query param.
        """
        if not listing_ids:
            raise EtsyValidationError("listing_ids must not be empty")
        return await self.client.get(
            "/listings/batch",
            params={"listing_ids": ",".join(str(i) for i in listing_ids)},
        )

    async def search_active(
        self,
        *,
        keywords: str | None = None,
        taxonomy_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
        min_price: float | None = None,
        max_price: float | None = None,
        sort_on: str | None = None,
        sort_order: str | None = None,
    ) -> dict[str, Any]:
        """GET /listings/active — public search across active listings."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if keywords is not None:
            params["keywords"] = keywords
        if taxonomy_id is not None:
            params["taxonomy_id"] = taxonomy_id
        if min_price is not None:
            params["min_price"] = min_price
        if max_price is not None:
            params["max_price"] = max_price
        if sort_on is not None:
            params["sort_on"] = sort_on
        if sort_order is not None:
            params["sort_order"] = sort_order
        return await self.client.get("/listings/active", params=params)

    async def get_featured(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        """GET /listings/featured — featured listings.

        [UNVERIFIED] This endpoint may not exist in Etsy v3. If it returns
        404, EtsyEndpointRemoved will surface and the tool layer will return
        a graceful error envelope.
        """
        return await self.client.get(
            "/listings/featured",
            params={"limit": limit, "offset": offset},
        )

    async def get(self, listing_id: int) -> dict[str, Any]:
        """GET /listings/{listing_id}"""
        return await self.client.get(f"/listings/{listing_id}")

    async def list_translations(
        self,
        shop_id: int,
        listing_id: int,
        language: str,
    ) -> dict[str, Any]:
        """GET /shops/{shop_id}/listings/{listing_id}/translations/{language}"""
        return await self.client.get(
            f"/shops/{shop_id}/listings/{listing_id}/translations/{language}"
        )

    async def list_return_policies(self, shop_id: int) -> dict[str, Any]:
        """GET /shops/{shop_id}/policies/return — shop's return policies."""
        return await self.client.get(f"/shops/{shop_id}/policies/return")

    # =========================================================================
    # WRITE operations — single
    # =========================================================================

    async def create_draft(
        self,
        shop_id: int,
        *,
        title: str,
        description: str,
        price: float,
        quantity: int,
        taxonomy_id: int,
        who_made: str,
        when_made: str,
        is_supply: bool,
        tags: list[str] | None = None,
        materials: list[str] | None = None,
        shipping_profile_id: int | None = None,
        shop_section_id: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/listings — create a draft listing.

        Accepts the canonical create payload. Additional fields can be
        passed via **extra; they are filtered through to_api_create() to
        strip read-only fields and None values.
        """
        payload: dict[str, Any] = {
            "title": title,
            "description": description,
            "price": price,
            "quantity": quantity,
            "taxonomy_id": taxonomy_id,
            "who_made": who_made,
            "when_made": when_made,
            "is_supply": is_supply,
        }
        if tags is not None:
            payload["tags"] = tags
        if materials is not None:
            payload["materials"] = materials
        if shipping_profile_id is not None:
            payload["shipping_profile_id"] = shipping_profile_id
        if shop_section_id is not None:
            payload["shop_section_id"] = shop_section_id
        payload.update(extra)

        return await self.client.post(
            f"/shops/{shop_id}/listings",
            json=to_api_create(payload),
        )

    async def update(
        self,
        shop_id: int,
        listing_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch-merge-PATCH a listing with post-update verification polling.

        Returns a dict shaped for `update_with_verification_envelope`:
            {
                "requested": <updates the caller asked for>,
                "applied":   <verified server state for those fields>,
                "diverged":  <fields where applied != requested>,
                "ignored":   <fields the caller passed that we rejected>,
                "warnings":  <human notes>,
            }
        """
        if not updates:
            raise EtsyValidationError("updates must not be empty")

        allowed, rejected = validate_update_fields(updates)
        warnings: list[str] = []
        if rejected:
            warnings.append(
                f"Rejected non-mutable fields (Etsy will not accept them): {rejected}"
            )
        if not allowed:
            raise EtsyValidationError(
                f"No mutable fields in updates. Rejected: {rejected}. "
                f"Allowed fields are: {sorted(MUTABLE_FIELDS)}"
            )

        # Fetch current state
        current = await self.get(listing_id)

        # Merge: start from current, overlay caller updates
        merged = dict(current)
        merged.update(allowed)

        # Strip read-only fields + filter to mutable set
        payload = to_api_update(merged)

        # PATCH
        await self.client.patch(
            f"/shops/{shop_id}/listings/{listing_id}",
            json=payload,
        )

        # Poll-verify: read the listing back and check that requested
        # fields actually applied. Eventual consistency is real.
        verified, verify_ok = await self._poll_verify(listing_id, allowed)

        if not verify_ok:
            # Cycle 1 review fix: NEVER conflate "cannot verify" with
            # "diverged state". If every poll-verify GET failed, we have
            # NO information about the post-PATCH state — the PATCH itself
            # returned 200 so it probably succeeded, but we can't prove it.
            # Return a clearly-flagged verification_unavailable result.
            warnings.append(
                "PATCH was accepted by Etsy but post-update verification "
                "polling failed (all GET attempts errored). Server state is "
                "UNKNOWN. Re-read the listing manually to confirm the update."
            )
            return {
                "requested": allowed,
                "applied": {},
                "diverged": {},
                "ignored": rejected,
                "warnings": warnings,
                "verification_unavailable": True,
            }

        applied = {k: verified.get(k) for k in allowed.keys()}
        diverged = {
            k: {"requested": allowed[k], "applied": applied[k]}
            for k in allowed.keys()
            if applied[k] != allowed[k]
        }

        return {
            "requested": allowed,
            "applied": applied,
            "diverged": diverged,
            "ignored": rejected,
            "warnings": warnings,
            "verification_unavailable": False,
        }

    async def _poll_verify(
        self,
        listing_id: int,
        expected: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Poll the listing until expected fields converge or backoff exhausted.

        Returns:
            (state, verify_ok) tuple where:
            - state: the most recent successful GET response, or empty dict
            - verify_ok: True iff AT LEAST ONE GET succeeded during the poll
                loop. When False, the caller MUST NOT compute diverged/applied
                from the state dict — it will produce false positives. This
                distinguishes "update was verified and these fields diverged"
                from "we couldn't verify anything at all" (Cycle 1 review fix).
        """
        last: dict[str, Any] = {}
        verify_ok = False
        for delay in self._UPDATE_VERIFY_BACKOFF:
            try:
                last = await self.get(listing_id)
                verify_ok = True
                if all(last.get(k) == v for k, v in expected.items()):
                    return last, verify_ok
            except EtsyError as exc:
                logger.warning(
                    "poll-verify GET failed for listing %s: %s",
                    listing_id,
                    exc,
                )
            await asyncio.sleep(delay)
        # Final read after last sleep
        try:
            last = await self.get(listing_id)
            verify_ok = True
        except EtsyError as exc:
            logger.warning(
                "final poll-verify GET failed for listing %s: %s",
                listing_id,
                exc,
            )
        return last, verify_ok

    async def delete(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """DELETE /shops/{shop_id}/listings/{listing_id} — destructive."""
        return await self.client.delete(f"/shops/{shop_id}/listings/{listing_id}")

    async def activate(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """PATCH state=active."""
        return await self.client.patch(
            f"/shops/{shop_id}/listings/{listing_id}",
            json={"state": "active"},
        )

    async def deactivate(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """PATCH state=inactive — revenue impact, reversible."""
        return await self.client.patch(
            f"/shops/{shop_id}/listings/{listing_id}",
            json={"state": "inactive"},
        )

    async def copy(self, shop_id: int, listing_id: int) -> dict[str, Any]:
        """POST /shops/{shop_id}/listings/{listing_id}/copy."""
        return await self.client.post(
            f"/shops/{shop_id}/listings/{listing_id}/copy",
        )

    async def update_variation_images(
        self,
        shop_id: int,
        listing_id: int,
        variation_images: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST /shops/{shop_id}/listings/{listing_id}/variation-images.

        [UNVERIFIED] The Etsy v3 endpoint name and verb (POST vs PUT) for
        variation images may differ. If the verb is wrong the client will
        return a 405 and the tool layer will surface an actionable error.
        """
        return await self.client.post(
            f"/shops/{shop_id}/listings/{listing_id}/variation-images",
            json={"variation_images": variation_images},
        )

    # =========================================================================
    # WRITE operations — bulk primitives
    # =========================================================================

    async def bulk_create_from_template(
        self,
        shop_id: int,
        templates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Iterate templates and create one listing per template.

        Per-item error isolation: a single failure does not abort the batch.
        Rate limiting is enforced by EtsyClient's token bucket — bulk runs
        will naturally throttle.

        Returns a dict shaped for partial_success_envelope:
            {"created": [...success items], "failed": [...failure items]}
        """
        created: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for idx, raw in enumerate(templates):
            try:
                # Validate via pydantic — fail loud per item
                template = ListingTemplate(**raw)
                payload = template.to_create_payload()
                result = await self.create_draft(shop_id, **payload)
                listing_id = result.get("listing_id") or result.get("id")
                created.append(
                    {
                        "index": idx,
                        "listing_id": listing_id,
                        "title": template.title,
                        "status": "success",
                    }
                )
            except EtsyError as exc:
                failed.append(
                    {
                        "index": idx,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                        "template_title": (raw.get("title") if isinstance(raw, dict) else None),
                    }
                )
            except (ValueError, TypeError) as exc:
                # pydantic ValidationError is a ValueError subclass
                failed.append(
                    {
                        "index": idx,
                        "error": f"Template validation failed: {exc}",
                        "error_type": exc.__class__.__name__,
                        "template_title": (raw.get("title") if isinstance(raw, dict) else None),
                    }
                )
            except Exception as exc:  # noqa: BLE001 — bulk isolation
                failed.append(
                    {
                        "index": idx,
                        "error": f"Unexpected error: {exc.__class__.__name__}",
                        "error_type": exc.__class__.__name__,
                        "template_title": (raw.get("title") if isinstance(raw, dict) else None),
                    }
                )

        return {"created": created, "failed": failed}

    async def bulk_update_from_template(
        self,
        shop_id: int,
        updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Iterate updates and apply fetch-merge-put per listing.

        Each update entry must be `{"listing_id": int, "patch_fields": dict}`.

        Per-listing error isolation. Returns a dict shaped for
        partial_success_envelope with `updated` + `failed`.
        """
        updated: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for idx, entry in enumerate(updates):
            listing_id = None
            try:
                if not isinstance(entry, dict):
                    raise ValueError("each update entry must be a dict")
                listing_id = entry.get("listing_id")
                patch_fields = entry.get("patch_fields")
                if listing_id is None or not isinstance(listing_id, int):
                    raise ValueError("listing_id (int) is required on each entry")
                if not patch_fields or not isinstance(patch_fields, dict):
                    raise ValueError("patch_fields (non-empty dict) is required on each entry")

                result = await self.update(shop_id, listing_id, patch_fields)
                updated.append(
                    {
                        "index": idx,
                        "listing_id": listing_id,
                        "applied": result["applied"],
                        "diverged": result["diverged"],
                        "ignored": result["ignored"],
                        "status": "success" if not result["diverged"] else "diverged",
                    }
                )
            except EtsyError as exc:
                failed.append(
                    {
                        "index": idx,
                        "listing_id": listing_id,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
            except (ValueError, TypeError) as exc:
                failed.append(
                    {
                        "index": idx,
                        "listing_id": listing_id,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — bulk isolation
                failed.append(
                    {
                        "index": idx,
                        "listing_id": listing_id,
                        "error": f"Unexpected error: {exc.__class__.__name__}",
                        "error_type": exc.__class__.__name__,
                    }
                )

        return {"updated": updated, "failed": failed}
