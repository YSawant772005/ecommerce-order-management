"""The single MongoDB client.

MongoDB owns the **product catalog** and nothing else. It is not on the order
synchronization path: no order, order item, status or total is ever written
here, and no historical order is ever reconstructed by reading a product
document back.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.settings import get_settings

_client: AsyncIOMotorClient | None = None


async def get_mongo() -> AsyncIOMotorClient:
    """Process-wide MongoDB client, created on first use."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            get_settings().mongo_dsn,
            serverSelectionTimeoutMS=5000,
            uuidRepresentation="standard",
        )
    return _client


async def get_db() -> AsyncIOMotorDatabase:
    """The catalog database."""
    return (await get_mongo())[get_settings().mongo_db_name]


async def close_mongo() -> None:
    """Close the client if one was opened. Safe to call when there was none."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
