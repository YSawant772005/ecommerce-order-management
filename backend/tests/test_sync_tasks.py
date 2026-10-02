"""Sync tasks: idempotent ES writes with stale-version protection.

A stale version is terminal (`mark_superseded`, never retried); an outage is
retryable (`mark_failed`, row stays pending). The worker settles only the
event id it was handed.
"""

from __future__ import annotations

import pytest
from elasticsearch import ConflictError

from app.repositories import outbox_repo
from app.services import sync_service
from tests.conftest import insert_items, insert_order, insert_user


async def _enqueue(pg_pool, aggregate_id, event="ORDER_CREATED"):
    async with pg_pool.acquire() as conn:
        return await outbox_repo.enqueue(conn, aggregate_id, event)


async def _placed_order(pg_pool):
    uid = await insert_user(pg_pool, "John", "john@example.com")
    oid = await insert_order(pg_pool, uid, "100.32")
    await insert_items(pg_pool, oid, [("p1", "Wireless Mouse", 2, "50.16")])
    return oid


async def test_stale_write_cannot_overwrite_newer_doc(es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    await es.index(
        index="orders", id="1",
        document={"order_id": 1, "version": 2, "status": "SHIPPED"},
        version=2, version_type="external",
    )
    with pytest.raises(ConflictError):
        await es.index(
            index="orders", id="1",
            document={"order_id": 1, "version": 1, "status": "PENDING"},
            version=1, version_type="external",
        )
    await es.indices.refresh(index="orders")
    got = (await es.get(index="orders", id="1"))["_source"]
    assert got["status"] == "SHIPPED"


async def test_version_conflict_is_terminal_not_retried(pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed_order(pg_pool)
    row_id = await _enqueue(pg_pool, oid)
    await es.index(
        index="orders", id=str(oid),
        document={"order_id": oid, "version": 99},
        version=99, version_type="external",
    )
    await sync_service.index_order(oid, row_id)  # must not raise
    async with pg_pool.acquire() as conn:
        row = await outbox_repo.get(conn, row_id)
    assert row["processed_at"] is not None
    assert row["attempts"] == 0
    assert "superseded" in (row["last_error"] or "")


async def test_es_outage_is_retried_then_terminal(pg_pool, es, monkeypatch):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed_order(pg_pool)
    row_id = await _enqueue(pg_pool, oid)

    async def _down(*args, **kwargs):
        from elasticsearch import ConnectionError

        raise ConnectionError("es down")

    es_client = await sync_service.get_es()
    monkeypatch.setattr(es_client, "index", _down)
    with pytest.raises(Exception):
        await sync_service.index_order(oid, row_id)
    async with pg_pool.acquire() as conn:
        row = await outbox_repo.get(conn, row_id)
    assert row["processed_at"] is None
    assert row["attempts"] == 1

    for _ in range(outbox_repo.MAX_ATTEMPTS - 1):
        with pytest.raises(Exception):
            await sync_service.index_order(oid, row_id)
    async with pg_pool.acquire() as conn:
        row = await outbox_repo.get(conn, row_id)
    assert row["processed_at"] is not None


async def test_index_order_settles_only_its_own_row(pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed_order(pg_pool)
    created = await _enqueue(pg_pool, oid, "ORDER_CREATED")
    changed = await _enqueue(pg_pool, oid, "ORDER_STATUS_CHANGED")
    await es.index(
        index="orders", id=str(oid),
        document={"order_id": oid, "version": 99},
        version=99, version_type="external",
    )
    await sync_service.index_order(oid, created)
    async with pg_pool.acquire() as conn:
        assert (await outbox_repo.get(conn, created))["processed_at"] is not None
        sibling = await outbox_repo.get(conn, changed)
    assert sibling["processed_at"] is None
    assert sibling["attempts"] == 0


async def test_index_order_without_outbox_id_settles_nothing(pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed_order(pg_pool)
    row_id = await _enqueue(pg_pool, oid)
    await sync_service.index_order(oid, None)
    async with pg_pool.acquire() as conn:
        assert (await outbox_repo.get(conn, row_id))["processed_at"] is None
    await es.indices.refresh(index="orders")
    assert (await es.get(index="orders", id=str(oid)))["_source"]["order_id"] == oid


async def test_duplicate_delivery_settles_once(pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed_order(pg_pool)
    row_id = await _enqueue(pg_pool, oid)
    await sync_service.index_order(oid, row_id)
    async with pg_pool.acquire() as conn:
        first = (await outbox_repo.get(conn, row_id))["processed_at"]
    await sync_service.index_order(oid, row_id)
    async with pg_pool.acquire() as conn:
        row = await outbox_repo.get(conn, row_id)
    assert row["processed_at"] == first
    assert row["attempts"] == 0


async def test_happy_path_indexes_and_settles(pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed_order(pg_pool)
    row_id = await _enqueue(pg_pool, oid)
    await sync_service.index_order(oid, row_id)
    await es.indices.refresh(index="orders")
    stored = (await es.get(index="orders", id=str(oid)))["_source"]
    assert stored["total_amount"] == "100.32"
    assert stored["version"] == 1
    async with pg_pool.acquire() as conn:
        assert (await outbox_repo.get(conn, row_id))["processed_at"] is not None
