"""Sync badge + maintenance routes, and catalog write routes."""

from __future__ import annotations

from app.repositories import outbox_repo
from app.services import sync_service
from tests.conftest import insert_items, insert_order, insert_product, insert_user


async def _placed(pg_pool, email="john@example.com"):
    uid = await insert_user(pg_pool, "John", email)
    oid = await insert_order(pg_pool, uid, "100.32")
    await insert_items(pg_pool, oid, [("p1", "Wireless Mouse", 2, "50.16")])
    return oid


async def test_sync_status_in_sync(client, pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed(pg_pool)
    await sync_service.index_order(oid, None)
    r = await client.get(f"/api/sync/status/{oid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "IN_SYNC"
    assert body["pg_version"] == body["es_version"] == 1


async def test_sync_status_missing_in_es(client, pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed(pg_pool)
    r = await client.get(f"/api/sync/status/{oid}")
    assert r.json()["state"] == "MISSING_IN_ES"
    assert r.json()["es_version"] is None


async def test_sync_status_out_of_sync_after_update(client, pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed(pg_pool)
    await sync_service.index_order(oid, None)
    await pg_pool.execute("UPDATE orders SET status='SHIPPED' WHERE id=$1", oid)
    r = await client.get(f"/api/sync/status/{oid}")
    body = r.json()
    assert body["state"] == "OUT_OF_SYNC"
    assert body["pg_version"] == 2 and body["es_version"] == 1


async def test_sync_status_missing_order_404(client, pg_pool):
    r = await client.get("/api/sync/status/999999")
    assert r.status_code == 404


async def test_drain_outbox_settles_and_indexes(client, pg_pool, es):
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    oid = await _placed(pg_pool)
    async with pg_pool.acquire() as conn:
        row_id = await outbox_repo.enqueue(conn, oid, "ORDER_CREATED")
    r = await client.post("/api/sync/drain-outbox")
    assert r.status_code == 200, r.text
    assert r.json()["settled"] == 1
    await es.indices.refresh(index="orders")
    assert (await es.get(index="orders", id=str(oid)))["_source"]["order_id"] == oid
    async with pg_pool.acquire() as conn:
        assert (await outbox_repo.get(conn, row_id))["processed_at"] is not None


async def test_reindex_rebuilds_all_docs(client, pg_pool, es):
    a = await _placed(pg_pool, "a@example.com")
    b = await _placed(pg_pool, "b@example.com")
    r = await client.post("/api/sync/reindex")
    assert r.status_code == 200, r.text
    assert r.json()["indexed"] == 2
    await es.indices.refresh(index="orders")
    for oid in (a, b):
        assert (await es.get(index="orders", id=str(oid)))["_source"]["order_id"] == oid


async def test_create_and_update_product(client, mongo_db):
    r = await client.post(
        "/api/products",
        json={
            "sku": "WM-001", "title": "Wireless Mouse", "price": "50.16",
            "category": "peripherals", "tags": ["wireless"],
            "attributes": {"color": "black"},
            "variants": [{"sku": "WM-001-BLK", "stock": 3}],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["price"] == "50.16"
    pid = r.json()["_id"]

    dup = await client.post(
        "/api/products",
        json={
            "sku": "WM-001", "title": "Other", "price": "9.99",
            "category": "peripherals", "attributes": {"x": 1},
            "variants": [{"sku": "O-1", "stock": 1}],
        },
    )
    assert dup.status_code == 409

    upd = await client.put(f"/api/products/{pid}", json={"price": "79.00"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["price"] == "79.00"

    missing = await client.put("507f1f77bcf86cd799439011", json={"price": "1.00"})
    assert missing.status_code == 404


async def test_create_product_rejects_bare_document(client):
    r = await client.post(
        "/api/products",
        json={
            "sku": "BARE-1", "title": "Bare", "price": "9.99",
            "category": "office", "attributes": {}, "variants": [],
        },
    )
    assert r.status_code == 422
