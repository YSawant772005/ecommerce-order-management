"""Rebuild the Elasticsearch orders index from PostgreSQL in one step.

Usage (from `backend/`):  python -m scripts.reindex_orders
"""

from __future__ import annotations

import asyncio


async def main() -> dict:
    import asyncpg
    from elasticsearch import AsyncElasticsearch

    from app.core.elasticsearch import ensure_orders_index
    from app.core.settings import get_settings
    from app.repositories import orders_repo
    from app.services import sync_service

    settings = get_settings()
    pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=5)
    es = AsyncElasticsearch(settings.es_url, request_timeout=30)
    try:
        if await es.indices.exists(index=settings.es_orders_index):
            await es.indices.delete(index=settings.es_orders_index)
        await ensure_orders_index()
        async with pool.acquire() as conn:
            oids = await orders_repo.list_order_ids(conn)
        for oid in oids:
            await sync_service.index_order(oid, None)
        await es.indices.refresh(index=settings.es_orders_index)
        print(f"indexed={len(oids)}")
        return {"indexed": len(oids)}
    finally:
        await es.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
