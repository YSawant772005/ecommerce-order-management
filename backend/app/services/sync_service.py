"""The canonical projection, and the vocabulary for reporting on it.

`build_order_document()` is the only code in the system that produces an
Elasticsearch order document. It is a pure function of **committed PostgreSQL
rows**: the order, its customer, and the `order_items` snapshots. It never reads
MongoDB.

That is the whole reason a renamed or repriced product cannot rewrite history. An
order line is a record of what was sold at the moment it was sold; if the
projection consulted the live catalog it would show today's title and today's
price on a two-year-old order. `test_snapshots_win_over_the_live_catalog` is the
test that would fail if anyone "helpfully" added a catalog lookup here.

The connection is a parameter, not an internal lookup, so the caller controls the
transaction. After a status update commits, the caller passes *that* connection
(or a fresh one) and the document is guaranteed to reflect the same snapshot the
caller just read.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg
from elasticsearch import ApiError, ConflictError, ConnectionError, TransportError

from app.core.elasticsearch import get_es
from app.core.postgres import get_pool
from app.repositories import outbox_repo

#: Place vocabulary. The moment an event is written to the outbox the order is
#: "pending"; the projection has not run and nothing may claim otherwise.
PENDING = "PENDING"

#: Badge vocabulary. This is what `GET /api/sync/status/{order_id}` reports, and
#: it is deliberately disjoint from the placement vocabulary above. `QUEUED` is
#: never a badge and `IN_SYNC` is never a placement.
IN_SYNC = "IN_SYNC"
OUT_OF_SYNC = "OUT_OF_SYNC"
MISSING_IN_ES = "MISSING_IN_ES"
QUEUED = "QUEUED"


class OrderNotFound(Exception):
    """No such order in PostgreSQL. A projection of nothing is an error, not a doc."""


def _is_version_conflict(exc: ConflictError) -> bool:
    """True when ES rejected a stale external version.

    On this path the only 409 Elasticsearch raises is
    `version_conflict_engine_exception` (mapping errors are 400), so a 409
    unambiguously means a newer version already won.
    """
    return getattr(exc, "status_code", None) == 409


async def index_order(order_id: int, outbox_id: int | None = None) -> None:
    """Index one order. `outbox_id` names the exact event being settled.

    `None` means index-and-settle-nothing (reindex / manual path). A stale
    version is terminal (`mark_superseded`, never retried); an outage stays
    retryable (`mark_failed`, re-raised so the beat drain retries it).
    """
    from app.core.settings import get_settings

    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await build_order_document(conn, order_id)
    es = await get_es()
    try:
        await es.index(
            index=get_settings().es_orders_index,
            id=str(order_id),
            document=doc,
            version=doc["version"],
            version_type="external",
        )
    except ConflictError as exc:
        if not _is_version_conflict(exc):
            raise
        if outbox_id is not None:
            async with pool.acquire() as conn:
                await outbox_repo.mark_superseded(
                    conn,
                    outbox_id,
                    f"superseded: stale version {doc['version']} lost to a newer index write",
                )
        return
    except (ApiError, ConnectionError, TransportError) as exc:
        if outbox_id is not None:
            async with pool.acquire() as conn:
                await outbox_repo.mark_failed(conn, outbox_id, str(exc))
        raise
    if outbox_id is not None:
        async with pool.acquire() as conn:
            await outbox_repo.mark_processed(conn, outbox_id)


async def drain_outbox(limit: int = 100) -> dict[str, int]:
    """Re-dispatch every pending event. One row's failure never stops the rest."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await outbox_repo.claim_unprocessed(conn, limit)
        claimed = [(r["aggregate_id"], r["id"]) for r in rows]
    settled = 0
    for aggregate_id, event_id in claimed:
        try:
            await index_order(aggregate_id, event_id)
        except Exception:
            continue
        settled += 1
    return {"claimed": len(claimed), "settled": settled}


def _money(value: Decimal | int | float | str) -> str:
    """PostgreSQL `NUMERIC` -> the exact two-place string Elasticsearch stores.

    asyncpg hands `NUMERIC` back as `Decimal`, so this is a formatting step, not
    a conversion. It goes through `Money`'s rule so the JSON wire format and the
    indexed value can never disagree.
    """
    from app.models._money import to_money_str

    return to_money_str(Decimal(value))


def _iso(value: datetime) -> str:
    """`timestamptz` -> `"2026-07-10T12:00:00Z"`, the format the mapping expects.

    Elasticsearch's `date` type parses ISO-8601 with an offset, but emitting a
    single canonical `Z` form keeps documents diffable and matches the format
    shown in the spec.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def build_order_document(conn: asyncpg.Connection, order_id: int) -> dict[str, Any]:
    """Project one committed order into the Elasticsearch document shape.

    Three queries against PostgreSQL, in the caller's transaction. Money is
    carried as an exact two-place string; the ES mapping declares
    `scaled_float(100)`, so the string is parsed back to exact cents on index.
    """
    row = await conn.fetchrow(
        """
        SELECT o.id, o.user_id, o.order_date, o.status, o.total_amount,
               o.updated_at, o.version,
               u.name  AS customer_name,
               u.email AS customer_email
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.id = $1
        """,
        order_id,
    )
    if row is None:
        raise OrderNotFound(f"order {order_id} not found in PostgreSQL")

    item_rows = await conn.fetch(
        """
        SELECT product_id, title, quantity, unit_price
        FROM order_items
        WHERE order_id = $1
        ORDER BY id
        """,
        order_id,
    )

    return {
        "order_id": row["id"],
        "order_date": _iso(row["order_date"]),
        "status": row["status"],
        # The committed total, never a fresh sum of the lines. A corrected line
        # must not silently restate what the customer was charged.
        "total_amount": _money(row["total_amount"]),
        "updated_at": _iso(row["updated_at"]),
        "version": row["version"],
        "customer": {
            "id": row["user_id"],
            "name": row["customer_name"],
            "email": row["customer_email"],
        },
        "items": [
            {
                "product_id": item["product_id"],
                "title": item["title"],
                "quantity": item["quantity"],
                "unit_price": _money(item["unit_price"]),
            }
            for item in item_rows
        ],
    }
