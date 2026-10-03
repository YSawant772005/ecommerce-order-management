# E-Commerce Order Management and Search Service
## Knowledge Bytes

This is the detailed learning and reference document for the repository. It is written from the implementation in `backend/`, `frontend/`, the SQL schema, tests, and Compose files. The README remains the short setup and demo guide.

The project is a Vue 3 application over a FastAPI API. It deliberately uses three data stores:

- MongoDB owns the flexible product catalog.
- PostgreSQL owns users, orders, order items, status, money, versions, and the outbox.
- Elasticsearch owns a searchable projection used by the admin search screen.

RabbitMQ transports synchronization messages. Celery runs synchronization work. Neither is a database, and neither is a synchronization strategy. The only implemented strategy is asynchronous queued dual-write: PostgreSQL commits first, then an outbox event is sent through RabbitMQ and Celery to Elasticsearch.

# PART 0 - THE BIG PICTURE

Before reading individual files, see how one user action travels through the project.

```text
Client browser
    |
    v
Vue 3 + Vite (development) or Nginx (container)
    |
    v
FastAPI JSON API (/api)
    |                  |                    |
    v                  v                    v
 MongoDB           PostgreSQL          Elasticsearch
 product catalog   orders and truth    admin search projection
                    |
                    v
              outbox -> RabbitMQ -> Celery worker
                    |                         |
                    +-------------------------+
                       index into Elasticsearch
```

## Components that actually exist

| Layer | Actual location | Responsibility |
|---|---|---|
| Frontend bootstrap | `frontend/src/main.js`, `router.js` | Mounts Vue, Pinia, and routes |
| Frontend screens | `frontend/src/views/` | Storefront, checkout, search, order detail, catalog admin |
| HTTP API | `backend/app/api/` | JSON routes for products, users, orders, search, sync, and health |
| Models | `backend/app/models/` | Pydantic request and response contracts |
| PostgreSQL access | `backend/app/repositories/orders_repo.py`, `outbox_repo.py` | Orders, users, snapshots, and outbox rows |
| MongoDB access | `backend/app/repositories/products_repo.py` | Product documents and catalog indexes |
| Elasticsearch access | `backend/app/repositories/search_repo.py`, `sync_service.py` | Search queries and order projection writes |
| Business workflow | `backend/app/services/` | Checkout, search orchestration, projection, and outbox draining |
| Background execution | `backend/app/workers/` | RabbitMQ-backed Celery tasks |
| Database definition | `backend/sql/001_schema.sql` | PostgreSQL tables, constraints, and triggers |
| Infrastructure | `docker-compose.yml`, `docker-compose.override.yml` | Stores, API, worker, beat, and frontend containers |
| Verification | `backend/tests/` | Real-store tests for contracts, transactions, sync, and isolation |

## What happens when one order is placed

Take `POST /api/orders` from the checkout screen:

1. Vue sends only `user_id`, product ids, and quantities. The client does not send trusted prices.
2. `backend/app/api/orders.py` passes the validated `OrderCreate` model to `order_service.place_order`.
3. The service reads the current products from MongoDB in one batch lookup.
4. Missing or inactive products are rejected before PostgreSQL is changed.
5. The service calculates the total with `Decimal`.
6. One PostgreSQL transaction inserts the order, immutable item snapshots, and an outbox event.
7. PostgreSQL commits before any background task is dispatched.
8. RabbitMQ carries the Celery task containing the order id and exact outbox id.
9. The worker reads the committed PostgreSQL order through `build_order_document()` and writes the projection to Elasticsearch.
10. The placement response says `sync_status: "QUEUED"`; `GET /api/sync/status/{order_id}` later compares PostgreSQL and Elasticsearch versions.

This means order detail can be correct before admin search catches up. That short window is intentional eventual consistency, not a second source of truth.

The bytes below zoom into these layers one at a time.

### Byte 1: The system in one request

**Builds on:** None

**In plain terms:**
The browser does not talk to one database that contains everything. A storefront request reads MongoDB. Checkout reads MongoDB for current product information and writes PostgreSQL. Admin order search reads Elasticsearch. Order detail reads PostgreSQL. A committed order is later projected into Elasticsearch in the background.

**The code:**
```text
Browser
  |
  v
Vue 3 + Vite or Nginx
  |
  v
FastAPI /api routes
  |             |                 |
  v             v                 v
MongoDB    PostgreSQL       Elasticsearch
catalog    orders/truth     admin search projection
                 |
                 v
          outbox -> RabbitMQ -> Celery -> Elasticsearch
```

```python
# backend/app/main.py
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(products.router, prefix="/api", tags=["products"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(orders.router, prefix="/api", tags=["orders"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(sync.router, prefix="/api", tags=["sync"])
```

**Why it matters:**
This is polyglot persistence: using more than one kind of database because the data and query problem differ. The important rule is not that three databases are automatically better. Each store has a named owner and a limited responsibility.

**Check yourself:**
- Which store is authoritative for an order total?
- Which store does the admin search endpoint read?
- Why can one order appear in PostgreSQL before it appears in Elasticsearch?

### Byte 2: Configuration and the implemented strategy

**Builds on:** Byte 1

**In plain terms:**
Settings are read from environment variables and optional `.env` values. The environment says `dual_write`, but this is not a switch between two implemented algorithms. It is a validation boundary: `polling` is rejected.

