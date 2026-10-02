"""Outbox repository: the durability record for Strategy 1.

Every settlement targets the exact event `id` (compare-and-set), never a row
looked up by `aggregate_id`: one order can own several live events and
settling a sibling would silently lose it.
"""

from __future__ import annotations

from app.repositories import outbox_repo


async def test_enqueue_creates_pending_row(pg_pool):
    async with pg_pool.acquire() as conn:
        oid = await outbox_repo.enqueue(conn, 42, "ORDER_CREATED")
        row = await outbox_repo.get(conn, oid)
    assert row["aggregate_id"] == 42
    assert row["event_type"] == "ORDER_CREATED"
    assert row["processed_at"] is None
    assert row["attempts"] == 0


async def test_claim_returns_pending_in_order(pg_pool):
    async with pg_pool.acquire() as conn:
        a = await outbox_repo.enqueue(conn, 1, "ORDER_CREATED")
        b = await outbox_repo.enqueue(conn, 1, "ORDER_STATUS_CHANGED")
        rows = await outbox_repo.claim_unprocessed(conn, 10)
    assert [r["id"] for r in rows] == [a, b]


async def test_claim_skips_processed_and_terminal_rows(pg_pool):
    async with pg_pool.acquire() as conn:
        keep = await outbox_repo.enqueue(conn, 1, "ORDER_CREATED")
        done = await outbox_repo.enqueue(conn, 2, "ORDER_CREATED")
        await outbox_repo.mark_processed(conn, done)
        dying = await outbox_repo.enqueue(conn, 3, "ORDER_CREATED")
        for _ in range(outbox_repo.MAX_ATTEMPTS):
            await outbox_repo.mark_failed(conn, dying, "boom")
        rows = await outbox_repo.claim_unprocessed(conn, 10)
    assert [r["id"] for r in rows] == [keep]


async def test_mark_processed_is_idempotent_compare_and_set(pg_pool):
    async with pg_pool.acquire() as conn:
        oid = await outbox_repo.enqueue(conn, 1, "ORDER_CREATED")
        assert await outbox_repo.mark_processed(conn, oid) is True
        assert await outbox_repo.mark_processed(conn, oid) is False
        assert (await outbox_repo.get(conn, oid))["processed_at"] is not None


async def test_mark_failed_retries_then_goes_terminal(pg_pool):
    async with pg_pool.acquire() as conn:
        oid = await outbox_repo.enqueue(conn, 1, "ORDER_CREATED")
        await outbox_repo.mark_failed(conn, oid, "es down")
        row = await outbox_repo.get(conn, oid)
        assert row["processed_at"] is None
        assert row["attempts"] == 1
        assert row["last_error"] == "es down"
        for _ in range(outbox_repo.MAX_ATTEMPTS - 1):
            await outbox_repo.mark_failed(conn, oid, "still down")
        row = await outbox_repo.get(conn, oid)
        assert row["attempts"] == outbox_repo.MAX_ATTEMPTS
        assert row["processed_at"] is not None


async def test_mark_superseded_is_terminal_without_retry(pg_pool):
    async with pg_pool.acquire() as conn:
        oid = await outbox_repo.enqueue(conn, 1, "ORDER_CREATED")
        assert await outbox_repo.mark_superseded(conn, oid, "stale version") is True
        row = await outbox_repo.get(conn, oid)
        assert row["processed_at"] is not None
        assert row["attempts"] == 0
        assert "stale version" in (row["last_error"] or "")


async def test_settlement_touches_only_its_own_row(pg_pool):
    """Two live events for one order: settling one leaves the sibling pending."""
    async with pg_pool.acquire() as conn:
        created = await outbox_repo.enqueue(conn, 1, "ORDER_CREATED")
        changed = await outbox_repo.enqueue(conn, 1, "ORDER_STATUS_CHANGED")
        await outbox_repo.mark_processed(conn, created)
        sibling = await outbox_repo.get(conn, changed)
        assert sibling["processed_at"] is None
        assert sibling["attempts"] == 0


async def test_get_missing_returns_none(pg_pool):
    async with pg_pool.acquire() as conn:
        assert await outbox_repo.get(conn, 999999) is None
