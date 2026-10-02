# E-Commerce Order Management & Search Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a proof-of-concept e-commerce system: a Vue 3 SPA over a FastAPI backend that uses PostgreSQL for orders, MongoDB for the catalog, and Elasticsearch for admin search, with two independently runnable order-sync strategies (A dual-write, B polling) and a deterministic seed.

**Architecture:** Three stores, each accessed through exactly one repository module, with a structural data-source rule per screen. Orders are written in a real PostgreSQL transaction; the Elasticsearch projection is produced by exactly one function `build_order_document` called from every sync path, so the index shape cannot drift. Strategy A writes an outbox row inside the order transaction and dispatches via RabbitMQ/Celery; Strategy B writes no outbox and is discovered by a periodic watermark poller. `ORDER_SYNC_STRATEGY` switches between them at runtime.

**Tech Stack:** Python 3.11 · FastAPI · asyncpg (no ORM) · motor (MongoDB) · elasticsearch-py AsyncElasticsearch · Celery + RabbitMQ (broker) · PostgreSQL 16 · MongoDB 7 · Elasticsearch 8 · pytest + pytest-asyncio · Faker. Frontend: Vue 3 + Vite + `<script setup>` · Vue Router 4 · Pinia · `Intl.NumberFormat`. Orchestration: Docker Compose (4 store services; apps on host).

**Spec:** `docs/superpowers/specs/2026-09-30-ecommerce-order-management-design.md` — the plan argues from the spec, so the spec travels with it; executors read both.

## Global Constraints

- No ORM. Use `asyncpg` directly, so the transaction boundary is visible as `async with pool.acquire() as c: async with c.transaction():` (spec §6).
- **Money is `Decimal` in Python, and each store/transport gets exactly one representation. Never let a float touch money.** The four boundaries (spec §5, §8, §9, §10):
  | Boundary | Representation | Rule |
  |---|---|---|
  | Python / Pydantic | `Decimal`, quantized to 2 places | `field_serializer` emits `str`; all arithmetic `Decimal`, never `float` |
  | PostgreSQL | `NUMERIC(12,2)` | `asyncpg` maps `NUMERIC` ⇄ `Decimal` natively; never cast to `float` |
  | MongoDB | BSON `Decimal128` | `Decimal128(str(decimal))` on write, `Decimal128.to_decimal()` on read; BSON has no `Decimal`, so `Decimal128` is not optional |
  | Elasticsearch | `scaled_float(100)` | stored as a double scaled by 100; money never travels to ES as a string or a raw `Decimal` |
  | HTTP JSON | **string** (`"50.16"`) | the only representation clients see, produced by the Pydantic serializer |
  - This is why the `orders` doc is assembled in Python from `Decimal` values: Pydantic `Decimal` → `Decimal128` for Mongo, and `float(Decimal)*100`-equivalent scaling for ES via the client's codec. Conversions are asserted at the boundary in Tasks 3, 6, 8, and 12, not assumed.
- Order-item snapshots (`title`, `unit_price`) are immutable; no `UPDATE` path touches them (spec §15).
- Elasticsearch `items` is `object`, NOT `nested`; `.prefix` n-gram subfields on `customer.name` and `items.title`; index name `orders`; 1 shard, 0 replicas, `refresh_index 1s`, `xpack.security.enabled=false` (spec §9).
- Outbox is written **only** under Strategy A; `sync_state` is read **only** under Strategy B. The `orders_touch` trigger owns `updated_at` and `version` (spec §7, §12, §13).
- Strategy switch is one env var: `ORDER_SYNC_STRATEGY=dual_write|polling`. Everything else is identical (spec §3).
- Celery has **no result backend** (no Redis) and uses `task_acks_late=True`, `task_ignore_result=True` (spec §12, §16).
- ES writes use `id=order_id` (idempotent) and `version=pg_version` with `version_type="external"` (spec §12).
- Data-source rule: Screen 3 (admin search) service imports **no** PostgreSQL or MongoDB repository — enforced by test (spec §4, §20).
- Docker: 4 services — `postgres:16`, `mongo:7`, `elasticsearch:8`, `rabbitmq:3-management`. Stores in Docker; FastAPI, Vite, Celery on host. ES needs `discovery.type=single-node`, `xpack.security.enabled=false`, `ES_JAVA_OPTS=-Xms512m -Xmx512m`, `memlock` ulimit (spec §19).
- Seed: 8 users, 25 products (24 active + 1 inactive), 40 orders, ~85 items, all programmatically generated (spec §18). Anchor `SEED_ANCHOR_DATE = 2026-09-30T00:00:00Z`.
- Snapshot-mismatch fixture: after seeding, the MongoDB product `Wireless Mouse` becomes `Wireless Mouse Pro` at 79.00 (MongoDB only); historical orders keep `Wireless Mouse` @ 50.16 (spec §18.5).
- No jQuery, no server-side HTML templating; FastAPI returns JSON only (spec §1.2).
- Test stack is **backend-only** pytest (spec §1.1). The frontend has no test task.

## Review Focus

Five failure modes the spec implies that are easiest to get wrong. Each gets a test in the owning task:

1. **Catalog edit leaking into history** — editing a product's title/price in MongoDB must not change any `order_items` row or ES document. (Task 11 / `test_snapshot.py`)
2. **Stale-write clobbering** — a slow worker indexing an older version must not overwrite a newer ES doc; PG status updates guard on `version`. (Task 13 / `test_sync_dual_write.py`)
3. **Polling NULL watermark and ties** — first poll with `last_polled_at IS NULL` must return all orders (not none), and two orders with identical `updated_at` must not be dropped by the watermark. (Task 13 / `test_sync_polling.py`)
4. **Money precision** — `total_amount` equals `Σ(quantity × unit_price)` to the cent, and ES-sourced money serializes as a string identical to PG-sourced money. (Tasks 5 and 12)
5. **Data-source isolation** — Screen 3 must not import PG/Mongo repos. (Task 5 / `test_data_source_isolation.py`)

---

## File Structure

Everything the plan creates, and who owns it:

```
backend/
  requirements.txt                 minimum compatible deps (>= floors, elasticsearch <9); asyncpg, motor, elasticsearch, celery, faker
  sql/001_schema.sql               full DDL: users, orders, order_items, outbox, sync_state, trigger, indexes
  app/
    main.py                         FastAPI factory, routers, CORS, lifespan (open clients, ensure ES index)
    core/settings.py                pydantic-settings; all env config incl. ORDER_SYNC_STRATEGY
    core/postgres.py                asyncpg pool factory + get_pool
    core/mongo.py                   motor client factory + get_client
    core/elasticsearch.py           AsyncElasticsearch client factory + ensure_orders_index
    models/product.py               Pydantic Product; price is a Python Decimal. BSON Decimal128 conversion lives in products_repo, not in the model.
    models/order.py                 Pydantic OrderCreate/OrderOut/OrderItemOut (money as str)
    models/search.py                Pydantic SearchRequest/SearchResponse (money as str)
    models/user.py                  Pydantic User
    repositories/users_repo.py      PG only: list_users
    repositories/products_repo.py   Mongo only: list/get/create/update products
    repositories/orders_repo.py     PG only: insert/get order+items, guarded status update, list_updated_since
    repositories/outbox_repo.py     PG only: enqueue, claim_unprocessed, mark_processed, mark_failed, mark_superseded, get; MAX_ATTEMPTS=5
    repositories/sync_state_repo.py PG only: get_watermark, set_watermark, reset
    repositories/search_repo.py     ES only: search_orders (filters, facets, revenue agg)
    services/order_service.py       THE transaction; place_order; strategy branch (only branch site)
    services/search_service.py      Screen 3 orchestration; imports search_repo ONLY
    services/sync_service.py        build_order_document (the single PG->ES projection) + ES index/verify
    services/outbox_service.py      outbox drain logic used by the beat task
    workers/celery_app.py           Celery app; broker from env; beat schedule; task_acks_late
    workers/tasks.py                index_order(order_id, outbox_id)/drain_outbox (A); poll_orders/poll_once (B)
    search/orders_mapping.json      the ES index mapping + settings
  scripts/
    seed.py                         deterministic generator + 18.6 verifier; --reset/--seed/--anchor-date/--verify-only
    reindex_orders.py               delete + create index + bulk index all orders via build_order_document
  tests/
    conftest.py                     async fixtures: pg pool, mongo client, es client, celery eager mode
    test_orders_touch_trigger.py
    test_order_placement.py
    test_snapshot.py
    test_sync_dual_write.py
    test_sync_polling.py
    test_search.py
    test_data_source_isolation.py
    test_seed_determinism.py
frontend/
  package.json, vite.config.js, index.html
  src/main.js, App.vue
  src/router.js
  src/views/{StorefrontView,CheckoutView,AdminSearchView,OrderDetailView,CatalogAdminView}.vue
  src/components/{ProductCard,ProductFilters,CartSummary,OrderStatusSelect,SyncBadge,FacetSidebar,KpiCards,OrderResultsTable,ProductForm}.vue
  src/stores/{cart,session,catalog,orders,search}.js
  src/api/{products,orders,search,users}.js
  src/utils/money.js
docker-compose.yml                   4 store services, healthchecks, volumes, ES env/ulimits
.env.example                        no real secrets
Makefile                            restart, reset-watermark (dev/demo convenience)
README.md                           boot->migrate->seed->run->5 screens->both strategies
NOTES.md                            5 learning milestones + A-queued vs A-inline
```

