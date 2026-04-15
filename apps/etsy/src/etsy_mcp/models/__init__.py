"""Shared pydantic field models per Etsy API domain.

Each model is the single source of truth for field names, types, and
mutability. List output fields must round-trip to create/update payloads.
See AGENTS.md's "Add or migrate a domain to shared field models" golden path.
"""
