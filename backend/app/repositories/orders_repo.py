"""PostgreSQL access for orders, order items and the outbox.

Every function here takes an `asyncpg.Connection` rather than reaching for a
pool. The caller owns the transaction, which is what lets `order_service` put
`orders`, `order_items` and the `outbox` event into a single atomic unit.
"""

from __future__ import annotations

import asyncpg

ORDER_CREATED = "ORDER_CREATED"
ORDER_STATUS_CHANGED = "ORDER_STATUS_CHANGED"


async def insert_order(
    conn: asyncpg.Connection,
    user_id: int,
    total_amount,
    status: str = "PENDING",
) -> int:
    """Insert one order and return its id. `version` starts at 1."""
    return await conn.fetchval(
        "INSERT INTO orders (user_id, status, total_amount) VALUES ($1, $2, $3) RETURNING id",
        user_id,
        status,
        total_amount,
    )


async def insert_order_items(
    conn: asyncpg.Connection,
    order_id: int,
    items: list[tuple[str, str, int, object]],
) -> None:
    """Insert the checkout snapshots: (product_id, title, quantity, unit_price)."""
    await conn.executemany(
        "INSERT INTO order_items (order_id, product_id, title, quantity, unit_price)"
        " VALUES ($1, $2, $3, $4, $5)",
        [(order_id, pid, title, qty, price) for pid, title, qty, price in items],
    )


async def insert_outbox_event(
    conn: asyncpg.Connection,
    aggregate_id: int,
    event_type: str,
) -> int:
    """Record the intent to index, inside the caller's transaction.

    Returning the id is what lets the post-commit dispatch name the exact event
    row, so the worker settles that row and no other. Single implementation:
    `outbox_repo.enqueue`.
    """
    from app.repositories import outbox_repo

    return await outbox_repo.enqueue(conn, aggregate_id, event_type)


async def update_status_guarded(
    conn: asyncpg.Connection,
    order_id: int,
    status: str,
    expected_version: int,
) -> tuple[bool, int]:
    """Update status only if the caller is not stale.

    Returns `(row_exists, updated)`. `updated == 0` with `row_exists` means the
    row is there but the caller's `expected_version` is behind — the optimistic
    lock losing, which the service turns into a 409. The `orders_touch` trigger
    has already bumped `version` and `updated_at` for the row that did land.
    """
    exists = await conn.fetchval("SELECT 1 FROM orders WHERE id = $1", order_id)
    if not exists:
        return False, 0
    updated = await conn.execute(
        "UPDATE orders SET status = $3 WHERE id = $1 AND version = $2",
        order_id,
        expected_version,
        status,
    )
    return True, int(updated.rsplit(" ", 1)[1])


async def fetch_order_row(conn: asyncpg.Connection, order_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT o.id, o.user_id, o.order_date, o.status, o.total_amount,
               o.updated_at, o.version,
               u.name AS customer_name, u.email AS customer_email
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.id = $1
        """,
        order_id,
    )


async def fetch_order_items(conn: asyncpg.Connection, order_id: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT product_id, title, quantity, unit_price FROM order_items"
        " WHERE order_id = $1 ORDER BY id",
        order_id,
    )


async def user_exists(conn: asyncpg.Connection, user_id: int) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM users WHERE id = $1", user_id))


async def list_order_ids(conn: asyncpg.Connection) -> list[int]:
    """Every order id, oldest first. The reindex path walks this list."""
    rows = await conn.fetch("SELECT id FROM orders ORDER BY id")
    return [r["id"] for r in rows]
