"""MCP tool modules — one per category.

Each tool module imports managers via runtime.get_*_manager(), registers
tools via @server.tool(), and returns standardized envelopes.

Tools MUST be thin wrappers: validate → delegate → envelope. No business
logic. No HTTP. No reasoning.
"""