**The code:**
```python
# backend/app/core/settings.py
OrderSyncStrategy = Literal["dual_write"]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    order_sync_strategy: OrderSyncStrategy = "dual_write"
    pg_dsn: str = "postgresql://ecommerce:ecommerce@127.0.0.1:55432/ecommerce"
    mongo_dsn: str = "mongodb://127.0.0.1:27017"
    mongo_db_name: str = "ecommerce"
    es_url: str = "http://127.0.0.1:9200"
    es_orders_index: str = "orders"
    rabbitmq_url: str = "amqp://guest:guest@127.0.0.1:5672//"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

**Why it matters:**
`Literal["dual_write"]` means the runtime has one synchronization path. The approved design documents discuss polling as an alternative, but this repository does not contain the polling task, watermark table, or polling branch. Do not document those as features.

**Configuration sources:**
`.env.example` contains no real secrets. Compose uses service names such as `postgres:5432`; the native local defaults use `127.0.0.1:55432` for PostgreSQL because that local stack avoids a host PostgreSQL already using port 5432.

**Check yourself:**
- What happens if `ORDER_SYNC_STRATEGY=polling` is set?
- Which settings identify the four external services?
- Is the setting a real runtime choice between dual-write and polling? No.

### Byte 3: Starting the FastAPI application

**Builds on:** Bytes 1-2

**In plain terms:**
`main.py` creates the FastAPI app, enables CORS for the configured frontend origin, includes routers, checks the Elasticsearch index during startup, and closes clients during shutdown.

**The code:**
```python
# backend/app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.core.elasticsearch import ensure_orders_index
        await ensure_orders_index()
    except Exception:
        pass
    yield
    try:
        from app.core.elasticsearch import close_es
        from app.core.mongo import close_mongo
        from app.core.postgres import close_pool
        await close_es()
        await close_mongo()
        await close_pool()
    except Exception:
        pass
```

**Why it matters:**
The Elasticsearch startup check is best effort. Elasticsearch being down should not prevent PostgreSQL and MongoDB API work from starting. This is consistent with Elasticsearch being a rebuildable projection rather than the order authority.

**Check yourself:**
- Why is the ES startup check caught instead of making startup fail?
- Where are database clients closed?

### Byte 4: Docker topology and process boundaries

**Builds on:** Byte 3

**In plain terms:**
The base Compose file runs PostgreSQL, MongoDB, Elasticsearch, and RabbitMQ. The override adds the backend, Celery worker, Celery beat, and frontend. The infrastructure-only Compose file is for running FastAPI, Celery, and Vite on the host.

**The code:**
```yaml
# docker-compose.override.yml
backend:
  command: uvicorn app.main:app --host 0.0.0.0 --port 8000

celery-worker:
  command: celery -A app.workers.celery_app.celery_app worker --loglevel=info

celery-beat:
  command: celery -A app.workers.celery_app.celery_app beat --loglevel=info

frontend:
  build: ./frontend
  ports:
    - "5173:80"
```

**Why it matters:**
The API process, worker, and beat scheduler have different jobs and lifetimes. Beat periodically asks the outbox drain to run; the worker executes tasks. The frontend image is Nginx serving built static files and proxying `/api/`.

**Not present:**
There is no Redis result backend. There is no server-side HTML rendering. FastAPI returns JSON.

**Check yourself:**
- Which process serves HTTP API requests?
- Which process executes `index_order`?
- Which process schedules `drain_outbox`?

### Byte 5: The database ownership rule

**Builds on:** Bytes 1-4

**In plain terms:**
Database ownership means one store is the authoritative writer for a type of fact. It does not mean other stores can never contain a copy. It means a copy must not become a competing authority.

**The code:**
```python
# backend/app/api/products.py
"""Catalog routes. MongoDB only."""

# backend/app/api/orders.py
"""Order routes. PostgreSQL is the source of truth."""

# backend/app/api/search.py
"""Admin search route. Elasticsearch only."""

# backend/app/api/sync.py
"""Sync badge and maintenance routes. PG + ES reads, never MongoDB."""
```

**Why it matters:**
The data-source rule prevents accidental joins and dual ownership. Screen 3 must not fetch PostgreSQL orders and then call Elasticsearch search. It searches Elasticsearch. Screen 5 edits MongoDB products. Screen 4 reads PostgreSQL order detail.

**The structural boundary:**
The repository modules are `products_repo.py` for MongoDB, `orders_repo.py` and `outbox_repo.py` for PostgreSQL, and `search_repo.py` for Elasticsearch. `test_data_source_isolation.py` checks this boundary.

**Check yourself:**
- Where is the current product price authoritative?
- Where is the historical order-line price authoritative?
- Which screen should be stale during an Elasticsearch outage?

### Byte 6: PostgreSQL schema and relational ownership

**Builds on:** Byte 5

**In plain terms:**
PostgreSQL stores related rows with foreign keys and constraints. An order points to a user. Order items point to an order. Money uses a fixed-precision numeric type. The outbox sits in the same database so it can commit atomically with the order.

**The code:**
```sql
CREATE TABLE IF NOT EXISTS orders (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id),
  order_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
  status       TEXT NOT NULL CHECK (status IN ('PENDING','PROCESSING','SHIPPED')),
  total_amount NUMERIC(12,2) NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  version      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS order_items (
  id         BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL,
  title      TEXT NOT NULL,
  quantity   INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(12,2) NOT NULL
);
```

**Why it matters:**
The schema makes some business rules database rules: valid statuses, positive quantities, required relationships, and two-place monetary storage. PostgreSQL is not merely a place to dump JSON; it protects order history.

**Implementation detail:**
The backend uses `asyncpg` directly. There is no ORM and no migration framework in this repository. `backend/sql/001_schema.sql` is idempotent and is applied by the test fixture.

**Check yourself:**
- What happens to order items when an order is deleted?
- Which constraint prevents a zero quantity?
- Why is `total_amount` not a floating-point column?

### Byte 7: MongoDB document modeling for products

**Builds on:** Byte 5

**In plain terms:**
A product has fields that vary naturally: tags, a free-form attributes object, and an array of variants. MongoDB stores this as one document instead of forcing every possible attribute into columns.

**The code:**
```python
# backend/app/models/product.py
class Product(BaseModel):
    id: str = Field(alias="_id")
    sku: str
    title: str
    description: str
    price: Money
    category: str
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    variants: list[Variant] = Field(default_factory=list)
    active: bool = True
    updated_at: datetime
