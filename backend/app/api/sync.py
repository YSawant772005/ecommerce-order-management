"""Sync badge and maintenance routes. PG + ES reads, never MongoDB."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.sync import SyncStatusOut

router = APIRouter()


@router.get("/sync/status/{order_id}", response_model=SyncStatusOut)
async def sync_status(order_id: int) -> SyncStatusOut:
    from elasticsearch import NotFoundError

    from app.core.elasticsearch import get_es
    from app.core.postgres import get_pool
    from app.core.settings import get_settings
    from app.repositories import orders_repo
    from app.services.sync_service import IN_SYNC, MISSING_IN_ES, OUT_OF_SYNC

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await orders_repo.fetch_order_row(conn, order_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"order {order_id} not found")
        pending = await conn.fetchval(
            "SELECT count(*) FROM outbox WHERE aggregate_id=$1 AND processed_at IS NULL",
            order_id,
        )
        last_error = await conn.fetchval(
            "SELECT last_error FROM outbox WHERE aggregate_id=$1"
            " AND last_error IS NOT NULL ORDER BY id DESC LIMIT 1",
            order_id,
        )
    es = await get_es()
    try:
        stored = (await es.get(index=get_settings().es_orders_index, id=str(order_id)))[
            "_source"
        ]
        es_version: int | None = stored.get("version")
    except NotFoundError:
        es_version = None
    if es_version is None:
        state = MISSING_IN_ES
    elif es_version == row["version"]:
        state = IN_SYNC
    else:
        state = OUT_OF_SYNC
    return SyncStatusOut(
        order_id=order_id,
        state=state,
        pg_version=row["version"],
        es_version=es_version,
        pending_outbox_events=pending,
        last_error=last_error,
    )


@router.post("/sync/drain-outbox")
async def drain_outbox(limit: int = 100) -> dict[str, int]:
    from app.services import sync_service

    return await sync_service.drain_outbox(limit)


@router.post("/sync/reindex")
async def reindex() -> dict[str, int]:
    """Delete, recreate, and fully repopulate the orders index from PG."""
    from app.core.elasticsearch import ensure_orders_index, get_es
    from app.core.postgres import get_pool
    from app.core.settings import get_settings
    from app.repositories import orders_repo
    from app.services import sync_service

    es = await get_es()
    index = get_settings().es_orders_index
    if await es.indices.exists(index=index):
        await es.indices.delete(index=index)
    await ensure_orders_index()
    pool = await get_pool()
    async with pool.acquire() as conn:
        oids = await orders_repo.list_order_ids(conn)
    for oid in oids:
        await sync_service.index_order(oid, None)
    return {"indexed": len(oids)}
