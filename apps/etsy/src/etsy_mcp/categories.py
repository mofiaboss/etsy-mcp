"""Etsy server category mapping and tool module map.

Maps tool category shorthands to config keys (for policy gate resolution)
and tool names to module paths (for lazy loading).

Inherits the pattern from unifi-mcp's apps/network/src/unifi_network_mcp/categories.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Permission category mapping
# ---------------------------------------------------------------------------

#: Mapping from tool category shorthand to config key.
#: Used by policy_gate to resolve env vars: ETSY_POLICY_<CATEGORY_KEY>_<ACTION>
ETSY_CATEGORY_MAP: dict[str, str] = {
    "shops": "shops",
    "listings": "listings",
    "listing_images": "listing_images",
    "listing_videos": "listing_videos",
    "listing_inventory": "listing_inventory",
    "listing_properties": "listing_properties",
    "listing_translations": "listing_translations",
    "listing_digital_files": "listing_digital_files",
    "receipts": "receipts",
    "payments": "payments",
    "shipping": "shipping",
    "reviews": "reviews",
    "taxonomy": "taxonomy",
    "users": "users",
    "buyer": "buyer",
}

#: Backward-compatible alias
CATEGORY_MAP = ETSY_CATEGORY_MAP


# ---------------------------------------------------------------------------
# Tool module map (lazy loading)
# ---------------------------------------------------------------------------

_MANIFEST_PATH = Path(__file__).parent / "tools_manifest.json"
_MANIFEST_FALLBACK = Path("apps/etsy/src/etsy_mcp/tools_manifest.json")


def _build_tool_module_map() -> dict[str, str]:
    """Build tool-to-module mapping by scanning tool files for @server.tool decorators.

    Uses the shared lazy_tools.build_tool_module_map helper which scans the
    tools/ directory for patterns like `name="etsy_..."` in decorators.
    """
    try:
        from etsy_mcp_shared.lazy_tools import build_tool_module_map

        manifest = _MANIFEST_PATH if _MANIFEST_PATH.exists() else _MANIFEST_FALLBACK
        return build_tool_module_map(
            tools_package="etsy_mcp.tools",
            manifest_path=str(manifest),
            tool_prefix="etsy_",
        )
    except ImportError:
        # etsy-mcp-shared not yet installed (e.g., during initial scaffolding)
        return {}


#: Built at module load time by scanning tool files.
TOOL_MODULE_MAP: dict[str, str] = _build_tool_module_map()


def setup_lazy_loading(server: object, tool_decorator: Callable) -> object:
    """Install lazy tool loading for the etsy-mcp app.

    Delegates to the shared helper. Called by main.py during server startup.
    """
    from etsy_mcp_shared.lazy_tools import setup_lazy_loading as _shared_setup

    return _shared_setup(
        server=server,
        tool_decorator=tool_decorator,
        tool_module_map=TOOL_MODULE_MAP,
    )
