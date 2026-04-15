"""User manager — wraps Etsy User + UserAddress endpoints.

5 operations:
- get_me: GET /users/me — authenticated user profile
- get_by_id: GET /users/{user_id}
- addresses_list: GET /users/{user_id}/addresses
- addresses_get: GET /users/{user_id}/addresses/{user_address_id}
- addresses_delete: DELETE /users/{user_id}/addresses/{user_address_id}

Scopes: profile_r (read user), address_r (list/get addresses), address_w (delete address).
"""

from __future__ import annotations

import logging
from typing import Any

from etsy_core.client import EtsyClient

logger = logging.getLogger(__name__)


class UserManager:
    """Manages Etsy User and UserAddress operations."""

    def __init__(self, client: EtsyClient) -> None:
        self.client = client

    # -------------------------------------------------------------------------
    # User read
    # -------------------------------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        """GET /users/me — authenticated user."""
        return await self.client.get("/users/me")

    async def get_by_id(self, user_id: int) -> dict[str, Any]:
        """GET /users/{user_id}"""
        return await self.client.get(f"/users/{user_id}")

    # -------------------------------------------------------------------------
    # User addresses
    # -------------------------------------------------------------------------

    async def addresses_list(self, user_id: int) -> dict[str, Any]:
        """GET /users/{user_id}/addresses"""
        return await self.client.get(f"/users/{user_id}/addresses")

    async def addresses_get(self, user_id: int, user_address_id: int) -> dict[str, Any]:
        """GET /users/{user_id}/addresses/{user_address_id}"""
        return await self.client.get(f"/users/{user_id}/addresses/{user_address_id}")

    async def addresses_delete(
        self,
        user_id: int,
        user_address_id: int,
    ) -> dict[str, Any]:
        """DELETE /users/{user_id}/addresses/{user_address_id}"""
        return await self.client.delete(f"/users/{user_id}/addresses/{user_address_id}")
