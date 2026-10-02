"""Liveness of the three stores."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """UP/DOWN per store. Never raises: a down store reports DOWN."""
    from app.core.settings import get_settings

    out: dict[str, str] = {}
    try:
        pool = await __import__("app.core.postgres", fromlist=["get_pool"]).get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        out["postgres"] = "UP"
    except Exception:
        out["postgres"] = "DOWN"
    try:
        mongo = await __import__("app.core.mongo", fromlist=["get_mongo"]).get_mongo()
        await mongo.admin.command("ping")
        out["mongo"] = "UP"
    except Exception:
        out["mongo"] = "DOWN"
    try:
        es = await __import__("app.core.elasticsearch", fromlist=["get_es"]).get_es()
        await es.info()
        out["elasticsearch"] = "UP"
    except Exception:
        out["elasticsearch"] = "DOWN"
    _ = get_settings()
    return out
