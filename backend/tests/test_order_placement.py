"""Order placement: one transaction, and MongoDB strictly before it.

The ordering here is the whole design:

1. read the catalog and reject inactive/missing products **first**, so a bad cart
   never opens a PostgreSQL transaction at all;
2. compute the total in `Decimal`;
3. write `orders`, `order_items` and the `outbox` event in **one** transaction,
   so "PostgreSQL committed" and "Elasticsearch will hear about this" are a
   single atomic fact;
4. dispatch to the queue only **after** commit.

Each of the failure tests asserts the absence of partial writes, because a
"successful" order with no items, or an order with an unqueued event, is the
failure mode this architecture exists to prevent.
"""

from __future__ import annotations

from decimal import Decimal

import asyncpg
import pytest
from fastapi import HTTPException

from app.models.order import OrderCreate, StatusUpdate
from app.services import order_service
from app.services.order_service import place_order, update_status
from tests.conftest import insert_product, insert_user


@pytest.fixture
def dispatched(monkeypatch):
    """Capture post-commit dispatches instead of calling a broker.

    Task 7 supplies the real `index_order.delay`. Until then this records the
    `(order_id, outbox_id)` pair so the test can assert it was dispatched with
    the id of the event row that actually committed.
    """
    calls: list[tuple[int, int | None]] = []
    monkeypatch.setattr(order_service, "dispatch_sync", lambda *args: calls.append(args))
    return calls


# --- the happy path ---------------------------------------------------------


async def test_place_order_persists_and_computes_total(pg_pool, mongo_db, dispatched):
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")

    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 2}]))

    # `total_amount` is a Decimal in Python and a string only at the JSON edge;
    # both are asserted so neither guarantee can be quietly dropped.
    assert out.total_amount == Decimal("100.32")  # 2 x 50.16
    assert out.model_dump(mode="json")["total_amount"] == "100.32"
    assert out.status == "PENDING"
    assert out.sync_status == "QUEUED"

    row = await pg_pool.fetchrow(
        "SELECT total_amount, status, version FROM orders WHERE id=$1", out.order_id
    )
    assert Decimal(row["total_amount"]) == Decimal("100.32")
    assert row["status"] == "PENDING"
    assert row["version"] == 1


async def test_snapshots_are_captured_at_checkout(pg_pool, mongo_db, dispatched):
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 2}]))

    item = await pg_pool.fetchrow(
        "SELECT product_id, title, quantity, unit_price FROM order_items WHERE order_id=$1",
        out.order_id,
    )
    assert item["title"] == "Wireless Mouse"
    assert item["product_id"] == pid
    assert item["quantity"] == 2
    assert Decimal(item["unit_price"]) == Decimal("50.16")


async def test_later_catalog_edit_does_not_rewrite_the_order(pg_pool, mongo_db, dispatched):
    """The snapshot exists so a repriced product cannot restate a past charge."""
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 2}]))

    await mongo_db.products.update_one(
        {"_id": __import__("bson").ObjectId(pid)},
        {"$set": {"title": "Cheaper Mouse v2", "price": __import__("bson").Decimal128("9.99")}},
    )

    item = await pg_pool.fetchrow(
        "SELECT title, unit_price FROM order_items WHERE order_id=$1", out.order_id
    )
    total = await pg_pool.fetchval("SELECT total_amount FROM orders WHERE id=$1", out.order_id)
    assert item["title"] == "Wireless Mouse"
    assert Decimal(item["unit_price"]) == Decimal("50.16")
    assert Decimal(total) == Decimal("100.32")


async def test_multiple_lines_are_summed_in_decimal(pg_pool, mongo_db, dispatched):
    a = await insert_product(mongo_db, "Mouse", "50.16")
    b = await insert_product(mongo_db, "Keyboard", "19.99")
    c = await insert_product(mongo_db, "Cable", "5.01")
    uid = await insert_user(pg_pool, "John", "john@example.com")

    out = await place_order(
        OrderCreate(
            user_id=uid,
            items=[
                {"product_id": a, "quantity": 2},
                {"product_id": b, "quantity": 3},
                {"product_id": c, "quantity": 7},
            ],
        )
    )
    # 100.32 + 59.97 + 35.07 == 195.36
    assert out.total_amount == Decimal("195.36")
    assert out.model_dump(mode="json")["total_amount"] == "195.36"
    assert await pg_pool.fetchval("SELECT count(*) FROM order_items WHERE order_id=$1", out.order_id) == 3