---

## Task 1: Project skeleton, settings, and Docker stores

**Files:**
- Create: `backend/requirements.txt`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/settings.py`, `docker-compose.yml`, `.env.example`, `backend/tests/conftest.py`
- Test: `backend/tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` singleton via `get_settings()` with fields: `order_sync_strategy: Literal["dual_write","polling"]`, `pg_dsn`, `mongo_dsn`, `es_url`, `rabbitmq_url`, `cors_origins: list[str]`, `seed_anchor_date: str`. Later tasks import `get_settings()`. Also brings up the four Docker stores that every other task's tests need.
- Produces `backend/tests/conftest.py` fixtures and helpers used by **every later task's tests** — the test-writing steps below assume these exist:
  - Fixtures: `pg_pool` (asyncpg pool, schema applied, tables truncated between tests), `mongo_db` (clean `products` collection), `es` (AsyncElasticsearch, `orders` index deleted+recreated), `client` (httpx `AsyncClient` bound to the FastAPI app, defined in Task 8 — until then, tests use the service functions directly).
  - Helpers: `insert_user(pool, name, email) -> int`, `insert_order(pool, user_id, total) -> int`, `insert_product(db, title, price, active=True) -> str` (returns the product id as a string), `seed_minimal(pool, n_orders)`.
  - `conftest.py` sets `asyncio_mode = auto` via a `pytest.ini`/`pyproject` section so async tests need no decorator.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings.py
from app.core.settings import get_settings, Settings

def test_default_strategy_is_dual_write():
    s = Settings(_env_file=None)
    assert s.order_sync_strategy == "dual_write"

def test_strategy_is_overridable(monkeypatch):
    monkeypatch.setenv("ORDER_SYNC_STRATEGY", "polling")
    assert get_settings().order_sync_strategy == "polling"

def test_seed_anchor_date_default():
    assert get_settings().seed_anchor_date == "2026-09-30T00:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Create `requirements.txt`, `docker-compose.yml`, `.env.example`**

`requirements.txt` lists **minimum compatible dependencies**, not exact pins — the constraint style is a floor (`>=`), with one deliberate ceiling:

```
fastapi>=0.115
uvicorn[standard]>=0.30
asyncpg>=0.29
motor>=3.5
pymongo>=4.8
elasticsearch[async]>=8,<9
celery>=5.4
pydantic>=2.7
pydantic-settings>=2.4
python-dotenv>=1.0
faker>=30.0
pytest>=8.0
pytest-asyncio>=0.24
```

The `<9` on `elasticsearch` is intentional and load-bearing, not decoration: the plan uses the 8.x async client API (`AsyncElasticsearch`, `version_type="external"`, `indices.create`), and a 9.x upgrade is a breaking change that must be a deliberate decision rather than an accident of a fresh install. The `pydantic>=2` floor is likewise load-bearing — the models use v2 `field_serializer` and `ConfigDict`.

There is no lockfile in this POC, so builds are not bit-reproducible; if reproducibility is wanted later, generate one with `pip freeze > requirements.lock.txt` and install from that. The floor style is what the spec's dependency table specifies, so the plan matches it rather than over-claiming precision.

`docker-compose.yml`: four services `postgres:16`, `mongo:7`, `elasticsearch:8`, `rabbitmq:3-management`; named volumes for pg and mongo; healthchecks on each; `depends_on: service_healthy`. ES env: `discovery.type=single-node`, `xpack.security.enabled=false`, `ES_JAVA_OPTS=-Xms512m -Xmx512m`; `ulimits: memlock: {soft: -1, hard: -1}`. Ports 5432, 27017, 9200, 5672, 15672.

`.env.example`: the connection strings and `ORDER_SYNC_STRATEGY=dual_write`, no real secrets.

- [ ] **Step 4: Implement `Settings` in `backend/app/core/settings.py`**

`class Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`; the fields above with defaults; `get_settings() -> Settings` using `functools.lru_cache`.

- [ ] **Step 5: Write `backend/tests/conftest.py` with the shared fixtures and helpers**

Create the fixtures and helpers named in this task's Interfaces block. Add `[tool.pytest.ini_options] asyncio_mode = "auto"` to `backend/pyproject.toml` (or a `pytest.ini`) so async tests run without decorators.

**The `pg_pool` fixture must not assume the schema exists yet.** `backend/sql/001_schema.sql` is created in Task 2, so at this point the file does not exist. Apply this rule, which is the real fix and not a workaround:

- A session-scoped `_pg_pool` fixture creates the pool and, **if `sql/001_schema.sql` exists on disk, applies it**. If the file is absent it proceeds with an empty database rather than erroring.
- `pg_pool` (function-scoped) depends on `_pg_pool`, checks whether the `orders` table exists, and **skips with a clear message** if it does not: `pytest.skip("schema not applied yet — run Task 2, or: psql -f sql/001_schema.sql")`.
- Every test needing PostgreSQL requests `pg_pool`, so it skips cleanly rather than erroring before Task 2 lands.
- Task 2 then writes `001_schema.sql` and the same fixtures pick it up with **no edit to `conftest.py`**. Re-applying must be safe, so Task 2's DDL uses `CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE FUNCTION`, and `DROP TRIGGER IF EXISTS` before `CREATE TRIGGER`.

`mongo_db` drops the `products` collection between tests; `es` deletes and recreates the `orders` index between tests. Neither depends on the schema.

- [ ] **Step 6: Verify the skip path works before Task 2 exists**

Run: `cd backend && python -m pytest tests/test_orders_touch_trigger.py -v`
Expected: **SKIPPED** with the "schema not applied yet" message — not an error.

- [ ] **Step 7: Bring up stores and run tests**

Run: `docker compose up -d && docker compose ps`
Expected: all four services `healthy`.

Run: `cd backend && python -m pytest tests/test_settings.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.txt backend/app/__init__.py backend/app/core/ docker-compose.yml .env.example backend/tests/ backend/pyproject.toml
git commit -m "chore: project skeleton, settings, and four store containers"
```

---

## Task 2: PostgreSQL schema and the `orders_touch` trigger

**Files:**
- Create: `backend/sql/001_schema.sql`, `backend/tests/test_orders_touch_trigger.py`
- Create: `backend/app/core/postgres.py`

**Interfaces:**
- Consumes: `get_settings().pg_dsn`
- Produces: `get_pool() -> asyncpg.Pool`; schema applied by `backend/sql/001_schema.sql`. Tables `users`, `orders`, `order_items`, `outbox`, `sync_state`; trigger `orders_touch_trg`; index `orders(updated_at, id)`; partial index `outbox(created_at) WHERE processed_at IS NULL`.
- Unblocks Task 1: once this file exists, the `pg_pool` fixture in `conftest.py` applies it automatically. **This task must not require any edit to `conftest.py`** — if it does, the Task 1 skip rule was implemented wrong.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_orders_touch_trigger.py
# (this file may not exist yet — Task 1 skips it cleanly. Create it now.)

async def test_update_bumps_updated_at_and_version(pg_pool):
    uid = await insert_user(pg_pool, "T", "t@example.com")
    oid = await insert_order(pg_pool, uid, "10.00")
    before = await pg_pool.fetchrow("SELECT updated_at, version FROM orders WHERE id=$1", oid)
    await pg_pool.execute("UPDATE orders SET status='SHIPPED' WHERE id=$1", oid)
    after = await pg_pool.fetchrow("SELECT updated_at, version FROM orders WHERE id=$1", oid)
    assert after["version"] == before["version"] + 1
    assert after["updated_at"] >= before["updated_at"]

async def test_version_is_monotonic_across_updates(pg_pool):
    # 3 updates -> version 4
    ...

async def test_schema_is_idempotent(pg_pool):
    # Re-applying the DDL must not raise, since conftest applies it every session.
    import pathlib
    ddl = pathlib.Path("sql/001_schema.sql").read_text()
    for stmt in [s for s in ddl.split(";") if s.strip()]:
        await pg_pool.execute(stmt)
    # The trigger must still be attached exactly once after re-application.
    n = await pg_pool.fetchval(
        "SELECT count(*) FROM pg_trigger WHERE tgname='orders_touch_trg' AND NOT tgisinternal")
    assert n == 1
    # ...and still firing, not silently dropped by the re-apply.
    uid = await insert_user(pg_pool, "T2", "t2@example.com")
    oid = await insert_order(pg_pool, uid, "1.00")
    await pg_pool.execute("UPDATE orders SET status='SHIPPED' WHERE id=$1", oid)
    assert (await pg_pool.fetchrow("SELECT version FROM orders WHERE id=$1", oid))["version"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_orders_touch_trigger.py -v`
Expected: FAIL with a real error (`relation "orders" does not exist`) — the Task 1 skip no longer applies because the schema file now exists, so the fixture applies it and the test proceeds to the missing-trigger behavior.