```

**Why it matters:**
The catalog is document-oriented because products can have different attributes such as `dpi`, `battery_hours`, or `ports`. `ProductCreate` requires at least one variant and one attribute so the project actually exercises that document shape.

**Repository boundary:**
`products_repo.py` converts MongoDB `ObjectId` to a string for the API and converts BSON `Decimal128` to Python `Decimal`. Other modules do not need to know BSON details.

**Check yourself:**
- Why does the model use `dict[str, Any]` for attributes?
- Which repository is allowed to import `bson`?
- Does the catalog document also own historical order titles? No.

### Byte 8: Elasticsearch as a search projection

**Builds on:** Bytes 5-7

**In plain terms:**
Elasticsearch is optimized for the admin search workload: partial text matching, status facets, date and price filters, and revenue aggregation. It is a projection, meaning a derived read model made from authoritative PostgreSQL data.

**The code:**
```json
// backend/app/search/orders_mapping.json
{
  "properties": {
    "order_id": { "type": "long" },
    "order_date": { "type": "date" },
    "status": { "type": "keyword" },
    "total_amount": { "type": "scaled_float", "scaling_factor": 100 },
    "updated_at": { "type": "date" },
    "version": { "type": "integer" },
    "items": {
      "type": "object",
      "properties": {
        "product_id": { "type": "keyword" },
        "title": { "type": "text" },
        "quantity": { "type": "integer" },
        "unit_price": { "type": "scaled_float", "scaling_factor": 100 }
      }
    }
  }
}
```

**Why it matters:**
The index can be deleted and rebuilt from PostgreSQL. That is the defining difference between a projection and a source of truth. If Elasticsearch is unavailable, committed orders are still in PostgreSQL and pending outbox rows record the work still needed.

**Search-specific features:**
The mapping uses `keyword` for exact status filtering, `scaled_float(100)` for cents, and edge n-grams for the `customer.name` and `items.title` prefix fields. `items` is an `object`, not a `nested` field, because that is the mapping implemented here.

**Check yourself:**
- Can Elasticsearch be the only copy of an order? No.
- Why is `status` a keyword?
- What does `scaled_float` protect in this mapping?

### Byte 9: Money at every boundary

**Builds on:** Bytes 6-8

**In plain terms:**
Money must not become a JavaScript or Python binary float. The project carries money as `Decimal` in Python, `NUMERIC(12,2)` in PostgreSQL, BSON `Decimal128` in MongoDB, `scaled_float(100)` in Elasticsearch, and a JSON string at the HTTP boundary.

**The code:**
```python
# backend/app/models/_money.py
CENTS = Decimal("0.01")

def quantize(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)

def to_money_str(value: Decimal) -> str:
    return format(quantize(value), "f")

Money = Annotated[
    Decimal,
    PlainSerializer(to_money_str, return_type=str, when_used="json"),
]
```

**Why it matters:**
`Decimal("0.10") * 3` stays `0.30`. The API serializes that value as the string `"0.30"`, so JavaScript does not parse a price into an imprecise binary number before displaying it.

**Boundary ownership:**
`products_repo.py` owns `Decimal128` conversion. `sync_service.py` formats PostgreSQL numeric values for the Elasticsearch document. `search_repo.py` converts Elasticsearch money back to `Decimal` before Pydantic serializes the response.

**Check yourself:**
- What does Screen 3 receive for a two-place amount?
- Why is the same money rule needed on both PG and ES paths?
- Where is BSON-specific conversion kept?

### Byte 10: The client order contract

**Builds on:** Bytes 6 and 9

**In plain terms:**
The client sends a user id and product ids with quantities. It does not send a trusted product title or price. The server reads those from MongoDB.

**The code:**
```python
# backend/app/models/order.py
class OrderItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str
    quantity: int = Field(gt=0)

class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    items: list[OrderItemIn] = Field(min_length=1)
```

```python
class OrderOut(BaseModel):
    order_id: int
    total_amount: Money
    status: OrderStatus
    sync_status: Literal["QUEUED"]
```

**Why it matters:**
Accepting a client-supplied price would let the client change the charge while still pretending the catalog was consulted. The server computes the total from current MongoDB catalog values, then writes the result to PostgreSQL.

**Check yourself:**
- Where does the order price come from?
- What does `extra="forbid"` reject?
- Why does a placement response never claim `IN_SYNC`?

### Byte 11: Checkout resolves catalog data before PostgreSQL

**Builds on:** Bytes 5, 7, and 10

**In plain terms:**
Checkout first batches product lookup in MongoDB. Missing or inactive products are rejected before a PostgreSQL transaction starts. This avoids creating partial order data for an invalid cart.

**The code:**
```python
# backend/app/services/order_service.py
async def _resolve_lines(req: OrderCreate) -> list[tuple[str, str, int, Decimal]]:
    wanted: dict[str, int] = {}
    for item in req.items:
        wanted[item.product_id] = wanted.get(item.product_id, 0) + item.quantity

    products = await (await _get_products_repo()).get_many_by_ids(list(wanted))
    missing = [pid for pid in wanted if pid not in products]
    inactive = [products[pid].title for pid in wanted
                if pid in products and not products[pid].active]
    if missing or inactive:
        raise HTTPException(status_code=409, detail="...")

    return [
        (pid, products[pid].title, quantity, products[pid].price)
        for pid, quantity in wanted.items()
    ]
