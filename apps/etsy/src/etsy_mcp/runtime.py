"""Shared runtime singletons for the etsy-mcp server.

This module is the single source of truth for global singletons:
- config
- server (FastMCP instance)
- auth (EtsyAuth)
- client (EtsyClient)
- every manager, one per category

Downstream modules (tools, tests) import via:
    from etsy_mcp.runtime import server, config, client, shop_manager

Lazy factories (get_*) are provided so tests can monkey-patch before import.
"""

# ruff: noqa: E402
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from etsy_core.auth import EtsyAuth, default_config_dir, default_token_path
from etsy_core.client import EtsyClient
from mcp.server.fastmcp import FastMCP

from etsy_mcp.bootstrap import load_config, logger

# ---------------------------------------------------------------------------
# Core singletons
# ---------------------------------------------------------------------------


@lru_cache
def get_config() -> Any:
    """Load and cache configuration from config.yaml + env vars."""
    return load_config()


@lru_cache
def get_auth() -> EtsyAuth:
    """Build the EtsyAuth instance from config."""
    cfg = get_config().etsy
    keystring = getattr(cfg, "keystring", "") or os.environ.get("ETSY_KEYSTRING", "")
    shared_secret = getattr(cfg, "shared_secret", "") or os.environ.get("ETSY_SHARED_SECRET", "")

    if not keystring:
        logger.warning(
            "ETSY_KEYSTRING is not set. The server will start but all API calls will fail. "
            "Run `etsy-mcp auth login` after setting ETSY_KEYSTRING and ETSY_SHARED_SECRET."
        )

    token_store = getattr(cfg, "token_store", "") or os.environ.get("ETSY_TOKEN_STORE", "")
    token_path = Path(token_store).expanduser() if token_store else default_token_path()

    return EtsyAuth(
        keystring=keystring or "placeholder",  # avoid ValueError during import; auth errors surface at call time
        shared_secret=shared_secret,
        token_path=token_path,
    )


@lru_cache
def get_client() -> EtsyClient:
    """Build the EtsyClient singleton."""
    cfg = get_config().etsy
    auth = get_auth()
    daily_counter_path = default_config_dir() / "daily_counter.json"
    return EtsyClient(
        auth=auth,
        base_url=str(getattr(cfg, "api_base", "https://api.etsy.com/v3/application")),
        timeout=float(getattr(cfg, "timeout_seconds", 15.0)),
        rate_limit_per_second=float(getattr(cfg, "rate_limit_per_second", 10.0)),
        daily_budget=int(getattr(cfg, "rate_limit_per_day", 10_000)),
        daily_counter_path=daily_counter_path,
    )


def _create_permissioned_tool_wrapper(original_tool_decorator):
    """Strip permission kwargs from the FastMCP tool decorator.

    Allows tool modules to be imported directly (for testing) without errors
    when they use permission_category / permission_action kwargs. main.py
    replaces this with the full permissioned_tool decorator at startup.
    """

    def wrapper(*args, **kwargs):
        kwargs.pop("permission_category", None)
        kwargs.pop("permission_action", None)
        kwargs.pop("auth", None)
        return original_tool_decorator(*args, **kwargs)

    return wrapper


@lru_cache
def get_server() -> FastMCP:
    """Create the FastMCP server instance exactly once."""
    server = FastMCP(
        name="etsy-mcp",
        debug=False,
    )

    server._original_tool = server.tool
    server.tool = _create_permissioned_tool_wrapper(server._original_tool)
    return server


# ---------------------------------------------------------------------------
# Manager factories — one per category
# ---------------------------------------------------------------------------
# Each manager is registered here with @lru_cache. Managers are added as
# their modules are built. During incremental development, importing a
# non-existent manager is fine because the factory is only called when
# the matching tool module is loaded.


@lru_cache
def get_shop_manager():
    from etsy_mcp.managers.shop_manager import ShopManager

    return ShopManager(get_client())


@lru_cache
def get_listing_manager():
    from etsy_mcp.managers.listing_manager import ListingManager

    return ListingManager(get_client())


@lru_cache
def get_image_manager():
    from etsy_mcp.managers.image_manager import ImageManager

    return ImageManager(get_client())


@lru_cache
def get_video_manager():
    from etsy_mcp.managers.video_manager import VideoManager

    return VideoManager(get_client())


@lru_cache
def get_inventory_manager():
    from etsy_mcp.managers.inventory_manager import InventoryManager

    return InventoryManager(get_client())


@lru_cache
def get_property_manager():
    from etsy_mcp.managers.property_manager import PropertyManager

    return PropertyManager(get_client())


@lru_cache
def get_translation_manager():
    from etsy_mcp.managers.translation_manager import TranslationManager

    return TranslationManager(get_client())


@lru_cache
def get_digital_file_manager():
    from etsy_mcp.managers.digital_file_manager import DigitalFileManager

    return DigitalFileManager(get_client())


@lru_cache
def get_receipt_manager():
    from etsy_mcp.managers.receipt_manager import ReceiptManager

    return ReceiptManager(get_client())


@lru_cache
def get_payment_manager():
    from etsy_mcp.managers.payment_manager import PaymentManager

    return PaymentManager(get_client())


@lru_cache
def get_shipping_manager():
    from etsy_mcp.managers.shipping_manager import ShippingManager

    return ShippingManager(get_client())


@lru_cache
def get_review_manager():
    from etsy_mcp.managers.review_manager import ReviewManager

    return ReviewManager(get_client())


@lru_cache
def get_taxonomy_manager():
    from etsy_mcp.managers.taxonomy_manager import TaxonomyManager

    return TaxonomyManager(get_client())


@lru_cache
def get_user_manager():
    from etsy_mcp.managers.user_manager import UserManager

    return UserManager(get_client())


@lru_cache
def get_buyer_manager():
    from etsy_mcp.managers.buyer_manager import BuyerManager

    return BuyerManager(get_client())


# ---------------------------------------------------------------------------
# Shorthand aliases (created lazily on first access)
# ---------------------------------------------------------------------------
# These are NOT created at import time because doing so would force every
# manager module to exist before the scaffolding is complete. Import them
# explicitly as needed:
#
#   from etsy_mcp.runtime import get_shop_manager
#   shop_manager = get_shop_manager()
#
# This differs from unifi-mcp's pattern of creating them at import time.
# The reason: etsy-mcp is built incrementally and not all managers exist
# in early phases.

logger.debug("runtime.py: factories registered, singletons will be created on demand")