- [ ] **Step 3: Write `backend/sql/001_schema.sql`**

Verbatim the DDL from spec §7: `users`, `orders` (with `version INTEGER NOT NULL DEFAULT 1`), `order_items` (snapshot `title`/`unit_price`), `outbox`, `sync_state` (nullable `last_polled_at`), `orders_touch()` plpgsql function + `BEFORE UPDATE` trigger, and both indexes.

**Write it idempotently**, because `conftest.py` may apply it on every session: `CREATE TABLE IF NOT EXISTS` for all five tables, `CREATE INDEX IF NOT EXISTS` for both indexes, `CREATE OR REPLACE FUNCTION orders_touch()`, and `DROP TRIGGER IF EXISTS orders_touch_trg ON orders;` immediately before `CREATE TRIGGER orders_touch_trg ...`. Also wrap the function body in `LANGUAGE plpgsql` as in the spec.

- [ ] **Step 4: Implement `backend/app/core/postgres.py`**

`get_pool() -> asyncpg.Pool` creating an `asyncpg.create_pool(dsn=..., min_size=1, max_size=10)` singleton.

- [ ] **Step 5: Verify the Task 1 skip now resolves to a pass, and that re-applying is safe**

Run: `cd backend && psql "$PG_DSN" -f sql/001_schema.sql && python -m pytest tests/test_orders_touch_trigger.py -v`
Expected: PASS (all three tests), and re-running the same `psql` command a second time exits 0.

Run: `cd backend && python -m pytest tests/test_settings.py tests/test_orders_touch_trigger.py -v`
Expected: settings pass and the trigger tests pass in the same session — confirming the Task 1 → Task 2 hand-off needs no `conftest.py` edit.

- [ ] **Step 6: Commit**

```bash
git add backend/sql/001_schema.sql backend/app/core/postgres.py backend/tests/
git commit -m "feat: postgres schema with orders_touch trigger owning updated_at and version"
```

---

## Task 3: MongoDB and Elasticsearch clients + the orders index

**Files:**
- Create: `backend/app/core/mongo.py`, `backend/app/core/elasticsearch.py`, `backend/app/search/orders_mapping.json`, `backend/tests/test_clients.py`

**Interfaces:**
- Consumes: `get_settings().mongo_dsn`, `get_settings().es_url`
- Produces: `get_mongo() -> AsyncIOMotorClient`, `get_db() -> AsyncIOMotorDatabase`; `get_es() -> AsyncElasticsearch`, `ensure_orders_index() -> None`. Mapping per spec §9: `order_id` long, `order_date` date, `status` keyword, `total_amount` scaled_float(100), `updated_at` date, `version` integer, `customer.{id,long,name:text+.keyword+.prefix,email:keyword}`, `items` **object** with `product_id` keyword, `title` text+.keyword+.prefix, `quantity` integer, `unit_price` scaled_float(100). Settings: 1 shard, 0 replicas, `refresh_interval 1s`, custom `autocomplete_index` analyzer = `standard` tokenizer + `edge_ngram` (2–15).

- [ ] **Step 1: Write the failing test**

```python
async def test_ensure_orders_index_creates_index_with_scaling(es):
    await ensure_orders_index()
    mapping = (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]
    assert mapping["total_amount"]["type"] == "scaled_float"
    assert mapping["total_amount"]["scaling_factor"] == 100
    assert mapping["items"]["unit_price"]["scaling_factor"] == 100
    assert mapping["status"]["type"] == "keyword"

# spec §9: items MUST be `object`, never `nested`. Assert the discriminator
# explicitly -- both object and nested expose a "properties" key, so checking
# for its presence proves nothing.
async def test_items_is_object_not_nested(es):
    await ensure_orders_index()
    mapping = (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]
    assert mapping["items"]["type"] == "object"
    assert "nested" not in mapping["items"]

async def test_prefix_subfields_present(es):
    await ensure_orders_index()
    m = (await es.indices.get_mapping(index="orders"))["orders"]["mappings"]["properties"]
    assert {"prefix"} <= set(m["customer"]["name"]["fields"])
    assert {"prefix"} <= set(m["items"]["title"]["fields"])

# Money boundary: MongoDB stores BSON Decimal128, never a float or a string.
async def test_product_price_roundtrips_as_decimal128(mongo_db):
    from bson.decimal128 import Decimal128
    await mongo_db.products.insert_one({"title": "Mouse", "price": Decimal128("50.16")})
    got = await mongo_db.products.find_one({"title": "Mouse"})
    assert isinstance(got["price"], Decimal128)
    assert got["price"].to_decimal() == Decimal("50.16")

# Money boundary: ES scaled_float(100) roundtrips a 2dp Decimal without
# float drift for the extreme values the seed produces.
@pytest.mark.parametrize("raw", ["0.01", "19.99", "1234.56", "99999999.99"])
async def test_es_scaled_float_preserves_cents(es, raw):
    await ensure_orders_index()
    await es.index(index="orders", id="1", document={"total_amount": float(Decimal(raw)),
                                                     "version": 1, "order_id": 1})
    await es.indices.refresh(index="orders")
    src = (await es.search(index="orders", size=1))["hits"]["hits"][0]["_source"]
    assert Decimal(str(src["total_amount"])).quantize(Decimal("0.01")) == Decimal(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_clients.py -v`
Expected: FAIL — `ModuleNotFoundError` for `app.core.elasticsearch`.

- [ ] **Step 3: Write `orders_mapping.json` and the two client modules**

`orders_mapping.json`: `{"settings": {...}, "mappings": {"properties": {...}}}` exactly per spec §9. `elasticsearch.py`: `get_es()` singleton + `ensure_orders_index()` that creates `orders` if absent with that mapping. `mongo.py`: `get_mongo()`/`get_db()` singletons.

- [ ] **Step 4: Run test**

Run: `cd backend && python -m pytest tests/test_clients.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/mongo.py backend/app/core/elasticsearch.py backend/app/search/orders_mapping.json backend/tests/test_clients.py
git commit -m "feat: mongo and es clients; orders index with object items and ngram prefix subfields"
```

---

## Task 4: Pydantic models with string money

**Files:**
- Create: `backend/app/models/{__init__,product,order,search,user}.py`, `backend/tests/test_models_money.py`

**Interfaces:**
- Produces: `Product` (price `Decimal`), `OrderCreate(user_id:int, items:list[OrderItemIn{product_id:str,quantity:int}])`, `OrderOut(order_id:int,total_amount:str,status:str,sync_status:str)`, `OrderItemOut(product_id,title,quantity,unit_price:str)`, `SearchRequest(q:str|None,statuses,date_from,date_to,price_min,price_max,page,size)`, `SearchResponse(total:int,hits:list[SearchHit],revenue:str,status_facets:dict)`, `User(id,name,email)`. `OrderCreate` MUST NOT accept a price or title from the client (spec §11).

- [ ] **Step 1: Write the failing test**

```python
def test_money_serializes_as_string():
    o = OrderOut(order_id=1, total_amount=Decimal("150.50"), status="PENDING", sync_status="QUEUED")
    assert o.model_dump(mode="json")["total_amount"] == "150.50"

def test_order_create_rejects_client_price():
    with pytest.raises(ValidationError):
        OrderCreate(user_id=1, items=[{"product_id":"x","quantity":1,"unit_price":"0.01"}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models_money.py -v`
Expected: FAIL — models module missing.

- [ ] **Step 3: Implement models**

Use Pydantic v2. For money fields annotate with a serializer that emits `str` quantized to 2dp (e.g. `field_serializer` returning `format(v.quantize(Decimal('0.01')), 'f')`). `OrderItemIn` has exactly `product_id` and `quantity`, and `model_config = ConfigDict(extra="forbid")` so a client-sent price is rejected.

**`Product.price` is a plain Python `Decimal` — do not annotate it `Decimal128` and do not import `bson` in any model module.** `Decimal128` is a BSON wire type, not a Pydantic type; the Pydantic model must stay storage-agnostic so the same model serves the HTTP layer and the Mongo layer. The conversion is the repository's job, and Task 5 implements it:

- **Out:** `products_repo` builds `{"price": Decimal128(str(decimal))}` before inserting/updating.
- **In:** `products_repo` converts on read — `Decimal128` back to `Decimal`, then the `Product` model validates it.

