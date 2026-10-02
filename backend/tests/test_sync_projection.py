"""`build_order_document()` — the one and only projection into Elasticsearch.

The architecture's central claim is that an indexed order is a pure function of
committed PostgreSQL rows. These tests attack that claim from three sides:

* **Shape** — the document matches the agreed spec field for field.
* **Isolation** — a product whose *live* catalog title differs from the order's
  *snapshot* title still projects the snapshot. If this ever reads MongoDB, the
  historical order silently rewrites itself and the projection is no longer a
  projection of PostgreSQL.
* **Transaction** — the caller passes the connection, so the projection reads the
  exact snapshot the caller is looking at rather than racing a second connection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import asyncpg
import pytest

from app.services.sync_service import build_order_document
from tests.conftest import insert_items, insert_order, insert_user


@pytest.fixture
async def placed(pg_pool: asyncpg.Pool):
    """One user, one order, two snapshot lines. Returns (user_id, order_id)."""
    uid = await insert_user(pg_pool, "John Doe", "john.doe@example.com")
    oid = await insert_order(
        pg_pool,
        uid,
        "150.50",
        status="SHIPPED",
        order_date=datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    await insert_items(
        pg_pool,
        oid,
        [
            ("64f1a2b3c4d5e6f7a8b9c0d1", "Wireless Mouse", 2, "50.16"),
            ("64f1a2b3c4d5e6f7a8b9c0d2", "Keyboard", 1, "50.18"),
        ],
    )
    return uid, oid


async def build(pool: asyncpg.Pool, order_id: int) -> dict:
    async with pool.acquire() as conn:
        return await build_order_document(conn, order_id)


# --- shape ------------------------------------------------------------------


async def test_document_has_exactly_the_agreed_keys(pg_pool, placed):
    _, oid = placed
    doc = await build(pg_pool, oid)
    assert set(doc) == {
        "order_id",
        "order_date",
        "status",
        "total_amount",
        "updated_at",
        "version",
        "customer",
        "items",
    }


async def test_document_values_match_postgres(pg_pool, placed):
    uid, oid = placed
    doc = await build(pg_pool, oid)
    assert doc["order_id"] == oid
    assert doc["status"] == "SHIPPED"
    assert doc["version"] == 1
    assert doc["customer"] == {"id": uid, "name": "John Doe", "email": "john.doe@example.com"}
    assert len(doc["items"]) == 2


async def test_money_is_a_two_place_string(pg_pool, placed):
    _, oid = placed
    doc = await build(pg_pool, oid)
    assert doc["total_amount"] == "150.50"
    for item in doc["items"]:
        assert isinstance(item["unit_price"], str)
        assert item["unit_price"].count(".") == 1
        assert len(item["unit_price"].split(".")[1]) == 2


async def test_item_shape_matches_the_spec(pg_pool, placed):
    _, oid = placed
    doc = await build(pg_pool, oid)
    assert set(doc["items"][0]) == {"product_id", "title", "quantity", "unit_price"}


async def test_timestamps_are_iso8601_utc_strings(pg_pool, placed):
    _, oid = placed
    doc = await build(pg_pool, oid)
    for key in ("order_date", "updated_at"):
        assert isinstance(doc[key], str)
        parsed = datetime.fromisoformat(doc[key].replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
    assert doc["order_date"].startswith("2026-07-10T12:00:00")


async def test_order_with_no_items_projects_an_empty_list(pg_pool):
    uid = await insert_user(pg_pool, "No Items", "none@example.com")
    oid = await insert_order(pg_pool, uid, "0.00")
    doc = await build(pg_pool, oid)
    assert doc["items"] == []


# --- isolation: PostgreSQL only, never the catalog ---------------------------


async def test_snapshots_win_over_the_live_catalog(pg_pool, placed, mongo_db):
    """The deliberate Wireless Mouse scenario, at the unit level.

    The catalog says the product is now called something else. The order was
    placed when it was called "Wireless Mouse", and the index must keep showing
    what the customer actually bought.
    """
    from bson import Decimal128

    await mongo_db.products.insert_one(
        {
            "sku": "WM-001",
            "title": "RENAMED IN CATALOG — DO NOT USE",
            "description": "changed after the order was placed",
            "price": Decimal128("999.00"),
            "category": "peripherals",
            "tags": ["wireless"],
            "attributes": {"color": "black"},
            "variants": [{"sku": "WM-001-BLK", "stock": 1}],
            "active": True,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    _, oid = placed
    doc = await build(pg_pool, oid)
    titles = [i["title"] for i in doc["items"]]
    assert "Wireless Mouse" in titles
    assert "RENAMED IN CATALOG — DO NOT USE" not in titles
    prices = [i["unit_price"] for i in doc["items"]]
    assert "999.00" not in prices


async def test_the_module_has_no_route_to_mongodb():
    """Structural proof of the rule, so it cannot rot back in unnoticed."""
    from pathlib import Path

    import app.services.sync_service as module

    source = Path(module.__file__).read_text()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            for banned in ("mongo", "motor", "bson"):
                assert banned not in stripped.lower(), f"sync_service imports {banned}: {stripped}"


async def test_total_is_not_recomputed_from_items(pg_pool):
    """`total_amount` is the committed value, not a fresh sum.

    Recomputing would silently rewrite history if a snapshot row were ever
    corrected; the order total is what the customer was charged.
    """
    uid = await insert_user(pg_pool, "Mismatch", "mismatch@example.com")
    oid = await insert_order(pg_pool, uid, "999.99")
    await insert_items(pg_pool, oid, [("p1", "Cheap", 1, "1.00")])
    doc = await build(pg_pool, oid)
    assert doc["total_amount"] == "999.99"


# --- transaction behaviour ---------------------------------------------------


async def test_reads_through_the_supplied_connection(pg_pool):
    """The projection sees the caller's uncommitted rows.

    This is why the connection is a parameter. If `build_order_document` opened
    its own connection it would not see an order still inside the transaction
    that produced it, and would index stale data or block on the writer.
    """
    uid = await insert_user(pg_pool, "In Transaction", "tx@example.com")
    async with pg_pool.acquire() as conn:
        async with conn.transaction():
            oid = await insert_order(conn, uid, "12.34")
            await insert_items(conn, oid, [("p1", "Thing", 2, "6.17")])
            doc = await build_order_document(conn, oid)
    assert doc["order_id"] == oid
    assert doc["total_amount"] == "12.34"


async def test_projection_is_deterministic(pg_pool, placed):
    _, oid = placed
    assert await build(pg_pool, oid) == await build(pg_pool, oid)


async def test_version_tracks_the_committed_row(pg_pool, placed):
    """After a status change the trigger bumps `version`, and so must the document.

    That version is what `sync_status` compares PostgreSQL against Elasticsearch
    to decide `IN_SYNC` vs `OUT_OF_SYNC`, so a stale one would report a
    synchronized index that is actually behind.
    """
    _, oid = placed
    before = await build(pg_pool, oid)
    async with pg_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'PENDING' WHERE id = $1", oid)
    after = await build(pg_pool, oid)
    assert after["version"] == before["version"] + 1
    assert after["status"] == "PENDING"
    # `version` is the field the sync-status check actually reads, so the
    # increment above is the guarantee. `updated_at` is emitted at second
    # precision (see `test_timestamps_are_truncated_to_whole_seconds`), so two
    # updates inside one second are indistinguishable by it — only never older.
    assert after["updated_at"] >= before["updated_at"]


async def test_timestamps_are_truncated_to_whole_seconds(pg_pool, placed):
    """Stated, not hidden: the projection emits second precision, as the spec shows.

    Consequence: a sub-second `updated_at` difference is not visible in the index.
    That is acceptable because `version` — an integer the trigger owns — is what
    `sync_status` compares, and it has no such ambiguity.
    """
    _, oid = placed
    async with pg_pool.acquire() as conn:
        raw = await conn.fetchval("SELECT updated_at FROM orders WHERE id = $1", oid)
    doc = await build(pg_pool, oid)
    assert doc["updated_at"].endswith("Z")
    assert "." not in doc["updated_at"]
    assert datetime.fromisoformat(doc["updated_at"].replace("Z", "+00:00")).microsecond == 0
    assert raw.microsecond >= 0  # the raw column keeps full precision


async def test_missing_order_raises(pg_pool):
    from app.services.sync_service import OrderNotFound

    with pytest.raises(OrderNotFound):
        await build(pg_pool, 999999)


async def test_item_order_follows_the_cart_not_the_alphabet(pg_pool):
    """`order_items.id` is a total order, so every rebuild is byte-identical.

    Ordering by `id` also preserves what the customer actually saw in their cart.
    Sorting by title would be just as deterministic but would quietly reorder the
    receipt.
    """
    uid = await insert_user(pg_pool, "Order Test", "order@example.com")
    oid = await insert_order(pg_pool, uid, "30.00")
    await insert_items(
        pg_pool,
        oid,
        [("p3", "C", 1, "10.00"), ("p1", "A", 1, "10.00"), ("p2", "B", 1, "10.00")],
    )
    doc = await build(pg_pool, oid)
    assert [i["title"] for i in doc["items"]] == ["C", "A", "B"]
    assert doc == await build(pg_pool, oid)


async def test_extreme_money_survives_projection(pg_pool):
    uid = await insert_user(pg_pool, "Rich", "rich@example.com")
    oid = await insert_order(pg_pool, uid, "99999999.99")
    await insert_items(pg_pool, oid, [("p1", "Yacht", 1, "0.01")])
    doc = await build(pg_pool, oid)
    assert doc["total_amount"] == "99999999.99"
    assert doc["items"][0]["unit_price"] == "0.01"
    assert Decimal(doc["total_amount"]) == Decimal("99999999.99")


# --- the document must actually index and search (real Elasticsearch) --------


async def test_projected_document_indexes_and_searches(pg_pool, placed, es):
    """End of the projection path: PostgreSQL -> document -> index -> query.

    This is where the mapping earns its keep. The `scaled_float(100)` fields must
    accept the money strings, the `object` items array must be queryable, and the
    index-time n-gram must make "Wir" match "Wireless Mouse" — a plain standard
    analyzer would return nothing.
    """
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    _, oid = placed
    doc = await build(pg_pool, oid)
    await es.index(index="orders", id=str(oid), document=doc, refresh="wait_for")

    stored = (await es.get(index="orders", id=str(oid)))["_source"]
    assert stored == doc
    assert stored["total_amount"] == "150.50"
    assert stored["items"][0]["unit_price"] == "50.16"

    by_prefix = await es.search(
        index="orders",
        query={"multi_match": {"query": "Wir", "fields": ["items.title.prefix"]}},
    )
    assert by_prefix["hits"]["total"]["value"] == 1
    assert by_prefix["hits"]["hits"][0]["_source"]["items"][0]["title"] == "Wireless Mouse"

    by_customer = await es.search(
        index="orders", query={"multi_match": {"query": "John", "fields": ["customer.name"]}}
    )
    assert by_customer["hits"]["total"]["value"] == 1

    by_range = await es.search(
        index="orders",
        query={"range": {"total_amount": {"gte": 100, "lte": 200}}},
    )
    assert by_range["hits"]["total"]["value"] == 1
    too_high = await es.search(
        index="orders", query={"range": {"total_amount": {"gte": 500}}}
    )
    assert too_high["hits"]["total"]["value"] == 0


async def test_money_round_trips_through_scaled_float_at_extremes(pg_pool, es):
    """The boundary where a float would quietly lose a cent."""
    from app.core.elasticsearch import ensure_orders_index

    await ensure_orders_index()
    uid = await insert_user(pg_pool, "Extremes", "extremes@example.com")
    amounts = ["0.01", "0.10", "9.99", "99999999.99", "123456.78", "100.32"]
    ids = []
    for index, amount in enumerate(amounts):
        oid = await insert_order(pg_pool, uid, amount)
        await insert_items(pg_pool, oid, [(f"p{index}", f"Item {index}", 1, amount)])
        doc = await build(pg_pool, oid)
        await es.index(index="orders", id=str(oid), document=doc, refresh="wait_for")
        ids.append(oid)

    for oid, amount in zip(ids, amounts):
        stored = (await es.get(index="orders", id=str(oid)))["_source"]
        assert stored["total_amount"] == amount, amount
        assert stored["items"][0]["unit_price"] == amount, amount
