"""Outbox durability record for Strategy 1.

Written **inside** the order transaction, so "PostgreSQL committed" and
"Elasticsearch will hear about it" are a single atomic fact. Every
settlement below targets the exact event `id` and is compare-and-set
(`WHERE id=$1 AND processed_at IS NULL`), so a redelivered worker is
idempotent and can never settle a sibling event for the same order.
"""

from __future__ import annotations

import asyncpg

#: Retries are bounded. After this many failures the row goes terminal so
#: `drain_outbox` stops re-dispatching it, and stays visible for repair.
MAX_ATTEMPTS = 5


async def enqueue(conn: asyncpg.Connection, aggregate_id: int, event_type: str) -> int:
    """Record the intent to index, inside the caller's transaction.

    Returns the event id so the post-commit dispatch names the exact row.
    """
    return await conn.fetchval(
        "INSERT INTO outbox (aggregate_id, event_type) VALUES ($1, $2) RETURNING id",
        aggregate_id,
        event_type,
    )


async def get(conn: asyncpg.Connection, outbox_id: int) -> asyncpg.Record | None:
    """One event row by its own id, or None."""
    return await conn.fetchrow("SELECT * FROM outbox WHERE id = $1", outbox_id)


async def claim_unprocessed(
    conn: asyncpg.Connection, limit: int
) -> list[asyncpg.Record]:
    """Oldest pending events, skipping locked, processed and terminal rows."""
    return await conn.fetch(
        """
        SELECT * FROM outbox
        WHERE processed_at IS NULL AND attempts < $1
        ORDER BY created_at, id
        LIMIT $2
        FOR UPDATE SKIP LOCKED
        """,
        MAX_ATTEMPTS,
        limit,
    )


async def mark_processed(conn: asyncpg.Connection, outbox_id: int) -> bool:
    """Settle exactly this event. Idempotent: a second call settles nothing."""
    row = await conn.fetchrow(
        "UPDATE outbox SET processed_at = now()"
        " WHERE id = $1 AND processed_at IS NULL RETURNING id",
        outbox_id,
    )
    return row is not None


async def mark_failed(conn: asyncpg.Connection, outbox_id: int, error: str) -> bool:
    """Record a retryable failure. Terminal once attempts reach MAX_ATTEMPTS."""
    row = await conn.fetchrow(
        """
        UPDATE outbox
        SET attempts = attempts + 1,
            last_error = $2,
            processed_at = CASE WHEN attempts + 1 >= $3 THEN now() ELSE processed_at END
        WHERE id = $1 AND processed_at IS NULL
        RETURNING id
        """,
        outbox_id,
        error,
        MAX_ATTEMPTS,
    )
    return row is not None


async def mark_superseded(conn: asyncpg.Connection, outbox_id: int, reason: str) -> bool:
    """Terminal without retry: a newer version already won, retrying is futile."""
    row = await conn.fetchrow(
        "UPDATE outbox SET processed_at = now(), last_error = $2"
        " WHERE id = $1 AND processed_at IS NULL RETURNING id",
        outbox_id,
        reason,
    )
    return row is not None