This keeps the money boundary table honest: the model is on the Python/Decimal row, the repository is the only place BSON types appear. `insert_product(mongo_db, ...)` in `conftest.py` accepts a plain string price and does the `Decimal128` wrapping itself, so no test needs to import `bson` either.

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/ backend/tests/test_models_money.py
git commit -m "feat: pydantic models; money serialized as string, client price forbidden"
```

---

## Task 5: Repositories (per-store access) + data-source isolation test

**Files:**
- Create: `backend/app/repositories/{__init__,users_repo,products_repo,orders_repo,outbox_repo,sync_state_repo,search_repo}.py`, `backend/app/services/search_service.py` (skeleton), `backend/tests/test_data_source_isolation.py`

**Interfaces:**
- Consumes: `get_pool()`, `get_db()`, `get_es()`
- Produces: `users_repo.list_users()`; `products_repo.{list_products,get_product,create_product,update_product}`; `orders_repo.{insert_order,insert_items,get_order,get_order_items,update_status_guarded(order_id,status,expected_version)->int,list_orders_updated_since(watermark_dt,limit)->list[int]}`; `outbox_repo.{enqueue(event, aggregate_id, version)->int (INSERT ... RETURNING id), claim_unprocessed(limit), mark_processed(outbox_id), mark_failed(outbox_id, error)->None, mark_superseded(outbox_id, reason)->None, get(outbox_id)}` with `MAX_ATTEMPTS = 5`. **All three settlement helpers key on `id` and are compare-and-set** (`WHERE id=$1 AND processed_at IS NULL`) so redelivery is idempotent; none of them accepts or derives an `aggregate_id`. `sync_state_repo.{get_watermark,set_watermark,reset_watermark}`; `search_repo.search_orders(req:SearchRequest)->SearchResponse`. `search_service` must import **only** `search_repo`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_data_source_isolation.py
# Screen 3 is Elasticsearch-only (spec §4). Asserted by parsing the import graph,
# not by grepping one file: an AST walk catches aliased and from-imports that a
# substring check would miss.
import ast
from pathlib import Path

PG_FORBIDDEN = {"orders_repo", "users_repo", "outbox_repo", "sync_state_repo"}
MONGO_FORBIDDEN = {"products_repo"}
ES_ALLOWED_FOR_SEARCH = {"search_repo"}

def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            names.update(a.name.rsplit(".", 1)[-1] for a in node.names)
    return names

def test_search_service_imports_no_pg_or_mongo_repo():
    got = imports_of(Path("app/services/search_service.py"))
    assert got & PG_FORBIDDEN == set()
    assert got & MONGO_FORBIDDEN == set()
    # it must actually reach Elasticsearch, not just avoid the others
    assert "search_repo" in got

def test_search_service_does_not_open_a_pg_or_mongo_client():
    src = Path("app/services/search_service.py").read_text()
    for forbidden in ["get_pool", "get_db", "get_mongo"]:
        assert forbidden not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_data_source_isolation.py -v`
Expected: FAIL — `app/services/search_service.py` does not exist.

- [ ] **Step 3: Implement the seven repository modules + `search_service` skeleton**

`search_service.search_orders(req)` calls `search_repo.search_orders` only. `search_repo.search_orders` builds the ES query: `bool`→`must` `multi_match` over `customer.name^2`, `items.title.prefix`, `items.title`, `customer.email`; `filter` for `terms` status and `range` on date/price; aggs `sum(total_amount)` and `terms(status)`. It re-quantizes ES money through `Decimal(...).quantize(Decimal("0.01"))` before returning so the response model emits strings.

**The aggregations must run in a separate, unbounded sub-search.** `hits` and `aggs` are affected differently: if the request body sets `size: 10` at the top level, an agg defined there is still evaluated over the whole matching set — but only because ES treats top-level aggs as document-scoped. The failure mode to avoid explicitly is computing revenue by iterating returned hits, or by issuing the agg inside a `size`-bounded nested query. Implement the request with `size` for hits and a sibling `aggs` object for `orders_revenue`/`orders_by_status`, and **never** derive `revenue` from `hits` in Python. Task 12's `test_revenue_agg_spans_all_pages_not_just_hits` is the regression guard for exactly this.

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/ backend/app/services/search_service.py backend/tests/test_data_source_isolation.py
git commit -m "feat: per-store repositories; screen-3 search isolated to es"
```

---

## Task 6: Order placement transaction + Strategy A/B branch

**Files:**
- Create: `backend/app/services/order_service.py`, `backend/tests/test_order_placement.py`
- Modify: `backend/app/repositories/orders_repo.py` (add insert helpers if needed)

**Interfaces:**
- Consumes: repositories from Task 5
- Produces: `order_service.place_order(req:OrderCreate) -> OrderOut` and `order_service.update_status(order_id:int, status:str, expected_version:int) -> OrderOut`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_place_order_persists_and_computes_total(pg_pool, mongo_db):
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    out = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 2}]))
    assert out.total_amount == "100.32"          # 2 x 50.16
    row = await pg_pool.fetchrow("SELECT total_amount FROM orders WHERE id=$1", out.order_id)
    assert Decimal(row["total_amount"]) == Decimal("100.32")
    # snapshot captured
    it = await pg_pool.fetchrow("SELECT title, unit_price FROM order_items WHERE order_id=$1", out.order_id)
    assert it["title"] == "Wireless Mouse" and Decimal(it["unit_price"]) == Decimal("50.16")

async def test_inactive_product_409_and_no_pg_rows(mongo_db, pg_pool):
    pid = await insert_product(mongo_db, "Hidden", "10.00", active=False)
    with pytest.raises(HTTPException) as e:
        await place_order(OrderCreate(user_id=1, items=[{"product_id": pid, "quantity": 1}]))
    assert e.value.status_code == 409
    assert await pg_pool.fetchval("SELECT count(*) FROM orders") == 0   # no partial write

async def test_dual_write_writes_outbox_row_in_same_txn(pg_pool, monkeypatch):
    monkeypatch.setenv("ORDER_SYNC_STRATEGY", "dual_write")
    # ... place order ...
    assert await pg_pool.fetchval("SELECT count(*) FROM outbox WHERE aggregate_id=$1 AND processed_at IS NULL", oid) == 1

async def test_polling_writes_no_outbox_row(pg_pool, monkeypatch):
    monkeypatch.setenv("ORDER_SYNC_STRATEGY", "polling")
    # ... place order ...
    assert await pg_pool.fetchval("SELECT count(*) FROM outbox") == 0
    # and sync_status is DEFERRED

# PG-side version guard (spec §17 scenario 7). The ES-side rejection of a stale
# write is covered in Task 13; this proves the database refuses it first.
async def test_stale_status_update_is_rejected_409(pg_pool, mongo_db):
    uid = await insert_user(pg_pool, "John", "john@example.com")
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    o = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))
    # first update succeeds and bumps version 1 -> 2 via the trigger
    await update_status(o.order_id, "PROCESSING", expected_version=1)
    # a second writer still holding version 1 is now stale
    with pytest.raises(HTTPException) as e:
        await update_status(o.order_id, "SHIPPED", expected_version=1)
    assert e.value.status_code == 409
    row = await pg_pool.fetchrow("SELECT status, version FROM orders WHERE id=$1", o.order_id)
    assert row["status"] == "PROCESSING"    # stale write did not land
    assert row["version"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_order_placement.py -v`
Expected: FAIL — `order_service` not implemented.

- [ ] **Step 3: Implement `place_order` per spec §11**

Order of operations is load-bearing: validate → one Mongo `$in` snapshot query (409 on missing/inactive, before any PG write) → `total = Σ(quantity*price)` Decimal 2dp → **one** `async with pool.acquire() as c: async with c.transaction():` inserting `orders` (`status='PENDING'`,`version=1`), `order_items`, and (A only) `outbox('ORDER_CREATED')` → commit → post-commit branch: A `index_order.delay(order_id, outbox_id)`, B no-op. Return `sync_status` `QUEUED` (A) or `DEFERRED` (B).

Capture the inserted `outbox_id` with `INSERT ... RETURNING id` inside the transaction, then dispatch `(order_id, outbox_id)` **after** commit. The pair is what identifies the work: `order_id` says *what* to index, `outbox_id` says *which event row* to settle. Dispatching `order_id` alone would make the worker unable to mark the correct row, and guessing by `aggregate_id` would let it settle a sibling event. `index_order` also handles `outbox_id=None` (a manual `reindex` or a direct call), in which case it indexes and settles nothing.

