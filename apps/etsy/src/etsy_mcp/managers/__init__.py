"""Domain managers — one per Etsy API resource category.

Managers delegate all HTTP to EtsyClient. Tools delegate all business logic
to managers. Cross-manager composition is forbidden (no orchestrators).
See development/04-architecture.md for the layering rules.
"""