```

**Why it matters:**
The lookup is one MongoDB `$in` query rather than one query per cart line. Duplicate lines for the same product are merged before the order item rows are written.

**Check yourself:**
- Why must inactive products be rejected before the transaction?
- Why are duplicate cart lines merged?
- Does this function update MongoDB? No.

### Byte 12: PostgreSQL transactions and atomic order placement

**Builds on:** Bytes 6 and 11

**In plain terms:**
A PostgreSQL transaction is an all-or-nothing group of writes. In this project, the order row, all item rows, and the outbox event commit together or roll back together.

**The code:**
```python
# backend/app/services/order_service.py
total = quantize(sum(
    (price * qty for _, _, qty, price in lines), Decimal("0")
))

async with pool.acquire() as conn:
    if not await orders_repo.user_exists(conn, req.user_id):
        raise HTTPException(status_code=404, detail=f"user {req.user_id} not found")

    async with conn.transaction():
        order_id = await orders_repo.insert_order(conn, req.user_id, total)
        await orders_repo.insert_order_items(conn, order_id, [...])
        outbox_id = await orders_repo.insert_outbox_event(
            conn, order_id, ORDER_CREATED
        )
```

**Why it matters:**
Without the transaction, a process failure could leave an order without its items or without its synchronization intent. With it, “the order committed” and “the event exists to request indexing” are one database fact.

**Important timing rule:**
The task is dispatched only after the transaction exits successfully. A worker must not try to project an order before that order is committed and visible.

**Check yourself:**
- What rolls back if `insert_order_items` fails?
- Why is dispatch after `async with conn.transaction()`?
- Is the Elasticsearch write part of the PostgreSQL transaction? No.

### Byte 13: Order-item snapshots preserve history

**Builds on:** Bytes 7 and 12

**In plain terms:**
At checkout, the current MongoDB title and price are copied into `order_items`. These are snapshots: facts about what was sold at that moment, not pointers to today’s catalog.

**The code:**
```sql
CREATE OR REPLACE FUNCTION order_items_snapshot_immutable() RETURNS trigger AS $$
BEGIN
  IF NEW.title IS DISTINCT FROM OLD.title
     OR NEW.unit_price IS DISTINCT FROM OLD.unit_price THEN
    RAISE EXCEPTION
      'order_items snapshot is immutable: title and unit_price are captured at checkout'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
```

```python
# backend/app/services/sync_service.py
async def build_order_document(conn: asyncpg.Connection, order_id: int):
    # The implementation reads the order, customer, and order_items from PG.
    # It never reads MongoDB.
```

**Why it matters:**
If a catalog editor renames `Wireless Mouse` to `Wireless Mouse Pro` or changes `50.16` to `79.00`, an old invoice must not change. The SQL trigger protects this even from a future code path that tries to rewrite the snapshot.

**Check yourself:**
- Where is a product title copied during checkout?
- Why must the canonical projection read order items from PostgreSQL?
- What prevents later item-title updates?

### Byte 14: The outbox pattern

**Builds on:** Byte 12

**In plain terms:**
The outbox is a durable list of “this committed order needs indexing” records. It solves the gap between a successful PostgreSQL commit and an unavailable message broker.

**The code:**
```sql
CREATE TABLE IF NOT EXISTS outbox (
  id           BIGSERIAL PRIMARY KEY,
  aggregate_id BIGINT NOT NULL,
  event_type   TEXT NOT NULL CHECK (
    event_type IN ('ORDER_CREATED','ORDER_STATUS_CHANGED')
  ),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT
);
```

```python
# backend/app/repositories/outbox_repo.py
async def enqueue(conn, aggregate_id: int, event_type: str) -> int:
    return await conn.fetchval(
        "INSERT INTO outbox (aggregate_id, event_type) VALUES ($1, $2) RETURNING id",
        aggregate_id,
        event_type,
    )
```

**Why it matters:**
RabbitMQ is a transport, not the durable business record. If RabbitMQ is down after PostgreSQL commits, the outbox row remains. Beat or the manual drain can retry it later.

**Exact event identity:**
The event id is sent with the order id. Completion updates `WHERE id = $1 AND processed_at IS NULL`, so one event cannot accidentally settle a sibling event for the same order.

**Check yourself:**
- When is the outbox row written?
- What is the difference between `aggregate_id` and the outbox row `id`?
- Why is `processed_at` also used as a compare-and-set guard?

### Byte 15: RabbitMQ is transport; Celery is execution

**Builds on:** Byte 14

**In plain terms:**
RabbitMQ carries the message. Celery provides the task abstraction and worker process that runs the Python function. They are infrastructure around the synchronization work, not alternate sources of truth.

**The code:**
```python
# backend/app/workers/celery_app.py
app = Celery(
    "ecommerce",
    broker=settings.rabbitmq_url,
    include=["app.workers.tasks"],
)
app.conf.update(
    task_acks_late=True,
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "drain-outbox": {
            "task": "app.workers.tasks.drain_outbox",
            "schedule": 15.0,
        },
    },
)
```

```python
# backend/app/workers/tasks.py
@celery_app.task(name="app.workers.tasks.index_order", acks_late=True,
                 ignore_result=True)
