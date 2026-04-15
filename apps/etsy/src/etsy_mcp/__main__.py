"""etsy-mcp entry point.

Dispatches to:
- `etsy-mcp` or `etsy-mcp serve` — start the MCP server (stdio mode)
- `etsy-mcp auth login` — run the interactive OAuth PKCE bootstrap
- `etsy-mcp auth info` — display current token state (redacted)
- `etsy-mcp auth logout` — delete stored tokens
"""

from __future__ import annotations

import asyncio
import logging
import sys

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure stderr-only logging per AGENTS.md rules."""
    import os

    level = os.environ.get("ETSY_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main() -> None:
    """CLI dispatch."""
    _configure_logging()

    args = sys.argv[1:]
    if not args or args[0] in ("serve", "--serve"):
        # Default: start the MCP server
        from etsy_mcp.main import run_server

        asyncio.run(run_server())
        return

    if args[0] == "auth":
        from etsy_mcp.cli.auth import auth_cli

        auth_cli(args[1:])
        return

    if args[0] in ("--version", "-V"):
        from etsy_mcp import __version__

        print(f"etsy-mcp {__version__}")
        return

    if args[0] in ("--help", "-h"):
        print("etsy-mcp — Etsy MCP server")
        print()
        print("Usage:")
        print("  etsy-mcp                   Start MCP server (stdio mode)")
        print("  etsy-mcp serve             Start MCP server (explicit)")
        print("  etsy-mcp auth login        Interactive OAuth PKCE bootstrap")
        print("  etsy-mcp auth info         Show current token state (redacted)")
        print("  etsy-mcp auth logout       Delete stored tokens")
        print("  etsy-mcp --version         Show version")
        print("  etsy-mcp --help            Show this help")
        return

    print(f"Unknown command: {args[0]}", file=sys.stderr)
    print("Run `etsy-mcp --help` for usage.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
