"""The `orders_touch` trigger owns `updated_at` and `version`.

This matters because Strategy 1's whole stale-write story rests on `version`
being correct for every order mutation, including ones written by future code
nobody reviews. Making the database own it is what turns that from a code-review
habit into an invariant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import insert_order, insert_user

SCHEMA_SQL = Path(__file__).resolve().parents[1] / "sql" / "001_schema.sql"


async def test_update_bumps_updated_at_and_version(pg_pool):
    uid = await insert_user(pg_pool, "T", "t@example.com")
    oid = await insert_order(pg_pool, uid, "10.00")

    before = await pg_pool.fetchrow("SELECT updated_at, version FROM orders WHERE id=$1", oid)
    await pg_pool.execute("UPDATE orders SET status='SHIPPED' WHERE id=$1", oid)
    after = await pg_pool.fetchrow("SELECT updated_at, version FROM orders WHERE id=$1", oid)

    assert after["version"] == before["version"] + 1
    assert after["updated_at"] >= before["updated_at"]


async def test_version_is_monotonic_across_updates(pg_pool):
    """Three updates take version 1 to 4 — never a repeat, never a gap."""
    uid = await insert_user(pg_pool, "T", "t@example.com")
    oid = await insert_order(pg_pool, uid, "10.00")

    for expected in (2, 3, 4):
        await pg_pool.execute("UPDATE orders SET status='SHIPPED' WHERE id=$1", oid)
        assert (await pg_pool.fetchrow("SELECT version FROM orders WHERE id=$1", oid))[
            "version"
        ] == expected


async def test_insert_starts_at_version_one(pg_pool):
    """The trigger owns bumps, not the initial value — an INSERT is version 1."""
    uid = await insert_user(pg_pool, "T", "t@example.com")
    oid = await insert_order(pg_pool, uid, "10.00")
    assert (await pg_pool.fetchrow("SELECT version FROM orders WHERE id=$1", oid))["version"] == 1


async def test_trigger_owns_updated_at_even_if_a_caller_sets_it(pg_pool):
    """A caller cannot forge `updated_at`: the trigger overwrites it on every update.

    This is the property that makes a late-arriving sync visible rather than
    silently invisible.
    """
    uid = await insert_user(pg_pool, "T", "t@example.com")
    oid = await insert_order(pg_pool, uid, "10.00")
    stale = await pg_pool.fetchval("SELECT updated_at - interval '1 day' FROM orders WHERE id=$1", oid)

    await pg_pool.execute(
        "UPDATE orders SET status='SHIPPED', updated_at=$2 WHERE id=$1", oid, stale
    )

    got = await pg_pool.fetchval("SELECT updated_at FROM orders WHERE id=$1", oid)
    assert got > stale


async def test_schema_is_idempotent(pg_pool):
    """conftest applies the DDL on every session, so re-applying must be safe."""
    ddl = SCHEMA_SQL.read_text()
    async with pg_pool.acquire() as conn:
        await conn.execute(ddl)

    n = await pg_pool.fetchval(
        "SELECT count(*) FROM pg_trigger WHERE tgname='orders_touch_trg' AND NOT tgisinternal"
    )
    assert n == 1, "the trigger must be attached exactly once after re-application"

    # ...and it must still be firing, not silently dropped by the re-apply.
    uid = await insert_user(pg_pool, "T2", "t2@example.com")
    oid = await insert_order(pg_pool, uid, "1.00")
    await pg_pool.execute("UPDATE orders SET status='SHIPPED' WHERE id=$1", oid)
    assert (await pg_pool.fetchrow("SELECT version FROM orders WHERE id=$1", oid))["version"] == 2


@pytest.mark.parametrize(
    "table,expected_columns",
    [
        ("users", {"id", "name", "email", "created_at"}),
        ("orders", {"id", "user_id", "order_date", "status", "total_amount", "updated_at", "version"}),
        ("order_items", {"id", "order_id", "product_id", "title", "quantity", "unit_price"}),
        ("outbox", {"id", "aggregate_id", "event_type", "created_at", "processed_at", "attempts", "last_error"}),
    ],
)
async def test_tables_exist_with_expected_columns(pg_pool, table, expected_columns):
    actual = set(await pg_pool.fetchval(
        "SELECT array_agg(column_name) FROM information_schema.columns"
        " WHERE table_name=$1 AND table_schema='public'",
        table,
    ))
    assert actual == expected_columns


async def test_money_columns_are_numeric_not_float(pg_pool):
    """Money must never be float8 -- PostgreSQL has no exact decimal binary type."""
    rows = await pg_pool.fetch(
        "SELECT table_name, column_name, data_type, numeric_precision, numeric_scale"
        " FROM information_schema.columns"
        " WHERE table_schema='public' AND data_type='numeric'"
        " ORDER BY table_name, column_name"
    )
    by_table = {r["table_name"]: r for r in rows}
    assert set(by_table) == {"orders", "order_items"}
    for row in rows:
        assert (row["numeric_precision"], row["numeric_scale"]) == (12, 2), dict(row)


async def test_no_float_columns_in_the_schema(pg_pool):
    floats = await pg_pool.fetchval(
        "SELECT count(*) FROM information_schema.columns"
        " WHERE table_schema='public'"
        " AND data_type IN ('double precision', 'real', 'money')"
    )
    assert floats == 0, "floating-point columns would break money precision"


async def test_order_items_snapshots_are_immutable(pg_pool):
    """No UPDATE path may rewrite a captured title or price.

    The immutability is enforced by privilege rather than by convention: the
    application role cannot update snapshot columns at all.
    """
    uid = await insert_user(pg_pool, "T", "t@example.com")
    oid = await insert_order(pg_pool, uid, "10.00")
    await pg_pool.execute(
        "INSERT INTO order_items (order_id, product_id, title, quantity, unit_price)"
        " VALUES ($1, 'p1', 'Wireless Mouse', 2, '50.16')",
        oid,
    )

    with pytest.raises(Exception) as e:
        await pg_pool.execute(
            "UPDATE order_items SET title='Wireless Mouse Pro', unit_price='79.00' WHERE order_id=$1",
            oid,
        )
    assert "snapshot" in str(e.value).lower(), str(e.value)

    row = await pg_pool.fetchrow(
        "SELECT title, unit_price FROM order_items WHERE order_id=$1", oid
    )
    assert row["title"] == "Wireless Mouse"
    assert str(row["unit_price"]) == "50.16"


async def test_outbox_partial_index_exists(pg_pool):
    idx = await pg_pool.fetch(
        "SELECT indexdef FROM pg_indexes WHERE tablename='outbox' AND indexdef LIKE '%processed_at IS NULL%'"
    )
    assert len(idx) == 1, "the drain query scans unprocessed rows only"
