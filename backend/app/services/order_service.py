"""Order placement and the guarded status change.

Both operations follow the same three-step shape, and the order of the steps is
the design rather than an implementation detail:

1. **validate first** — the catalog is read and rejected on before any PostgreSQL
   transaction opens, so a bad cart leaves no trace to clean up;
2. **one transaction** — `orders`, `order_items` and the `outbox` event commit
   together, or none of them do;
3. **dispatch after commit** — the queue is told only once the fact is durable,
   because a worker that starts before the commit would project an order that
   does not exist.

There is no polling branch and no `sync_state`. Strategy 1 is the only
synchronization path, so there is nothing to switch on.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from app.core.postgres import get_pool
from app.core.settings import get_settings
from app.models._money import CENTS, quantize
from app.models.order import OrderCreate, OrderOut
from app.repositories import orders_repo
from app.repositories.orders_repo import ORDER_CREATED, ORDER_STATUS_CHANGED

# Re-exported so a test can patch exactly what this module calls.
insert_order_items = orders_repo.insert_order_items
from app.repositories.products_repo import ProductsRepo


def dispatch_sync(order_id: int, outbox_id: int | None) -> None:
    """Hand the committed event to the queue. Replaced in tests; wired in Task 7.

    Called only after COMMIT. The pair is the message: `order_id` says what to
    index, `outbox_id` says which event row to settle. Dispatching `order_id`
    alone would leave the worker unable to mark the right row, and matching on
    `aggregate_id` could settle a sibling event.

    Slice note: `app.workers.tasks` lands in Phase 9. Until then a missing
    worker module is a best-effort skip, never a failed checkout.
    """
    try:
        from app.workers.tasks import index_order
    except ImportError:
        return

    index_order.delay(order_id, outbox_id)


async def _get_products_repo() -> ProductsRepo:
    from app.core.mongo import get_db

    return ProductsRepo(await get_db())


async def _resolve_lines(req: OrderCreate) -> list[tuple[str, str, int, Decimal]]:
    """Read the catalog and price the cart. Raises 409 before any PG write.

    One `$in` query for the whole cart, so checkout latency does not grow with
    cart size. Duplicate lines for one product are merged here rather than
    producing two `order_items` rows for a single product.
    """
    wanted: dict[str, int] = {}
    for item in req.items:
        wanted[item.product_id] = wanted.get(item.product_id, 0) + item.quantity

    products = await (await _get_products_repo()).get_many_by_ids(list(wanted))

    missing = [pid for pid in wanted if pid not in products]
    inactive = [products[pid].title for pid in wanted if pid in products and not products[pid].active]
    if missing or inactive:
        detail = []
        if missing:
            detail.append(f"not found: {', '.join(missing)}")
        if inactive:
            detail.append(f"not available: {', '.join(inactive)}")
        raise HTTPException(status_code=409, detail="; ".join(detail))

    return [
        (pid, products[pid].title, quantity, products[pid].price)
        for pid, quantity in wanted.items()
    ]


async def place_order(req: OrderCreate) -> OrderOut:
    """Validate against the catalog, then write the order, items and event atomically."""
    lines = await _resolve_lines(req)
    total = quantize(sum((price * qty for _, _, qty, price in lines), Decimal("0")))

    pool = await get_pool()
    async with pool.acquire() as conn:
        if not await orders_repo.user_exists(conn, req.user_id):
            raise HTTPException(status_code=404, detail=f"user {req.user_id} not found")

        async with conn.transaction():
            order_id = await orders_repo.insert_order(conn, req.user_id, total)
            await orders_repo.insert_order_items(
                conn, order_id, [(pid, title, qty, price) for pid, title, qty, price in lines]
            )
            outbox_id = await orders_repo.insert_outbox_event(conn, order_id, ORDER_CREATED)
        # ---- committed ----

    # After COMMIT, never before: a worker that started earlier would project an
    # order row that does not exist yet.
    dispatch_sync(order_id, outbox_id)

    return OrderOut(
        order_id=order_id,
        total_amount=total,
        status="PENDING",
        sync_status=get_settings().order_sync_placement_status,
    )


async def update_status(order_id: int, status: str, expected_version: int) -> OrderOut:
    """Change status under an optimistic lock, queue a re-index, and report the new row.

    `expected_version` is the version the caller believes is current. If the
    database holds a higher one, this is a stale write: it is rejected with 409
    rather than silently overwriting a concurrent change.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            exists, updated = await orders_repo.update_status_guarded(
                conn, order_id, status, expected_version
            )
            if not exists:
                raise HTTPException(status_code=404, detail=f"order {order_id} not found")
            if updated == 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"order {order_id} has moved on: expected_version={expected_version} "
                        "is stale. Re-read the order and retry."
                    ),
                )
            # Read the row back so the queued event and the caller both report the
            # version that actually committed, not the one they asked for.
            row = await orders_repo.fetch_order_row(conn, order_id)
            outbox_id = await orders_repo.insert_outbox_event(
                conn, order_id, ORDER_STATUS_CHANGED
            )
        # ---- committed ----

    dispatch_sync(order_id, outbox_id)

    return OrderOut(
        order_id=row["id"],
        total_amount=row["total_amount"],
        status=row["status"],
        sync_status=get_settings().order_sync_placement_status,
    )