`update_status` calls `orders_repo.update_status_guarded(order_id, status, expected_version)`, which issues `UPDATE orders SET status=$3 WHERE id=$1 AND version=$2` and returns the affected row count. **0 rows means a stale write → raise 409.** On success the `orders_touch` trigger has already bumped `version` and `updated_at`; read the new row back and use its `version` for the outbox row and the dispatch, so the worker indexes the version that actually committed. Under Strategy A write an outbox row (`ORDER_STATUS_CHANGED`, its own distinct `outbox_id`) inside the same transaction and dispatch `(order_id, outbox_id)` after commit; under Strategy B do neither.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_order_placement.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/order_service.py backend/app/repositories/orders_repo.py backend/tests/test_order_placement.py
git commit -m "feat: order placement in one pg transaction; mongo-before-txn; strategy branch"
```

---

## Task 7: Celery app, tasks, and the single `build_order_document` projection

**Files:**
- Create: `backend/app/services/sync_service.py`, `backend/app/services/outbox_service.py`, `backend/app/workers/{__init__,celery_app,tasks}.py`, `backend/tests/test_sync_projection.py`

**Interfaces:**
- Consumes: repos, `get_es`, `get_pool`
- Produces: `sync_service.build_order_document(conn, order_id:int) -> dict` (the single PG→ES projection); `sync_service.index_order(order_id:int, outbox_id:int|None = None) -> None`; `celery_app` (broker from `get_settings().rabbitmq_url`, `task_acks_late=True`, `task_ignore_result=True`, beat schedule). Tasks: `index_order(order_id, outbox_id)`, `drain_outbox` (A); `poll_orders`, `poll_once` (B).

**`index_order` takes the specific outbox event, not just the order.** The signature is `index_order(order_id: int, outbox_id: int | None = None)`, and the Celery task mirrors it. The worker must be able to settle *exactly* the row it was dispatched for:

- `outbox_id=None` is legal and means "index but settle nothing" — used by `reindex` and by manual/scripted calls that have no event row.
- When `outbox_id` is given, every terminal call (`mark_processed` / `mark_superseded` / `mark_failed`) targets **that** `outbox_id`.
- The worker must **never** settle a row chosen by `aggregate_id = order_id`. One order can have several unprocessed events (`ORDER_CREATED` plus later `ORDER_STATUS_CHANGED` rows); settling by aggregate would let a stale `ORDER_CREATED` worker mark a newer event done and lose it. `test_index_order_settles_only_its_own_outbox_row` enforces this.
- Settling is a compare-and-set: `UPDATE outbox SET processed_at=now() WHERE id=$1 AND processed_at IS NULL`, so a duplicate delivery is idempotent and cannot double-settle.

- [ ] **Step 1: Write the failing test**

```python
async def test_build_order_document_shape(pg_pool, mongo_db):
    uid = await insert_user(pg_pool, "John", "john@example.com")
    oid = await insert_order(pg_pool, uid, "100.32")
    async with pg_pool.acquire() as conn:
        doc = await build_order_document(conn, oid)
    assert doc["order_id"] == oid
    assert doc["status"] in ("PENDING","PROCESSING","SHIPPED")
    assert doc["version"] == 1
    assert doc["customer"]["email"] == "john@example.com"
    assert len(doc["items"]) == 2
    assert doc["items"][0]["title"] == "Wireless Mouse"   # snapshot
    # money emitted numeric (ES scaled_float) but derived from Decimal
    assert doc["total_amount"] == 100.32

# ---- external-version conflict handling (spec §12, §17 scenario 7) ----

async def test_stale_worker_cannot_overwrite_newer_doc(pg_pool, es, outbox):
    # A newer order version is already indexed.
    doc_v2 = {"order_id": 1, "version": 2, "status": "SHIPPED", "total_amount": 100.32}
    await es.index(index="orders", id="1", document=doc_v2, version=2, version_type="external")
    # A stale worker holds version 1 and tries to write.
    stale = {"order_id": 1, "version": 1, "status": "PENDING", "total_amount": 100.32}
    with pytest.raises(ConflictError):
        await es.index(index="orders", id="1", document=stale, version=1, version_type="external")
    await es.indices.refresh(index="orders")
    got = (await es.get(index="orders", id="1"))["_source"]
    assert got["status"] == "SHIPPED"      # newer doc survived
    assert got["version"] == 2

async def test_version_conflict_is_terminal_not_retried(pg_pool, es, outbox):
    row = await enqueue_outbox(aggregate_id=1, event="ORDER_CREATED", version=1)
    # index v2 first so the worker's v1 write conflicts
    await es.index(index="orders", id="1", document={"order_id": 1, "version": 2},
                   version=2, version_type="external")
    await sync_service.index_order(1, row["id"])              # must not raise
    r = await outbox_repo.get(row["id"])
    assert r["processed_at"] is not None
    assert r["attempts"] == 0                               # not retried at all
    assert "superseded" in (r["last_error"] or "")

async def test_es_outage_is_retried_then_marked_failed(pg_pool, es, outbox, monkeypatch):
    row = await enqueue_outbox(aggregate_id=1, event="ORDER_CREATED", version=1)
    monkeypatch.setattr(sync_service.es, "index", _raise_transport_error)
    with pytest.raises(Exception):
        await sync_service.index_order(1, row["id"])
    r = await outbox_repo.get(row["id"])
    assert r["processed_at"] is None                        # still retryable
    assert r["attempts"] == 1 and r["last_error"]
    # after max_attempts the row is terminal so drain_outbox stops re-dispatching
    for _ in range(outbox_repo.MAX_ATTEMPTS):
        with pytest.raises(Exception):
            await sync_service.index_order(1, row["id"])
    assert (await outbox_repo.get(row["id"]))["processed_at"] is not None

# ---- outbox identity: the worker settles only the event it was given ----

async def test_index_order_settles_only_its_own_outbox_row(pg_pool, es, outbox):
    """One order can have several unprocessed events. A worker holding
    ORDER_CREATED must not mark a newer ORDER_STATUS_CHANGED row done, and a
    conflict on the created-event must not settle the status event either."""
    created = await enqueue_outbox(aggregate_id=1, event="ORDER_CREATED", version=1)
    changed = await enqueue_outbox(aggregate_id=1, event="ORDER_STATUS_CHANGED", version=2)
    # index v2 so the v1 write from the created-event conflicts
    await es.index(index="orders", id="1", document={"order_id": 1, "version": 2},
                   version=2, version_type="external")
    await sync_service.index_order(1, created["id"])
    assert (await outbox_repo.get(created["id"]))["processed_at"] is not None
    assert (await outbox_repo.get(changed["id"]))["processed_at"] is None   # untouched
    assert (await outbox_repo.get(changed["id"]))["attempts"] == 0

async def test_index_order_without_outbox_id_settles_nothing(pg_pool, es, outbox):
    """outbox_id=None means 'index but settle nothing' (reindex path)."""
    created = await enqueue_outbox(aggregate_id=1, event="ORDER_CREATED", version=1)
    await sync_service.index_order(1, None)
    assert (await outbox_repo.get(created["id"]))["processed_at"] is None
    assert (await es.get(index="orders", id="1"))["_source"]["order_id"] == 1

