"""etsy-mcp — Professional-grade Etsy MCP server.

Architectural stance: capability layer, not reasoning layer.
The MCP exposes 90 pure-primitive Etsy tools. The LLM installed alongside
brings the intelligence. No scoring, no heuristics, no content generation.

Entry points:
- Server: `python -m etsy_mcp`
- CLI auth: `python -m etsy_mcp auth login`

For architectural rules and tool reference, see:
- `/Users/rvillucci/skunkworks/etsy-mcp-context/00-session-resume.md`
- `/Users/rvillucci/.claude/plans/wise-strolling-aurora.md`
"""

try:
    from etsy_mcp._version import __version__
except ImportError:
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