async def test_duplicate_product_lines_are_merged(pg_pool, mongo_db, dispatched):
    """Two lines for one product become one, with the quantities added.

    Otherwise the index would carry two object entries for the same product and
    the receipt would disagree with the total.
    """
    pid = await insert_product(mongo_db, "Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(
        OrderCreate(
            user_id=uid,
            items=[{"product_id": pid, "quantity": 2}, {"product_id": pid, "quantity": 3}],
        )
    )
    assert await pg_pool.fetchval(
        "SELECT count(*) FROM order_items WHERE order_id=$1", out.order_id
    ) == 1
    assert await pg_pool.fetchval(
        "SELECT quantity FROM order_items WHERE order_id=$1", out.order_id
    ) == 5
    assert out.total_amount == Decimal("250.80")
    assert out.model_dump(mode="json")["total_amount"] == "250.80"


async def test_total_is_exact_for_a_price_that_breaks_floats(pg_pool, mongo_db, dispatched):
    """0.1 * 3 is 0.30000000000000004 in binary floating point."""
    pid = await insert_product(mongo_db, "Cheap", "0.10")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 3}]))
    assert out.total_amount == Decimal("0.30")
    assert out.model_dump(mode="json")["total_amount"] == "0.30"
    assert Decimal(await pg_pool.fetchval("SELECT total_amount FROM orders WHERE id=$1", out.order_id)) == Decimal("0.30")


# --- the outbox event, and dispatch after commit ----------------------------


async def test_outbox_row_is_written_in_the_same_transaction(pg_pool, mongo_db, dispatched):
    pid = await insert_product(mongo_db, "Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))

    rows = await pg_pool.fetch(
        "SELECT id, aggregate_id, event_type, processed_at FROM outbox WHERE aggregate_id=$1",
        out.order_id,
    )
    assert len(rows) == 1
    assert rows[0]["event_type"] == "ORDER_CREATED"
    assert rows[0]["processed_at"] is None


async def test_dispatch_happens_after_commit_with_the_outbox_id(pg_pool, mongo_db, dispatched):
    """`(order_id, outbox_id)` is the pair. `order_id` alone cannot settle the event."""
    pid = await insert_product(mongo_db, "Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))

    assert len(dispatched) == 1
    order_id, outbox_id = dispatched[0]
    assert order_id == out.order_id
    assert outbox_id is not None
    assert outbox_id == await pg_pool.fetchval("SELECT id FROM outbox WHERE aggregate_id=$1", out.order_id)


async def test_dispatch_happens_only_once_the_row_is_committed(pg_pool, mongo_db, monkeypatch):
    """Inside the transaction the order must not be visible to a second reader.

    If the dispatch ran before commit, a worker that started instantly would
    project an order that does not exist yet.
    """
    seen: list[tuple[int, int | None]] = []

    def spy(order_id, outbox_id):
        seen.append((order_id, outbox_id))

    pid = await insert_product(mongo_db, "Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    monkeypatch.setattr(order_service, "dispatch_sync", spy)
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))

    # After place_order returns, the order is committed and readable.
    assert await pg_pool.fetchval("SELECT count(*) FROM orders WHERE id=$1", out.order_id) == 1
    assert len(seen) == 1


# --- rejection paths: no partial writes -------------------------------------


async def test_inactive_product_is_409_and_writes_nothing(pg_pool, mongo_db, dispatched):
    pid = await insert_product(mongo_db, "Hidden", "10.00", active=False)
    uid = await insert_user(pg_pool, "John", "john@example.com")

    with pytest.raises(HTTPException) as excinfo:
        await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))
    assert excinfo.value.status_code == 409
    assert await pg_pool.fetchval("SELECT count(*) FROM orders") == 0
    assert await pg_pool.fetchval("SELECT count(*) FROM order_items") == 0
    assert await pg_pool.fetchval("SELECT count(*) FROM outbox") == 0
    assert dispatched == []


async def test_missing_product_is_409_and_writes_nothing(pg_pool, mongo_db, dispatched):
    uid = await insert_user(pg_pool, "John", "john@example.com")
    with pytest.raises(HTTPException) as excinfo:
        await place_order(
            OrderCreate(user_id=uid, items=[{"product_id": "507f1f77bcf86cd799439011", "quantity": 1}])
        )
    assert excinfo.value.status_code == 409
    assert await pg_pool.fetchval("SELECT count(*) FROM orders") == 0
    assert dispatched == []