async def test_duplicate_delivery_settles_once(pg_pool, es, outbox):
    """task_acks_late means redelivery happens; settlement must be idempotent."""
    row = await enqueue_outbox(aggregate_id=1, event="ORDER_CREATED", version=1)
    await sync_service.index_order(1, row["id"])
    first = (await outbox_repo.get(row["id"]))["processed_at"]
    await sync_service.index_order(1, row["id"])
    assert (await outbox_repo.get(row["id"]))["processed_at"] == first
    assert (await outbox_repo.get(row["id"]))["attempts"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `sync_service` missing.

- [ ] **Step 3: Implement `build_order_document` + tasks**

`build_order_document` runs the projection query (order + user + items in one join) and returns the exact §9 document.

**`index_order` must distinguish a stale version from an outage.** This is the one place the external-version guard is actually enforced, and the two failure modes need opposite handling:

```python
async def index_order(order_id: int, outbox_id: int | None = None) -> None:
    """Index one order. outbox_id names the exact outbox event this call is
    settling; None means index-and-settle-nothing (reindex / manual path)."""
    async with pool.acquire() as conn:
        doc = await build_order_document(conn, order_id)
    try:
        await es.index(index="orders", id=str(order_id), document=doc,
                       version=doc["version"], version_type="external")
    except ConflictError as e:
        if _is_version_conflict(e):          # 409 version_conflict_engine_exception
            # A NEWER version is already in the index. PG is the source of truth,
            # so the stale worker losing is the correct outcome: mark terminal and
            # return. Do NOT retry -- retrying can never win, and would spin forever.
            if outbox_id is not None:
                await outbox_repo.mark_superseded(outbox_id, "stale version")
            return
        raise
    except (ApiError, ConnectionError, TransportError) as e:
        # Genuine outage: retryable. Record the error, let the row stay unprocessed,
        # and re-raise so Celery's bounded retry/backoff handles it.
        if outbox_id is not None:
            await outbox_repo.mark_failed(outbox_id, str(e))
        raise
    if outbox_id is not None:
        await outbox_repo.mark_processed(outbox_id)
```

Every settlement helper targets the `outbox_id` it was handed — never a row
looked up by `aggregate_id`:

```sql
-- mark_processed / mark_superseded / mark_failed all follow this shape
UPDATE outbox
SET processed_at = now(), last_error = $2      -- or superseded/attempts+1
WHERE id = $1 AND processed_at IS NULL         -- compare-and-set: idempotent
RETURNING id;
```

`WHERE processed_at IS NULL` makes settlement a compare-and-set, so a redelivered
task (expected, given `task_acks_late=True`) cannot double-settle or resurrect a
finished row, and two workers racing on the same event settle it exactly once.
`claim_unprocessed` in `drain_outbox` uses `FOR UPDATE SKIP LOCKED` with
`attempts < MAX_ATTEMPTS` so two drains never dispatch the same event concurrently.

Rules to implement, each with a test above:
- **A stale version is terminal, never retried.** `version_type="external"` makes ES reject any write whose `version` is `<=` the stored one. Catch `ConflictError` and confirm the body is `version_conflict_engine_exception`; treat it as success-with-supersession via `outbox_repo.mark_superseded`, never as an error. Retrying is provably futile, so the worker must not enter a retry loop or leave the row claiming to be pending forever.
- **The worker settles only its own event.** `index_order` receives the specific `outbox_id` and settles that row and no other. It must never resolve a row by `aggregate_id`, because a single order can have several live events and settling a sibling would silently lose it (`test_index_order_settles_only_its_own_outbox_row`).
- **Genuine outages stay retryable.** `ConnectionError`, `TimeoutError`, and `5xx` `ApiError` are *not* version conflicts. Bump `attempts` and `last_error`, leave `processed_at` NULL, and re-raise so `autoretry_for`/`retry_backoff` retries with backoff.
- **Retries are bounded.** After `outbox_repo.MAX_ATTEMPTS` (e.g. 5), mark the row terminal-failed so `drain_outbox` stops re-dispatching it, and leave it visible for `reindex` to repair.
- **Never write without a version.** `version` and `version_type="external"` are always passed together; a write with no version would silently downgrade a document and defeat the whole guard.

`drain_outbox` claims unprocessed rows (`FOR UPDATE SKIP LOCKED`, `attempts < MAX_ATTEMPTS`) and re-dispatches each as `index_order(row.aggregate_id, row.id)` — passing the row's own `id`, so the retry settles the same event it claimed rather than a sibling for the same order. `poll_orders` reads the watermark (NULL-safe), selects the window, bulk-indexes with `version_type="external"`, then advances the watermark per Task 13. All share `build_order_document`.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_sync_projection.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_service.py backend/app/services/outbox_service.py backend/app/workers/ backend/tests/test_sync_projection.py
git commit -m "feat: single build_order_document projection; celery tasks for both strategies"
```

---

## Task 8: API routers and app wiring

**Files:**
- Create: `backend/app/api/{__init__,products,orders,search,users,sync,health}.py`, `backend/app/main.py`, `backend/tests/test_api_smoke.py`
- Modify: `backend/tests/test_data_source_isolation.py` (add the router-level checks now that routers exist)

**Interfaces:**
- Consumes: services + repos
- Produces: FastAPI app with routers at the exact spec §10 paths: `GET/POST/PUT /api/products[/{id}]`, `GET /api/users`, `POST/GET/PATCH /api/orders[/{id}[/status]]`, `POST /api/search/orders`, `GET /api/sync/status/{order_id}`, `POST /api/sync/{drain-outbox,poll-once,reset-watermark,reindex}`, `GET /api/health`. CORS allows `http://localhost:5173`. Lifespan opens clients and calls `ensure_orders_index()`.

- [ ] **Step 1: Write the failing smoke tests**

```python
async def test_health_ok(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert set(r.json()) == {"postgres","mongo","elasticsearch"}

async def test_search_endpoint_returns_string_money(client):
    r = await client.post("/api/search/orders", json={})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["revenue"], str)          # money is a string from ES
    for h in body["hits"]:
        assert isinstance(h["total_amount"], str)
        for it in h["items"]:
            assert isinstance(it["unit_price"], str)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api_smoke.py -v`
Expected: FAIL — app/routers missing.

- [ ] **Step 3: Implement routers + `main.py`**

`search.py` router depends only on `search_service` (no PG/Mongo import). `health.py` pings each store. `main.py` builds the app, includes routers, configures CORS, and in lifespan opens pools and calls `ensure_orders_index()`. Add `response_model` to every route so money is serialized by the Task 4 string serializers rather than by FastAPI's default encoder.

- [ ] **Step 4: Extend `test_data_source_isolation.py` with the router-level rule**

The spec's rule is per *screen route*, and the routers are where a shortcut would be added, so assert it there using the same `imports_of` AST helper from Task 5:

```python
SCREEN_REPOS = {
    "products": {"products_repo", "users_repo"},            # Screen 1/5: Mongo (+PG users)
    "orders":   {"orders_repo", "products_repo", "search_repo"},  # Screens 2/4: PG (+Mongo snapshot)
    "search":   {"search_repo"},                            # Screen 3: ES ONLY
    "users":    {"users_repo"},
}

def test_each_router_imports_only_its_declared_repositories():
    for router, allowed in SCREEN_REPOS.items():
        got = imports_of(Path(f"app/api/{router}.py")) & ALL_REPOS
        assert got == allowed, f"api/{router}.py imports {got - allowed}"

def test_search_router_reaches_only_elasticsearch():
    got = imports_of(Path("app/api/search.py")) & ALL_REPOS
    assert got == {"search_repo"}
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_api_smoke.py tests/test_data_source_isolation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ backend/app/main.py backend/tests/test_api_smoke.py
git commit -m "feat: api routers and app factory; search router is es-only"
```

---

## Task 9: Deterministic seed generator + invariant verifier

**Files:**
- Create: `backend/scripts/seed.py`, `backend/tests/test_seed_determinism.py`, `backend/tests/test_seed_invariants.py`

**Interfaces:**
- Consumes: `build_order_document`, repos, `ensure_orders_index`
- Produces: `seed.build_order_plan(seed:int, anchor_date:datetime) -> list[OrderSlot]` — a **pure function** of `(seed, anchor_date)`; `seed.main()` honoring `--reset`, `--seed` (default 42), `--anchor-date`, `--verify-only`. Produces 8 users, 25 products (6 named active + 18 accessories active + 1 inactive), 40 orders, ~85 items, ES fully caught up, then renames Wireless Mouse → Wireless Mouse Pro @ 79.00 in MongoDB only, then verifies 18 invariants exiting non-zero on failure.

- [ ] **Step 1: Write the failing determinism test**

```python
def test_plan_is_pure_function_of_seed_and_anchor():
    a = build_order_plan(42, ANCHOR)
    b = build_order_plan(42, ANCHOR)
    assert [s.to_json() for s in a] == [s.to_json() for s in b]   # identical allocations

def test_plan_differs_with_seed():
    assert [s.to_json() for s in build_order_plan(42, ANCHOR)] != [s.to_json() for s in build_order_plan(7, ANCHOR)]

def test_plan_never_calls_now_or_reads_db(monkeypatch):
    # monkeypatch datetime.now to raise; build_order_plan(42, ANCHOR) still succeeds
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `build_order_plan` missing.

- [ ] **Step 3: Implement `build_order_plan` (pure) and the generator/verifier**

`build_order_plan` returns 40 `OrderSlot`s (user, status, date bucket, chosen product ids, quantities) with roles overlapping (spec §18.3). It must derive every incidental choice from a locally seeded `random.Random(seed)` and the passed `anchor_date` — never module RNG state, never `datetime.now()`. Then the writer: insert users → products → orders+items (computing `total_amount` as `Σ(quantity*unit_price)`, never generating it) → project all orders to ES via `build_order_document` → rename the Wireless Mouse in MongoDB only → run the 18 invariant checks reading back from all three stores, printing a report and `sys.exit(1)` on any failure.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_seed_determinism.py -v` → PASS.
Run the full seed against live stores: `python -m scripts.seed --reset` → report shows all invariants pass, exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/seed.py backend/tests/test_seed_determinism.py backend/tests/test_seed_invariants.py
git commit -m "feat: deterministic seed with pure order plan and 18-invariant verifier"
```

---

## Task 10: Reindex script

**Files:**
- Create: `backend/scripts/reindex_orders.py`, `backend/tests/test_reindex.py`

**Interfaces:**
- Consumes: `build_order_document`, `get_es`
- Produces: `reindex_orders.main() -> None` — **async**, so the test awaits it. Deletes `orders`, recreates with the mapping, bulk-indexes every PG order with `version_type="external"`. Shares the projection with all other paths.

- [ ] **Step 1: Write the failing test**

```python
async def test_reindex_rebuilds_full_index(pg_pool, es):
    await seed_minimal(pg_pool, n_orders=3)
    await reindex_orders.main()
    assert await es.count(index="orders") == 3
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement `reindex_orders.py`** per spec §10/§14 (same code path as `POST /api/sync/reindex`).

- [ ] **Step 4: Run test** → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/reindex_orders.py backend/tests/test_reindex.py
git commit -m "feat: reindex script sharing the order projection"
```

---

## Task 11: Snapshot immutability test

**Files:**
- Test: `backend/tests/test_snapshot.py`

**Interfaces:**
- Consumes: `place_order`, mongo
- Proves: catalog edit does not change history (spec §15, Review Focus #1).

- [ ] **Step 1: Write the failing test**

```python
async def test_catalog_edit_does_not_change_history(pg_pool, mongo_db, es):
    pid = await insert_product(mongo_db, "Wireless Mouse", "50.16")
    uid = await insert_user(pg_pool, "John", "john@example.com")
    o = await place_order(OrderCreate(user_id=uid, items=[{"product_id": pid, "quantity": 1}]))
    # rename + reprice in MongoDB
    await mongo_db.products.update_one({"_id": ObjectId(pid)}, {"$set": {"title": "Wireless Mouse Pro", "price": Decimal128("79.00")}})
    # order_items unchanged
    it = await pg_pool.fetchrow("SELECT title, unit_price FROM order_items WHERE order_id=$1", o.order_id)
    assert it["title"] == "Wireless Mouse" and Decimal(it["unit_price"]) == Decimal("50.16")
    # ES document unchanged
    doc = (await es.get(index="orders", id=str(o.order_id)))["_source"]
    assert doc["items"][0]["title"] == "Wireless Mouse"
    assert float(doc["items"][0]["unit_price"]) == 50.16
```

- [ ] **Step 2: Run** → Expected: PASS immediately (proves the invariant holds; it guards against regression). If it fails, an `UPDATE` path is touching snapshots — fix that, not the test.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_snapshot.py
git commit -m "test: catalog edits never mutate historical order snapshots"
```

---

## Task 12: Search correctness test

**Files:**
- Test: `backend/tests/test_search.py`

**Interfaces:**
- Consumes: `search_service.search_orders`
- Proves: facets, filters, revenue agg, and uniform string money from ES (Review Focus #4).

- [ ] **Step 1: Write the tests**

```python
async def test_wireless_query_hits_name_and_product(client):
    r = await client.post("/api/search/orders", json={"q": "Wireless"})
    # includes Wendy Wireless's orders AND orders containing a wireless-tagged product

async def test_filters_shrink_result_set(client):
    base = (await client.post("/api/search/orders", json={})).json()["total"]
    by_status = (await client.post("/api/search/orders", json={"statuses": ["SHIPPED"]})).json()["total"]
    assert by_status <= base

# The revenue aggregation must cover the ENTIRE filtered result set, not the
# current page. Summing over body["hits"] is wrong: hits is truncated to `size`,
# so a page-1 test would pass even if the agg were computed over hits only.
async def test_revenue_agg_is_exact_and_string(client):
    body = (await client.post("/api/search/orders", json={})).json()
    assert isinstance(body["revenue"], str)          # money as string from ES
    expected = _expected_revenue(statuses=None, q=None)   # computed from PG in the test
    assert Decimal(body["revenue"]) == expected

async def test_revenue_agg_spans_all_pages_not_just_hits(client):
    """Revenue must be independent of page size. If the agg covered only the
    returned hits, shrinking the page would shrink the revenue."""
    big = (await client.post("/api/search/orders", json={"size": 100})).json()
    small = (await client.post("/api/search/orders", json={"size": 1})).json()
    assert len(small["hits"]) < len(big["hits"]) or big["total"] <= 1
    assert small["revenue"] == big["revenue"] == _expected_revenue(None, None)

async def test_revenue_agg_respects_the_filter(client):
    """A filtered aggregation must not include unfiltered rows."""
    all_rev = (await client.post("/api/search/orders", json={})).json()["revenue"]
    shipped = (await client.post("/api/search/orders", json={"statuses": ["SHIPPED"]})).json()
    assert Decimal(shipped["revenue"]) <= Decimal(all_rev)
    assert Decimal(shipped["revenue"]) == _expected_revenue(["SHIPPED"], None)
```

`test_search.py` adds a `_expected_revenue(statuses, q)` helper that computes the
expected sum **from PostgreSQL**, not from Elasticsearch. That independence is the
point: a PG-derived oracle catches a mis-scoped `size`-limited agg, a wrong filter,
and a scaled_float rounding error in one assertion. It sums `orders.total_amount`
for the same predicate the API applied.

- [ ] **Step 2: Run** → PASS (regression guard). Fix `search_repo` money re-quantization if the string/Decimal assertion fails, and fix the aggregation if the page-independence test fails.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_search.py
git commit -m "test: es search facets, page-independent revenue agg, string money from es"
```

---

## Task 13: Sync strategy tests (A dual-write, B polling)

**Files:**
- Test: `backend/tests/test_sync_dual_write.py`, `backend/tests/test_sync_polling.py`

**Interfaces:**
- Consumes: `index_order`, `drain_outbox`, `poll_orders`, repos
- Proves: Review Focus #2 (stale write rejected) and #3 (NULL watermark + ties).

**Watermark contract under test** (spec §13). `poll_orders` reads `sync_state.last_polled_at` and must behave as follows — each clause has a test below:

| Rule | Behavior | Guard against |
|---|---|---|
| NULL-first poll | `last_polled_at IS NULL` → no lower bound, select **all** orders | the classic `updated_at > NULL` bug that matches zero rows forever |
| 30-second overlap | bound is `last_polled_at - INTERVAL '30 seconds'`, never the bare watermark | a row committed microseconds after the last poll is skipped forever |
| Deterministic order | `ORDER BY updated_at, id` | a non-deterministic order makes ties and advancement non-reproducible |
| Identical-timestamp ties | several rows may share one `updated_at`; all must be indexed | dropping ties silently loses orders |
| Exact advancement | advance to the **max `(updated_at, id)` actually indexed**, and only after the whole batch succeeded | advancing past a partially-failed batch silently skips orders |

- [ ] **Step 1: Write the failing tests**

```python
# test_sync_dual_write.py
async def test_es_down_leaves_outbox_pending_then_drains(pg_pool, es, monkeypatch):
    # place order (A) -> index_order fails (es down) -> outbox row unprocessed with attempts/last_error
    # es back -> drain_outbox -> row processed, doc present

async def test_stale_es_write_rejected_by_external_version(pg_pool, es):
    # index v1, bump pg to v2, index v2, then index v1 again -> es still shows v2

async def test_stale_worker_does_not_retry_conflict_endlessly(pg_pool, es, outbox):
    """A version conflict is terminal: the worker must not re-raise it into a
    retry loop, because retrying a stale version can never succeed."""
    row = await enqueue_outbox(aggregate_id=1, event="ORDER_CREATED", version=1)
    # index v2 first so the v1 write conflicts
    await es.index(index="orders", id="1", document={"order_id": 1, "version": 2},
                   version=2, version_type="external")
    await index_order(1, row["id"])              # must NOT raise ConflictError
    assert (await outbox_repo.get(row["id"]))["processed_at"] is not None
    assert (await outbox_repo.get(row["id"]))["attempts"] == 0
    assert "superseded" in ((await outbox_repo.get(row["id"]))["last_error"] or "")


# test_sync_polling.py
async def test_null_watermark_returns_all_orders(pg_pool, es):
    """NULL watermark must mean 'no lower bound', not 'match nothing'.
    Guard the SQL-shape bug: `updated_at > NULL` yields zero rows forever."""
    await sync_state_repo.reset_watermark(pg_pool)
    await poll_orders()
    assert await es.count(index="orders") == await pg_pool.fetchval("SELECT count(*) FROM orders")

async def test_second_poll_with_null_watermark_is_idempotent(pg_pool, es):
    await sync_state_repo.reset_watermark(pg_pool)
    await poll_orders(); await poll_orders()
    assert await es.count(index="orders") == await pg_pool.fetchval("SELECT count(*) FROM orders")

async def test_overlap_reindexes_recently_updated_row(pg_pool, es):
    """The 30s overlap means a row updated just before the last poll is picked
    up again rather than being skipped by a bare `> watermark` bound."""
    oid = await _seed_order(pg_pool, updated_at=now() - timedelta(seconds=5))
    await sync_state_repo.set_watermark(pg_pool, now() - timedelta(seconds=10))  # ahead of the row
    await es.delete(index="orders", id=str(oid), ignore=[404])
    await poll_orders()
    assert (await es.get(index="orders", id=str(oid)))["_source"]["order_id"] == oid

async def test_identical_updated_at_rows_not_dropped(pg_pool, es):
    """Ties on updated_at must all be indexed, and the watermark must not
    advance past any of them."""
    t = now() - timedelta(minutes=1)
    a = await _seed_order(pg_pool, updated_at=t)
    b = await _seed_order(pg_pool, updated_at=t)
    await sync_state_repo.set_watermark(pg_pool, t - timedelta(minutes=1))
    await poll_orders()
    assert {h["_source"]["order_id"] for h in (await es.search(index="orders", size=10))["hits"]["hits"]} >= {a, b}

async def test_watermark_advances_to_max_indexed_pair(pg_pool, es):
    await _seed_order(pg_pool, updated_at=now() - timedelta(minutes=2))
    last = await _seed_order(pg_pool, updated_at=now() - timedelta(minutes=1))
    await sync_state_repo.reset_watermark(pg_pool)
    await poll_orders()
    wm = await sync_state_repo.get_watermark(pg_pool)
    assert wm is not None
    assert abs((wm - (now() - timedelta(minutes=1))).total_seconds()) <= 5

async def test_watermark_does_not_advance_on_failure(pg_pool, es, monkeypatch):
    """A failed batch must leave the watermark exactly where it was, otherwise
    the orders in that batch are never retried."""
    await _seed_order(pg_pool)
    before = await sync_state_repo.get_watermark(pg_pool)
    monkeypatch.setattr(sync_service.es, "bulk", _raise_transport_error)
    with pytest.raises(Exception):
        await poll_orders()
    assert await sync_state_repo.get_watermark(pg_pool) == before

async def test_watermark_not_advanced_past_partially_failed_batch(pg_pool, es, monkeypatch):
    """If any document in the batch fails to index, the watermark must stay put
    so the whole window is re-polled next time."""
    await _seed_order(pg_pool)
    before = await sync_state_repo.get_watermark(pg_pool)
    monkeypatch.setattr(sync_service.es, "bulk", _partial_bulk_with_one_failure)
    with pytest.raises(Exception):
        await poll_orders()
    assert await sync_state_repo.get_watermark(pg_pool) == before
```

- [ ] **Step 2: Run tests to verify they fail (or expose gaps)**

Run: `cd backend && python -m pytest tests/test_sync_dual_write.py tests/test_sync_polling.py -v`
Expected: FAIL until the tasks in Task 7 fully satisfy them; fix task code, not the assertions.

- [ ] **Step 3: Make them pass**

`poll_orders` implements the five-rule table above, and the advancement rule needs to be exact. **Do not implement the watermark as `set_watermark(now())`.** That is the tempting one-liner and it is wrong twice over: it can skip rows (anything that committed between the batch read and the `now()` call is never re-read, because it falls *below* the new watermark and outside the 30s overlap), and it makes advancement non-deterministic across runs. Write it as:

```sql
-- 1. NULL-safe lower bound + deterministic order + stable paging.
--    $1 is the stored watermark (may be NULL); the 30s overlap always applies.
--    The $1 IS NULL branch is what makes the first poll return every row:
--    `updated_at > NULL` is NULL, so without this arm the first poll matches
--    nothing and the index stays empty forever.
SELECT o.id, o.updated_at
FROM orders o
WHERE ($1::timestamptz IS NULL
       OR o.updated_at > $1::timestamptz - INTERVAL '30 seconds')
ORDER BY o.updated_at, o.id          -- deterministic; ties broken by id
LIMIT $2;
```

```python
# 2. Index the whole window; track the max (updated_at, id) actually processed.
rows = await self._fetch_window(watermark, limit)   # ordered by (updated_at, id)
if not rows:
    return                                          # empty window: leave the watermark alone
max_pair = (rows[-1]["updated_at"], rows[-1]["id"]) # last row == max, because of the ORDER BY

# 3. Bulk-index with external versioning. Any failure raises and aborts here,
#    BEFORE the watermark write, so a partial batch is re-polled next tick.
docs = [await self._project(r["id"]) for r in rows]
await self._bulk_index(docs)

# 4. Only now, and only to the max pair actually indexed -- never now().
await sync_state_repo.set_watermark(self.pool, max_pair[0])
```

Rules, each mapped to a test above:
- **NULL-first poll.** A NULL `last_polled_at` means *no lower bound*, so the first poll returns every order and `es.count == pg count`. Implemented as `$1 IS NULL OR ...` above; the alternative formulations (`COALESCE` to epoch, or `updated_at > NULL`) behave differently and are wrong.
- **30-second overlap.** The lower bound is always `watermark - 30 seconds`, never the bare watermark, so a row committed just after the previous batch is still caught.
- **Deterministic order.** `ORDER BY updated_at, id` makes the batch reproducible and makes "the last row" a well-defined maximum. Without the `id` tiebreaker, two rows sharing a timestamp could page in either order and the recorded max would be arbitrary.
- **Identical-timestamp ties are safe.** Because the next window restarts 30s earlier, every row sharing the boundary timestamp is re-read on the next poll; the external-version guard turns those harmless duplicate writes into no-ops instead of conflicts. `test_identical_updated_at_rows_not_dropped` proves no tie is lost.
- **Advance to the max actually processed, only on success.** The watermark is written from `max_pair`, derived from rows that Elasticsearch confirmed indexing, and only after the whole batch succeeds. Two tests guard it: `test_watermark_does_not_advance_on_failure` (transport error) and `test_watermark_not_advanced_past_partially_failed_batch` (one bad document in an otherwise-good bulk). If a later read returns zero rows, the watermark is left unchanged rather than reset.

> **Deliberate tightening of spec §13.** The spec's sequence diagram writes `UPDATE sync_state SET last_polled_at = now()`. `now()` is the *transaction* timestamp, and it is taken **after** the batch was read, so any order that commits in that window lands below the new watermark and is never re-read — a silent skip the spec's own "nothing can be lost" property forbids. This plan therefore advances to the maximum `(updated_at, id)` actually indexed, which is what spec §13's prose ("the watermark advances only after indexing") intends. The 30-second overlap and idempotent upsert make the extra re-reads free, so this is strictly safer with no cost. Flagged here rather than changed silently; the spec diagram should be amended to match.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_sync_dual_write.py backend/tests/test_sync_polling.py
git commit -m "test: dual-write outbox recovery and polling watermark safety"
```

---

## Task 14: Frontend skeleton (Vite + Vue 3 + Pinia + Router)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/{main.js,App.vue,router.js,utils/money.js,api/{products,orders,search,users}.js,stores/{cart,session,catalog,orders,search}.js}`

**Interfaces:**
- Consumes: the API from Task 8.
- Produces: a runnable SPA shell. `utils/money.js` exports `formatMoney(str) -> "$150.50"` using `Intl.NumberFormat` on the string. Five Pinia stores (`cart`, `session`, `catalog`, `orders`, `search`) kept separate so `search` never shares code with `orders` (spec §5). `vite.config.js` serves on 5173 and proxies `/api` to `localhost:8000`. No jQuery, no server-side templating.

- [ ] **Step 1: Scaffold the files** (no test task — backend-only test stack; verify by building).

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npm install && npm run build`
Expected: `vite build` completes with no errors. This is a **build-only** gate: `npm run dev` is a long-running server and must not be chained with `&&`, or the command never returns and the step hangs with no output.

- [ ] **Step 3: Verify it serves (background, then stop)**

Run `npm run dev` as a **separate, backgrounded** step and confirm startup, rather than appending it to the build:

```bash
cd frontend
npm run dev > /tmp/vite.log 2>&1 &
VITE_PID=$!
sleep 4
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:5173/   # expect 200
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/health  # expect 200, backend up
kill "$VITE_PID"; wait "$VITE_PID" 2>/dev/null
```

Expected: both curls print `200`; the dev server logs `5173` and proxies `/api` to `8000`. Always `kill` the background PID so the port is free for Task 15.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): vite+vue3+pinia skeleton, five isolated stores, money util"
```

---

## Task 15: The five screens

**Files:**
- Create: `frontend/src/views/{StorefrontView,CheckoutView,AdminSearchView,OrderDetailView,CatalogAdminView}.vue`, `frontend/src/components/{ProductCard,ProductFilters,CartSummary,OrderStatusSelect,SyncBadge,FacetSidebar,KpiCards,OrderResultsTable,ProductForm}.vue`

**Interfaces:**
- Consumes: stores + api modules.
- Data-source rule (spec §4): Storefront & Catalog read Mongo-backed `/api/products`; Checkout posts to `/api/orders`; AdminSearch reads **only** `POST /api/search/orders` (never PG/Mongo endpoints); OrderDetail reads `/api/orders/{id}` + `/api/sync/status/{id}` for the `SyncBadge`.

- [ ] **Step 1: Build the five views and their components** to the spec's routes `/`, `/checkout`, `/admin/orders`, `/admin/orders/:id`, `/admin/catalog`.

- [ ] **Step 2: Wire Router** in `router.js`.

- [ ] **Step 3: Verify by running** the app against the seeded backend and clicking through all five screens (storefront→cart→checkout commit; admin search facets/KPIs; order detail status change + badge; catalog edit).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/ frontend/src/components/ frontend/src/router.js
git commit -m "feat(frontend): five screens with per-screen data-source routing"
```

---

## Task 16: Demo plumbing — Makefile, README, NOTES

**Files:**
- Create: `Makefile`, `README.md`, `NOTES.md`

**Interfaces:**
- `Makefile` targets: `up` (docker compose up), `migrate`, `seed`, `reindex`, `api`, `worker`, `beat`, `frontend`, `reset-watermark` (dev convenience only, spec §22).
- `README.md`: boot → migrate → seed → run → demo all 5 screens → demo both strategies (spec §21 Parts 0–3, with the measured latency table).
- `NOTES.md`: answers all five learning milestones from observed behavior + `A-queued` vs `A-inline` contrast (spec §21 Part 4, §2).

- [ ] **Step 1: Write `Makefile`**

- [ ] **Step 2: Write `README.md`** including the boot-to-demo path and the strategy comparison walkthrough.

- [ ] **Step 3: Write `NOTES.md`** answering: split-brain, why not SQL search, why MongoDB for the catalog, snapshotting, write-path discipline; plus A-queued vs A-inline.

- [ ] **Step 4: Verify end-to-end per spec §24 gates**: reindex from empty ES; seed report all-pass; both strategies converge; milestone 1 answered; five screens run with zero manual entry.

- [ ] **Step 5: Commit**

```bash
git add Makefile README.md NOTES.md
git commit -m "docs: makefile, readme demo guide, notes with learning milestones"
```

---

## Task 17: Final verification gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Confirm clean tree and no secrets**

Run: `git status` (clean) and grep for committed secrets (none; `.env` is gitignored, only `.env.example` committed).

- [ ] **Step 3: Commit any last fixes** if the gate surfaced anything; otherwise stop.
