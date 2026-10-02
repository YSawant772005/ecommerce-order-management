"""Vertical-slice API tests: health, products, users, orders (PG + Mongo).

RED first: `app.main` does not exist yet, so collection errors until the
slice routers land. Uses real stores via the shared `pg_pool`/`mongo_db`
fixtures; HTTP via httpx ASGI (no network port needed).
"""

from __future__ import annotations

import pytest


async def test_health_ok(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert set(r.json()) == {"postgres", "mongo", "elasticsearch"}


async def test_products_list_empty_then_one(client, mongo_db):
    r = await client.get("/api/products")
    assert r.status_code == 200
    assert r.json() == []

    from tests.conftest import insert_product

    await insert_product(mongo_db, "Wireless Mouse", "50.16")
    r2 = await client.get("/api/products")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body) == 1
    assert body[0]["title"] == "Wireless Mouse"
    # Money crosses the wire as a string, never a float.
    assert body[0]["price"] == "50.16"


async def test_users_list(client, pg_pool):
    from tests.conftest import insert_user

    await insert_user(pg_pool, "John Doe", "john.doe@example.com")
    r = await client.get("/api/users")
    assert r.status_code == 200
    assert r.json()[0]["email"] == "john.doe@example.com"


async def test_create_and_get_order(client, pg_pool, mongo_db):
    from tests.conftest import insert_product, insert_user

    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")

    r = await client.post(
        "/api/orders", json={"user_id": uid, "items": [{"product_id": pid, "quantity": 2}]}
    )
    assert r.status_code == 201, r.text
    assert r.json()["total_amount"] == "100.32"
    assert r.json()["sync_status"] == "QUEUED"
    oid = r.json()["order_id"]

    g = await client.get(f"/api/orders/{oid}")
    assert g.status_code == 200
    detail = g.json()
    assert detail["total_amount"] == "100.32"
    assert detail["items"][0]["title"] == "Wireless Mouse"
    assert detail["version"] == 1


async def test_create_order_rejects_client_price(client):
    r = await client.post(
        "/api/orders",
        json={"user_id": 1, "items": [{"product_id": "x", "quantity": 1, "unit_price": "0.01"}]},
    )
    assert r.status_code == 422