def index_order(order_id: int, outbox_id: int | None = None) -> None:
    _run(sync_service.index_order(order_id, outbox_id))
```

**Why it matters:**
The worker can be stopped without losing the committed order. The outbox remains the recovery record. There is no Celery result backend in this project because the result is represented by the Elasticsearch document and outbox state, not by a task return value.

**Eventual consistency:**
PostgreSQL and Elasticsearch are not updated at the same instant. After commit, there is a short window where order detail is current but admin search is missing or older. The `QUEUED` placement status and sync-status endpoint expose that reality instead of hiding it.

**Check yourself:**
- What does RabbitMQ do?
- What does the Celery worker do?
- Where is failed synchronization remembered?

### Byte 16: The canonical projection

**Builds on:** Bytes 8, 13-15

**In plain terms:**
A canonical projection is one function that defines how a PostgreSQL order becomes an Elasticsearch document. Every sync path should use the same function so index shape and snapshot behavior cannot drift.

**The code:**
```python
# backend/app/services/sync_service.py
async def build_order_document(conn: asyncpg.Connection, order_id: int) -> dict[str, Any]:
    row = await conn.fetchrow(
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
    # The function then reads order_items and builds the ES document.
```

```python
async def index_order(order_id: int, outbox_id: int | None = None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await build_order_document(conn, order_id)
    await es.index(
        index=get_settings().es_orders_index,
        id=str(order_id),
        document=doc,
        version=doc["version"],
        version_type="external",
    )
```

**Why it matters:**
The projection reads committed PostgreSQL order rows, customer data, and immutable item snapshots. It never looks up the live MongoDB product. Reindexing and normal event processing therefore produce the same document shape.

**Check yourself:**
- What is the single source for an indexed item title?
- Why should reindexing call the same projection?
- Is the projection a live MongoDB join? No.

### Byte 17: Versioning and stale-write protection

**Builds on:** Bytes 6, 15, and 16

**In plain terms:**
Every order starts at version 1. The database trigger increments the version on every update. Elasticsearch receives that PostgreSQL version as an external version. An older worker result cannot overwrite a newer indexed document.

**The code:**
```sql
CREATE OR REPLACE FUNCTION orders_touch() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  NEW.version := OLD.version + 1;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER orders_touch_trg BEFORE UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION orders_touch();
```

```python
# backend/app/repositories/orders_repo.py
updated = await conn.execute(
    "UPDATE orders SET status = $3 WHERE id = $1 AND version = $2",
    order_id,
    expected_version,
    status,
)
```

**Why it matters:**
There are two related protections. PostgreSQL rejects a status update made from a stale `expected_version`. Elasticsearch rejects a projection whose external version is older than the stored document. The database owns version increments so every update path follows the rule.

**Terminal versus retryable:**
An Elasticsearch version conflict is terminal for that old event: a newer version already won. An Elasticsearch outage is retryable, so the outbox records the error and the event remains eligible until the retry limit is reached.

**Check yourself:**
- Who increments `version`?
- What status code represents a stale API status update? `409`.
- Should a stale ES write be retried forever? No.

### Byte 18: Admin search and aggregations

**Builds on:** Bytes 8, 9, and 16

**In plain terms:**
The admin search endpoint sends a complex search body to Elasticsearch. It combines optional text search with status, date, and total-price filters. Revenue and status facets are aggregations over all matching documents, not just the current page.

**The code:**
```python
# backend/app/repositories/search_repo.py
body = {
    "query": {"bool": {"must": must, "filter": filters}},
    "aggs": {
        "orders_revenue": {"sum": {"field": "total_amount"}},
        "orders_by_status": {"terms": {"field": "status"}},
    },
    "from": (req.page - 1) * req.size,
    "size": req.size,
    "sort": [{"order_date": "desc"}],
}
res = await es.search(index=get_settings().es_orders_index, **body)
```

```python
# backend/app/services/search_service.py
if req.q:
    must.append({
        "multi_match": {
            "query": req.q,
            "fields": [
                "customer.name^2",
                "items.title.prefix",
                "items.title",
                "customer.email",
            ],
        }
    })
```

**Why it matters:**
The admin screen needs partial text such as `Wir` matching `Wireless Mouse`, plus faceting and filtered revenue. The response does not calculate revenue by summing returned hits because a page is only a slice of the filtered result set.

**Not present:**
The search query does not include `order_id` in its `multi_match` fields. Exact order lookup is still supported by the `order_id` stored in each hit and by the detail route.

**Check yourself:**
- Which data source does `POST /api/search/orders` use?
- Why are aggregations siblings of `size`?
- What does the `^2` on `customer.name` do? It boosts that field.

### Byte 19: Order status changes are guarded writes

**Builds on:** Bytes 12, 15, and 17

**In plain terms:**
The admin detail screen can change an order from `PENDING` to `PROCESSING` or `SHIPPED`, but it must state the version it last read. The update commits in PostgreSQL, creates an outbox event, and then queues re-indexing.

**The code:**
```python
# backend/app/api/orders.py
@router.patch("/orders/{order_id}/status", response_model=OrderOut)
async def patch_status(order_id: int, req: StatusUpdate) -> OrderOut:
    from app.services import order_service
    return await order_service.update_status(
        order_id, req.status, req.expected_version
    )
```

```python
# backend/app/models/order.py
class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: OrderStatus
    expected_version: int = Field(ge=1)
```

**Why it matters:**
If two admin users read version 1 and one changes the order first, the second user must not overwrite that change using stale information. The second request gets `409` and must re-read.

**Data flow:**
`PATCH -> guarded PG UPDATE -> trigger version bump -> outbox insert -> commit -> dispatch -> projection -> ES version update`.

**Check yourself:**
- What protects a concurrent status update?
- Does the status route write Elasticsearch first? No.
- Does changing status rewrite item snapshots? No.

### Byte 20: Synchronization status is a comparison, not a promise

**Builds on:** Bytes 14-17

**In plain terms:**
`POST /api/orders` reports `QUEUED` because it returns before the worker runs. `GET /api/sync/status/{order_id}` checks reality by comparing the PostgreSQL version with the Elasticsearch version and inspecting pending outbox errors.

**The code:**
```python
# backend/app/models/sync.py
SyncState = Literal["IN_SYNC", "OUT_OF_SYNC", "MISSING_IN_ES"]

class SyncStatusOut(BaseModel):
    order_id: int
    state: SyncState
    pg_version: int
    es_version: int | None = None
    pending_outbox_events: int = 0
    last_error: str | None = None
```

```python
# backend/app/api/sync.py
if es_version is None:
    state = MISSING_IN_ES
elif es_version == row["version"]:
    state = IN_SYNC
else:
    state = OUT_OF_SYNC
```

**Why it matters:**
The two vocabularies are intentionally separate. `QUEUED` describes a placement response. `IN_SYNC`, `OUT_OF_SYNC`, and `MISSING_IN_ES` describe a comparison after looking at both systems.

**Check yourself:**
- When can `MISSING_IN_ES` be normal?
- Where does the pending error come from?
- Can the create response honestly say `IN_SYNC`? No.

### Byte 21: Reindexing and repair

**Builds on:** Bytes 16 and 20

**In plain terms:**
Because Elasticsearch is derived, the project has a repair path that deletes and recreates the `orders` index, then projects every PostgreSQL order again.

**The code:**
```python
# backend/app/api/sync.py
@router.post("/sync/reindex")
async def reindex() -> dict[str, int]:
    es = await get_es()
    index = get_settings().es_orders_index
    if await es.indices.exists(index=index):
        await es.indices.delete(index=index)
    await ensure_orders_index()
    pool = await get_pool()
    async with pool.acquire() as conn:
        oids = await orders_repo.list_order_ids(conn)
    for oid in oids:
        await sync_service.index_order(oid, None)
    return {"indexed": len(oids)}
```

**Why it matters:**
Repair is possible precisely because PostgreSQL is the source of truth and `build_order_document()` is canonical. A projection may be stale or empty without destroying the business record.

**Other maintenance route:**
`POST /api/sync/drain-outbox` retries pending outbox events without deleting the index.

**Check yourself:**
- What is the input to a full reindex?
- Does reindex read MongoDB product titles for old orders? No.
- What is the difference between reindex and drain-outbox?

### Byte 22: The frontend application and route ownership

**Builds on:** Bytes 1, 4, and 5

**In plain terms:**
The frontend is a Vue 3 single-page application. `main.js` installs Pinia and Vue Router. Route metadata requires a session and distinguishes user routes from admin routes.

**The code:**
```javascript
// frontend/src/main.js
createApp(App).use(createPinia()).use(router).mount('#app')
```

```javascript
// frontend/src/router.js
{ path: '/', component: () => import('./views/StorefrontView.vue'),
  meta: { role: 'user' } },
{ path: '/checkout', component: () => import('./views/CheckoutView.vue'),
  meta: { role: 'user' } },
{ path: '/admin/orders', component: () => import('./views/AdminSearchView.vue'),
  meta: { role: 'admin' } },
{ path: '/admin/orders/:id', component: () => import('./views/OrderDetailView.vue'),
  meta: { role: 'admin' } },
{ path: '/admin/catalog', component: () => import('./views/CatalogAdminView.vue'),
  meta: { role: 'admin' } }
```

**Why it matters:**
The views make the data-source rule visible to a user:

- `/` reads products from MongoDB.
- `/checkout` posts an order to PostgreSQL-backed API logic.
- `/admin/orders` searches Elasticsearch only.
- `/admin/orders/:id` reads PostgreSQL order detail.
- `/admin/catalog` edits MongoDB products only.

**Check yourself:**
- Which route demonstrates the search projection?
- Which route can edit the product catalog?
- Where is cart state held before checkout?

### Byte 23: The cart is client-side state; checkout is server authority

**Builds on:** Bytes 10-12 and 22

**In plain terms:**
The Pinia cart stores product ids, quantities, and display hints in the browser. It does not calculate or persist the authoritative order total. The server recalculates from MongoDB during checkout.

**The code:**
```javascript
// frontend/src/stores/cart.js
export const useCart = defineStore('cart', {
  state: () => ({ lines: [] }),
  actions: {
    add(productId, qty = 1, title = '', category = '') {
      const line = this.lines.find((l) => l.product_id === productId)
      if (line) line.quantity += qty
      else this.lines.push({ product_id: productId, quantity: qty, title, category })
    },
    clear() {
      this.lines = []
    }
  }
})
```

```javascript
// frontend/src/api/orders.js
export async function placeOrder(payload) {
  const r = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!r.ok) throw new Error((await r.json()).detail || 'order failed')
  return r.json()
}
```

**Why it matters:**
Browser state is convenient UI state, not a trust boundary. A client can change it. PostgreSQL receives only validated product ids and quantities, while MongoDB supplies title and price.

**Check yourself:**
- Is the cart total authoritative? No.
- Where does checkout obtain the actual price?
- What happens to the cart after the user leaves the browser? It is not a backend cart in this implementation.

### Byte 24: Product CRUD and catalog validation

**Builds on:** Bytes 7 and 22

**In plain terms:**
The catalog admin can list, create, update, and view products. Product creation requires a non-empty attributes object and at least one variant. SKU uniqueness is enforced by a MongoDB index and translated into HTTP 409.

**The code:**
```python
# backend/app/models/product.py
@model_validator(mode="after")
def _require_document_shape(self) -> ProductCreate:
    if not self.variants:
        raise ValueError("a product must have at least one variant")
    if not self.attributes:
        raise ValueError("a product must have at least one attribute")
    return self
```

```python
# backend/app/repositories/products_repo.py
await self._col.create_index("sku", unique=True, name="sku_unique")
await self._col.create_index(
    [("category", 1), ("active", 1)], name="category_active"
)
await self._col.create_index("tags", name="tags_idx")
```

**Why it matters:**
The Mongo repository owns BSON conversion, indexes, catalog filtering, and CRUD. The order path uses it only to resolve current products; it never asks it to rewrite historical orders.

**Not present:**
There is no MongoDB copy of orders and no product-to-PostgreSQL synchronization path.

**Check yourself:**
- What makes SKU unique?
- Why does `ProductCreate` reject an empty attributes object?
- Which store does catalog update modify?

### Byte 25: Deterministic seed data

**Builds on:** Bytes 6-9 and 13

**In plain terms:**
The seed script creates a predictable demonstration dataset: 8 users, 25 products, 40 orders, and approximately 85 item rows. It uses a fixed random seed and an anchor date so the order plan can be reproduced.

**The code:**
```python
# backend/scripts/seed.py
ANCHOR_DEFAULT = "2026-09-30T00:00:00Z"

def build_order_plan(seed: int, anchor_date: str) -> dict:
    rng = random.Random(seed)
    anchor = _parse_anchor(anchor_date)
    statuses = (["PENDING"] * 14 + ["PROCESSING"] * 13 + ["SHIPPED"] * 13)
    rng.shuffle(statuses)
    # The function creates 40 order slots using only this local RNG.
```

```python
# backend/scripts/seed.py
total_amount = quantize(sum(
    (price * quantity for _, _, quantity, price in lines), Decimal("0")
))
```

**Why it matters:**
`build_order_plan()` is a pure planning function: no database and no current clock. `test_seed_determinism.py` checks repeatability. The seed also creates a deliberate catalog/history mismatch: the live MongoDB product can be renamed or repriced while historical PostgreSQL snapshots remain unchanged.

**Important scope note:**
The seed uses `datetime.now(timezone.utc)` for product `updated_at` fields when writing product documents. The order plan itself is anchored and deterministic. Do not claim that every byte of every store document is timestamp-identical across runs.

**Check yourself:**
- What makes the order plan repeatable?
- Are order totals generated randomly? No, they are calculated from item lines.
- Which data demonstrates snapshot preservation?

### Byte 26: Failure behavior and eventual consistency

**Builds on:** Bytes 12-21

**In plain terms:**
If Elasticsearch is down, an order can still commit to PostgreSQL. The outbox event remains pending, attempts and the last error are recorded, and a later drain can retry. During this time, PostgreSQL-backed order detail is correct while Elasticsearch-backed search may be stale.

**The code:**
```python
# backend/app/repositories/outbox_repo.py
MAX_ATTEMPTS = 5

async def mark_failed(conn, outbox_id: int, error: str) -> bool:
    return await conn.fetchrow(
        """
        UPDATE outbox
        SET attempts = attempts + 1,
            last_error = $2,
            processed_at = CASE
                WHEN attempts + 1 >= $3 THEN now()
                ELSE processed_at
            END
        WHERE id = $1 AND processed_at IS NULL
        RETURNING id
        """,
        outbox_id, error, MAX_ATTEMPTS,
    ) is not None
```

**Why it matters:**
This is eventual consistency with an explicit recovery record. “Eventually consistent” does not mean “randomly inconsistent.” It means the systems have a known asynchronous path, a pending event, retry state, and a repair endpoint.

**Failure categories:**

- PostgreSQL failure prevents the order transaction from committing.
- MongoDB failure prevents catalog lookup and therefore prevents checkout.
- RabbitMQ failure can leave a committed outbox row for later drain.
- Elasticsearch failure leaves order detail available but search stale.
- A stale Elasticsearch version is terminal because a newer version already won.

**Check yourself:**
- What is lost when Elasticsearch is temporarily down? Search freshness, not the committed order.
- What records the retry error?
- Which endpoint can force a full rebuild?

### Byte 27: The API surface and status meanings

**Builds on:** Bytes 3, 10, 18, and 20

**In plain terms:**
The backend exposes JSON routes grouped by responsibility. Response models make the public contract explicit, including money serialization.

**The code:**
```text
GET    /api/health
GET    /api/users
GET    /api/products
GET    /api/products/{product_id}
POST   /api/products
PUT    /api/products/{product_id}
POST   /api/orders                 201
GET    /api/orders/{order_id}
PATCH  /api/orders/{order_id}/status
POST   /api/search/orders
GET    /api/sync/status/{order_id}
POST   /api/sync/drain-outbox
POST   /api/sync/reindex
```

**Why it matters:**
HTTP status codes describe different classes of failure. Validation errors are rejected by Pydantic, missing resources use 404, stale status updates and duplicate catalog conditions use 409, and successful order creation returns 201 with `sync_status: QUEUED`.

**Health behavior:**
`GET /api/health` reports `UP` or `DOWN` separately for PostgreSQL, MongoDB, and Elasticsearch and does not raise when one is unavailable. This is a liveness report, not a claim that all user workflows will work.

**Check yourself:**
- Which route returns the source-of-truth order detail?
- Which route reports whether ES matches the PostgreSQL version?
- Does health include RabbitMQ? No, the implementation checks PostgreSQL, MongoDB, and Elasticsearch.

### Byte 28: How the tests prove the architecture

**Builds on:** All previous bytes

**In plain terms:**
The backend tests use real store clients configured in `tests/conftest.py`; they are not a fake in-memory architecture. Each test family protects a specific boundary.

**The code:**
```python
# backend/tests/conftest.py
@pytest_asyncio.fixture(scope="session")
async def _pg_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=get_settings().pg_dsn,
                                     min_size=1, max_size=10)
    if SCHEMA_SQL.exists():
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL.read_text())
    yield pool
    await pool.close()
