"""etsy-mcp server entry point.

Responsibilities:
- Initialize the FastMCP server via runtime.get_server()
- Install the permissioned_tool decorator from etsy-mcp-shared
- Import all tool modules (triggers @server.tool() registration)
- Run the stdio transport loop

For the CLI auth subcommand, see etsy_mcp/cli/auth.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_server() -> None:
    """Start the MCP server and run the stdio transport loop."""
    from etsy_mcp.bootstrap import load_config
    from etsy_mcp.runtime import get_server

    # Load config first to fail-fast on missing credentials
    cfg = load_config()
    logger.info("Starting etsy-mcp server (log_level=%s)", getattr(cfg.server, "log_level", "INFO"))

    server = get_server()

    # Install the permissioned_tool decorator from the shared package
    _install_permissioned_tool(server)

    # Import all tool modules — triggers @server.tool() registration
    _register_tools()

    # Run stdio transport
    logger.info("etsy-mcp server ready. Listening on stdio.")
    await server.run_stdio_async()


def _install_permissioned_tool(server) -> None:
    """Install the permissioned_tool decorator + policy gate checker.

    Imports from etsy-mcp-shared. If the shared package isn't installed yet
    (early development), falls back to a no-op wrapper so the server can
    still start for smoke testing.
    """
    try:
        from etsy_mcp_shared.diagnostics import wrap_tool
        from etsy_mcp_shared.permissioned_tool import setup_permissioned_tool
        from etsy_mcp_shared.tool_index import register_tool

        from etsy_mcp.categories import ETSY_CATEGORY_MAP

        setup_permissioned_tool(
            server=server,
            category_map=ETSY_CATEGORY_MAP,
            server_prefix="ETSY",
            register_tool_fn=register_tool,
            diagnostics_enabled_fn=lambda: False,
            wrap_tool_fn=wrap_tool,
            logger=logger,
        )
        logger.info("permissioned_tool decorator installed with %d categories", len(ETSY_CATEGORY_MAP))
    except ImportError as exc:
        logger.warning(
            "etsy-mcp-shared not installed (import failed: %s). "
            "Running without permissioned_tool wrapper — tools will work but policy gates are disabled.",
            exc,
        )


def _register_tools() -> None:
    """Import every tool module to trigger @server.tool() decorators."""
    # Import in category order. Each import may fail during incremental
    # development — we catch and log rather than crashing the whole server.
    categories = [
        "shops",
        "listings",
        "listing_images",
        "listing_videos",
        "listing_inventory",
        "listing_properties",
        "listing_translations",
        "listing_digital_files",
        "receipts",
        "payments",
        "shipping",
        "reviews",
        "taxonomy",
        "users",
        "buyer",
    ]

    registered = 0
    for name in categories:
        try:
            __import__(f"etsy_mcp.tools.{name}")
            registered += 1
        except ImportError as exc:
            logger.warning("Tool module etsy_mcp.tools.%s not available: %s", name, exc)
        except Exception as exc:
            logger.error("Failed to import etsy_mcp.tools.%s: %s", name, exc, exc_info=True)

    logger.info("Tool modules registered: %d / %d", registered, len(categories))