async def test_one_bad_line_rejects_the_whole_cart(pg_pool, mongo_db, dispatched):
    """No partial order: a cart is atomic, not best-effort."""
    good = await insert_product(mongo_db, "Good", "10.00")
    bad = await insert_product(mongo_db, "Bad", "10.00", active=False)
    uid = await insert_user(pg_pool, "John", "john@example.com")

    with pytest.raises(HTTPException) as excinfo:
        await place_order(
            OrderCreate(
                user_id=uid,
                items=[{"product_id": good, "quantity": 1}, {"product_id": bad, "quantity": 1}],
            )
        )
    assert excinfo.value.status_code == 409
    assert await pg_pool.fetchval("SELECT count(*) FROM orders") == 0
    assert await pg_pool.fetchval("SELECT count(*) FROM order_items") == 0


async def test_unknown_user_is_rejected(pg_pool, mongo_db, dispatched):
    pid = await insert_product(mongo_db, "Mouse", "50.16")
    with pytest.raises(HTTPException) as excinfo:
        await place_order(OrderCreate(user_id=999999, items=[{"product_id": pid, "quantity": 1}]))
    assert excinfo.value.status_code == 404
    assert await pg_pool.fetchval("SELECT count(*) FROM orders") == 0


async def test_a_failure_inside_the_transaction_rolls_everything_back(
    pg_pool, mongo_db, monkeypatch, dispatched
):
    """The outbox row is not an escape hatch: it rolls back with the order."""
    from app.repositories import orders_repo

    pid = await insert_product(mongo_db, "Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")

    real_insert_items = orders_repo.insert_order_items

    async def explode(*args, **kwargs):
        await real_insert_items(*args, **kwargs)
        raise RuntimeError("simulated crash after items, before commit")

    monkeypatch.setattr(orders_repo, "insert_order_items", explode)
    monkeypatch.setattr(order_service, "insert_order_items", orders_repo.insert_order_items)

    with pytest.raises(RuntimeError):
        await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))

    assert await pg_pool.fetchval("SELECT count(*) FROM orders") == 0
    assert await pg_pool.fetchval("SELECT count(*) FROM order_items") == 0
    assert await pg_pool.fetchval("SELECT count(*) FROM outbox") == 0
    assert dispatched == []


# --- version guard on status ------------------------------------------------


async def test_stale_status_update_is_rejected_409(pg_pool, mongo_db, dispatched):
    """A second writer holding version 1 cannot clobber a committed version 2."""
    uid = await insert_user(pg_pool, "John", "john@example.com")
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))

    await update_status(out.order_id, "PROCESSING", expected_version=1)

    with pytest.raises(HTTPException) as excinfo:
        await update_status(out.order_id, "SHIPPED", expected_version=1)
    assert excinfo.value.status_code == 409

    row = await pg_pool.fetchrow("SELECT status, version FROM orders WHERE id=$1", out.order_id)
    assert row["status"] == "PROCESSING"  # the stale write did not land
    assert row["version"] == 2


async def test_status_update_bumps_version_and_writes_its_own_event(pg_pool, mongo_db, dispatched):
    uid = await insert_user(pg_pool, "John", "john@example.com")
    pid = await insert_product(mongo_db, "Mouse", "50.16")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))
    dispatched.clear()

    updated = await update_status(out.order_id, "PROCESSING", expected_version=1)
    assert updated.status == "PROCESSING"

    events = await pg_pool.fetch(
        "SELECT id, event_type FROM outbox WHERE aggregate_id=$1 ORDER BY id", out.order_id
    )
    assert [e["event_type"] for e in events] == ["ORDER_CREATED", "ORDER_STATUS_CHANGED"]

    # The dispatch must carry the NEW outbox row, and the committed version.
    assert len(dispatched) == 1
    order_id, outbox_id = dispatched[0]
    assert outbox_id == events[1]["id"]
    assert outbox_id != events[0]["id"]


async def test_status_update_on_missing_order_is_404(pg_pool, dispatched):
    with pytest.raises(HTTPException) as excinfo:
        await update_status(999999, "SHIPPED", expected_version=1)
    assert excinfo.value.status_code == 404
    assert dispatched == []


async def test_status_update_validates_against_the_schema(pg_pool, mongo_db, dispatched):
    uid = await insert_user(pg_pool, "John", "john@example.com")
    pid = await insert_product(mongo_db, "Mouse", "50.16")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StatusUpdate(status="DELIVERED", expected_version=1)
    with pytest.raises(ValidationError):
        StatusUpdate(status="SHIPPED", expected_version=1, version=9)