```

**Tests to read by concept:**

- `test_models_money.py`: Decimal and JSON string money contract.
- `test_products_repo.py`: Mongo CRUD, Decimal128 conversion, and no order data in Mongo.
- `test_order_placement.py`: catalog validation first, exact totals, snapshots, rollback, and dispatch after commit.
- `test_orders_touch_trigger.py`: automatic `updated_at` and monotonic `version`.
- `test_outbox_repo.py`: pending, claim, retry, terminal failure, idempotent settlement, and exact event identity.
- `test_sync_projection.py`: canonical PostgreSQL-to-ES document shape.
- `test_sync_tasks.py`: task behavior, retries, and stale-version handling.
- `test_search.py`: partial text, filters, pagination, facets, and revenue over all filtered hits.
- `test_data_source_isolation.py`: route/service import boundaries.
- `test_seed_determinism.py`: repeatable pure order planning.
- `test_api_slice.py` and `test_sync_api.py`: HTTP routes, response models, status codes, and sync reporting.

**Why it matters:**
The tests are not only checking that endpoints return JSON. They check the architecture’s failure modes: catalog edits must not rewrite history, stale writes must not clobber newer search documents, money must remain exact, and screen data sources must stay isolated.

**Check yourself:**
- Which test would catch a live MongoDB lookup inside the projection?
- Which test would catch a forgotten version bump?
- Which test protects Screen 3 from accidentally importing PostgreSQL repositories?

### Byte 29: What this project deliberately does not implement

**Builds on:** Bytes 2, 5, 8, and 28

**In plain terms:**
Knowing what is absent is part of reading a real codebase correctly. A design document may discuss alternatives, but only source code defines shipped behavior.

**The code:**
```python
# backend/app/core/settings.py
OrderSyncStrategy = Literal["dual_write"]
```

**Not present in this implementation:**

- No polling synchronization strategy.
- No `sync_state` watermark table or polling task.
- No synchronous inline Elasticsearch write during checkout.
- No authentication or authorization backend; the frontend session and role guard are client-side behavior.
- No payments, inventory decrementing, multi-currency, or i18n.
- No ORM; SQL access is through `asyncpg`.
- No Elasticsearch alias-swap reindex flow; the index is literally named `orders`.
- No server-side HTML templates.
- No Redis result backend.
- No product copy in PostgreSQL and no order copy in MongoDB.

**Why it matters:**
A beginner often fills gaps with familiar framework features. Here, that would produce false documentation. “Not present” is a useful answer when tracing a bug or planning a change.

**Check yourself:**
- Is `ORDER_SYNC_STRATEGY=polling` a supported deployment mode? No.
- Is the frontend’s client-side role guard a server security boundary? No.
- Can you add a database feature to the documentation without finding its implementation? No.

### Byte 30: A practical way to trace a change

**Builds on:** All previous bytes

**In plain terms:**
When changing this project, start at the behavior the user sees and follow ownership inward. For a new checkout field, inspect the Vue payload, Pydantic model, order service, PostgreSQL schema, projection, search model, and tests. For a new catalog field, inspect the MongoDB model and repository and the catalog views; do not add it to PostgreSQL unless ownership truly changes.

**The code:**
```text
Browser view
  -> frontend/src/api/*.js
  -> backend/app/api/*.py
  -> backend/app/models/*.py
  -> backend/app/services/*.py
  -> backend/app/repositories/*.py
  -> owning store
  -> focused backend test
```

**Why it matters:**
The safest change preserves the existing data-source and transaction boundaries. If a change touches an order write, ask whether it belongs inside the PostgreSQL transaction and whether an outbox event is needed. If it changes an indexed field, update the canonical projection, mapping, search model, and the projection/search tests together.

**A useful reading order:**

1. Read `README.md` for the short run and demo path.
2. Read Bytes 1-9 for ownership and storage concepts.
3. Read Bytes 10-21 for checkout, transactions, snapshots, outbox, workers, projection, and synchronization.
4. Read Bytes 22-27 for browser routes and HTTP contracts.
5. Read Bytes 28-30 before modifying behavior.

**Check yourself:**
- Which layer owns a transaction boundary?
- Which function defines an indexed order document?
- Which test should be added before changing a cross-store contract?
