"""Shared fixtures and helpers for the backend test suite.

Every fixture here talks to the **real** stores. There are no mocks and no
in-memory substitutes anywhere in this suite: the tests assert behaviour of the
actual PostgreSQL, MongoDB, Elasticsearch and RabbitMQ instances the application
uses in production.

The `pg_pool` fixture is written so that it degrades cleanly while the schema
does not exist yet: `_pg_pool` applies `sql/001_schema.sql` if the file is on
disk and otherwise proceeds against an empty database, and `pg_pool` skips with
an explanatory message when the `orders` table is absent. Task 2 lands the DDL
and these fixtures pick it up with no edit here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from bson.decimal128 import Decimal128
from elasticsearch import AsyncElasticsearch
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.settings import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = BACKEND_ROOT / "sql" / "001_schema.sql"

TRUNCATE_ORDER = [
    "order_items",
    "outbox",
    "orders",
    "users",
]


# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def _pg_pool() -> asyncpg.Pool:
    """Session pool. Applies the schema file when it exists on disk."""
    settings = get_settings()
    pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=10)
    if SCHEMA_SQL.exists():
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL.read_text())
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def pg_pool(_pg_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Empty schema, real connection. Skips until the schema file exists."""
    if not SCHEMA_SQL.exists():
        pytest.skip("schema not applied yet — run Task 2, or: psql -f sql/001_schema.sql")
    async with _pg_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT to_regclass('public.orders') IS NOT NULL")
    if not exists:
        pytest.skip("schema not applied yet — run Task 2, or: psql -f sql/001_schema.sql")
    await _pg_pool.execute(f"TRUNCATE {', '.join(TRUNCATE_ORDER)} RESTART IDENTITY CASCADE")
    return _pg_pool


async def insert_user(pool: asyncpg.Pool, name: str, email: str) -> int:
    """Insert a user, return its id."""
    return await pool.fetchval(
        "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id", name, email
    )


async def insert_order(
    pool: asyncpg.Pool,
    user_id: int,
    total: str,
    status: str = "PENDING",
    order_date: datetime | None = None,
    updated_at: datetime | None = None,
) -> int:
    """Insert an order, return its id.

    `updated_at` is overridable so a test can create a specific timestamp;
    otherwise it is left to the column default.
    """
    date = order_date or datetime.now(timezone.utc)
    return await pool.fetchval(
        "INSERT INTO orders (user_id, order_date, status, total_amount, updated_at)"
        " VALUES ($1, $2, $3, $4, COALESCE($5::timestamptz, now())) RETURNING id",
        user_id,
        date,
        status,
        Decimal(total),
        updated_at,
    )


async def insert_items(
    pool: asyncpg.Pool,
    order_id: int,
    items: list[tuple[str, str, int, str]],
) -> None:
    """Insert `order_items` snapshot rows: (product_id, title, quantity, unit_price)."""
    await pool.executemany(
        "INSERT INTO order_items (order_id, product_id, title, quantity, unit_price)"
        " VALUES ($1, $2, $3, $4, $5)",
        [(order_id, pid, title, qty, Decimal(price)) for pid, title, qty, price in items],
    )


async def seed_minimal(
    pool: asyncpg.Pool,
    n_orders: int = 3,
    items_per_order: int = 2,
) -> list[int]:
    """One user plus `n_orders` orders, each with `items_per_order` snapshot lines."""
    uid = await insert_user(pool, "Seed User", "seed@example.com")
    order_ids: list[int] = []
    for i in range(n_orders):
        total = sum(Decimal("10.00") * qty for qty in range(1, items_per_order + 1))
        oid = await insert_order(pool, uid, f"{total:.2f}", status="PENDING")
        await insert_items(
            pool,
            oid,
            [
                (
                    f"0000000000000000000000{i:02d}",
                    f"Product {i}",
                    qty,
                    "10.00",
                )
                for qty in range(1, items_per_order + 1)
            ],
        )
        order_ids.append(oid)
    return order_ids


# ---------------------------------------------------------------------------
# MongoDB (product catalog)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def _mongo_client() -> AsyncIOMotorClient:
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_dsn, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")
    yield client
    client.close()


@pytest_asyncio.fixture
async def mongo_db(_mongo_client: AsyncIOMotorClient):
    """Real MongoDB database with an empty `products` collection."""
    db = _mongo_client[get_settings().mongo_db_name]
    await db.products.drop()
    yield db
    await db.products.drop()


async def insert_product(
    db,
    title: str,
    price: str,
    active: bool = True,
    **extra: object,
) -> str:
    """Insert a product, return its id as a string.

    Takes a plain string price and does the `Decimal128` wrapping here, so no
    test other than the deliberate money-boundary test imports `bson`.
    """
    document: dict[str, object] = {
        "sku": f"SKU-{abs(hash(title)) % 10**8:08d}",
        "title": title,
        "description": f"{title} description",
        "price": Decimal128(str(Decimal(price))),
        "category": "peripherals",
        "tags": ["wireless"],
        "attributes": {"color": "black"},
        "variants": [{"sku": f"{title}-V1", "color": "black", "stock": 10}],
        "active": active,
        "updated_at": datetime.now(timezone.utc),
    }
    document.update(extra)
    result = await db.products.insert_one(document)
    return str(result.inserted_id)


# ---------------------------------------------------------------------------
# Elasticsearch (admin order search projection)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def _es_client() -> AsyncElasticsearch:
    es = AsyncElasticsearch(get_settings().es_url, request_timeout=30)
    await es.info()
    yield es
    await es.close()


@pytest_asyncio.fixture
async def es(_es_client: AsyncElasticsearch) -> AsyncElasticsearch:
    """Real Elasticsearch client with no `orders` index left behind.

    The index is not created here: Task 3's tests create it themselves via
    `ensure_orders_index()`, so the mapping is never asserted against a
    half-built fixture.
    """
    index = get_settings().es_orders_index
    if await _es_client.indices.exists(index=index):
        await _es_client.indices.delete(index=index)
    yield _es_client
    if await _es_client.indices.exists(index=index):
        await _es_client.indices.delete(index=index)


# ---------------------------------------------------------------------------
# HTTP client — defined in Task 8, once app.main exists
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(pg_pool, mongo_db):
    """httpx client bound to the FastAPI app (ASGI, no port needed).

    Depends on `pg_pool`/`mongo_db` so each test starts from empty stores.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
