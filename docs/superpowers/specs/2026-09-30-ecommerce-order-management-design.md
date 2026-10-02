# E-Commerce Order Management & Search Service — Design Specification

**Path:** `docs/superpowers/specs/2026-09-30-ecommerce-order-management-design.md`
**Status:** approved in conversation, written to disk for review
**Source of truth:** `docs/ecommerce-postgres-mongo-es.pdf`

## 1. Purpose and scope

A proof-of-concept e-commerce system demonstrating correct use of three stores, each for the job it does best:

- **PostgreSQL** — orders, written under a real database transaction. Source of truth for money and fulfillment.
- **MongoDB** — the product catalog. Schema-flexible documents with sparse attributes and variant arrays.
- **Elasticsearch** — a back-office order search dashboard: omni-search, faceted filters, and KPI aggregations.

The graded outcome is not the feature set but the **wiring**: which screen reads which store, and how the order sync survives failure. Scope is one coherent system and is not decomposed into sub-projects.

### 1.1 Decisions locked with the human partner

| Decision | Choice |
|---|---|
| Synchronization strategies | **A (dual-write)** and **B (periodic polling)**, both implemented and compared |
| Async infrastructure | RabbitMQ + Celery, as transport and execution |
| Outbox | Durability mechanism **inside Strategy A only** |
| Tests | Backend-only pytest, **including `test_seed_determinism.py`** |
| Run topology | Stores in Docker; FastAPI, Vite, and Celery on the host |
| Storefront text search | **Not built.** Screen 1 filtering is category/attribute only, per the assignment |
| `Makefile` | **Kept** as a developer and demo convenience; no architectural effect |

### 1.2 Non-goals

Authentication, payments, inventory decrementing, multi-currency, i18n, and horizontal scaling beyond a single Celery worker. Alias-swap reindexing is recorded in `NOTES.md` as a production consideration rather than built, because the assignment asks for an index literally named `orders`.

**Explicit limitation:** `order_id` is mapped as `long` for exact lookup from Screen 3 to Screen 4, but is **not** part of the Screen 3 omni-search `multi_match`, so typing an order number into the search bar returns no results. The assignment's demo script requires only partial product title and customer name, so this is in-spec; it is stated here so a reviewer is not surprised.

**Explicit constraint restated:** no jQuery, and no server-side HTML templating for Screens 1–5. All five screens are Vue components rendered client-side; the FastAPI process serves JSON only and never returns HTML.

## 2. Strategy A framing

- Strategy A **is** the assignment's dual-write option, implemented with the Elasticsearch write dispatched asynchronously: `PostgreSQL COMMIT → RabbitMQ → Celery worker → Elasticsearch`.
- **This creates a short eventual-consistency window** between PostgreSQL and Elasticsearch, on the order of one second, bounded by the broker round-trip, task execution, and the index's `refresh_interval` of 1s. During it, Screen 4 shows the order and Screen 3 does not. This is designed behavior, not a defect.
- **Dual-write is the strategy. RabbitMQ is transport. Celery is execution. The outbox is durability.** None of the latter three is a synchronization strategy.
- We chose the asynchronous form over the assignment's literal synchronous "then immediately indexes" for four reasons:
  1. **It is the direct answer to the question the assignment itself poses** — "what if Elasticsearch times out after Postgres already committed?" With a synchronous call, every checkout opens a connection to Elasticsearch and pays its latency and failure modes, so search-index degradation becomes order-placement degradation for reasons unrelated to the order. Decoupling them makes checkout depend on PostgreSQL alone.
  2. **It makes RabbitMQ and Celery load-bearing** rather than decorative infrastructure in the architecture.
  3. **What is given up is precisely bounded** — strong consistency at the instant the client receives `201`, in exchange for a ~1s window that is short, measured, and self-healing.
  4. **The window is observable** — via the `sync_status` field, the pending outbox row, and the Screen 4 badge.
- The synchronous inline variant is **not** a shipped code path. It is described in `NOTES.md` as `A-inline` and contrasted against our `A-queued` form with recorded latency numbers, so a reviewer can see what the queue bought and what it cost.
- This remains dual-write: one order, two stores, second write causally derived from the first. The queue changes *when* the Elasticsearch write lands, never *whether* it is requested.

## 3. The four concepts, separated

| Concept | Layer | Definition | A strategy? |
|---|---|---|---|
| **Synchronization strategy** | Policy | How an order change reaches Elasticsearch: `dual_write` or `polling`. | **Yes — these two are compared** |
| **RabbitMQ** | Transport | Carries `es.sync` messages producer→worker. Transient, at-least-once. | No |
| **Celery** | Execution | Runs sync work as background tasks on a beat schedule, with retries. | No |
| **Outbox** | Durability | PostgreSQL table of undelivered index intents, written in the order's own transaction. | No |

The outbox answers exactly one question Strategy A raises — if RabbitMQ is down at commit time, the event is gone — and is confined to Strategy A. Strategy B never writes to it, because B delivers no events: it reconciles from `updated_at` and cannot lose a change that `updated_at` records.

**Strategy switch:** `ORDER_SYNC_STRATEGY=dual_write | polling`. A single environment variable. Celery, RabbitMQ, the Elasticsearch mapping, all five screens, and the seed are identical under both.

## 4. Screens

| # | Screen | Route | Data source | Notes |
|---|---|---|---|---|
| 1 | Customer Storefront | `/` | **MongoDB** (products); PG for the user list only | The assignment permits users in PostgreSQL; the *product* rule is the hard one. `active:false` hidden. Cart in Pinia only, no backend. Filtering by category and attributes only. |
| 2 | Checkout | `/checkout` | **PostgreSQL** (write); MongoDB to validate price and title | The transactional boundary. Explicit commit success/failure notice. |
| 3 | Admin Search | `/admin/orders` | **Elasticsearch only** | Omni-search, facets, KPI cards. Never touches PostgreSQL or MongoDB. |
| 4 | Order Detail | `/admin/orders/:id` | **PostgreSQL** (read); PG + ES for the sync badge | Status toggle writes PG and triggers an ES update. |
| 5 | Catalog Admin | `/admin/catalog` | **MongoDB only** | List including inactive, create, edit. Editing proves snapshots do not move. |

The data-source rule is the assignment's real test, so it is enforced **structurally**: `repositories/` contains one module per store, and each screen's route may only import its declared repository. Not a convention — an import boundary a reviewer can check, covered by a test.

## 5. Vue frontend

Vue 3 with Vite, `<script setup>` Composition API, Vue Router 4, Pinia. No jQuery; no server-side templating.

```
frontend/
  package.json            install and run scripts (dev, build, preview)
  vite.config.js          dev server on :5173, proxy to :8000
  src/
    main.js               app bootstrap, router, Pinia
    App.vue               layout shell
    views/                StorefrontView, CheckoutView, AdminSearchView,
                          OrderDetailView, CatalogAdminView
    components/           ProductCard, ProductFilters, CartSummary,
                          OrderStatusSelect, SyncBadge, FacetSidebar, KpiCards,
                          OrderResultsTable, ProductForm
    stores/               cart, session, catalog, orders, search
    api/                  products.ts, orders.ts, search.ts, users.ts
    utils/                money.ts
```

`ProductForm` provides dedicated editors for the nested `attributes` object and the `variants` array, because Screen 5 must prove the catalog is genuinely document-oriented.

**Why five stores rather than one:** `search.ts` shares no code with `orders.ts`. A shared store would let someone later back Screen 3 with a PostgreSQL call and break the data-source rule invisibly. Separation is the enforcement mechanism.

**Why the frontend is strategy-agnostic:** it must render correctly under both strategies. The only observable difference is timing, surfaced through `sync_status` and the Screen 4 badge. No screen reads `ORDER_SYNC_STRATEGY`.

**Money crosses the wire as a JSON string** (`"50.16"`). Pydantic v2 serializes `Decimal` as a string, and `utils/money.ts` formats with `Intl.NumberFormat`. To guarantee this uniformly, `search_repo` converts Elasticsearch's `scaled_float` number back through `Decimal(...).quantize(Decimal("0.01"))` before the response model serializes it — see §10. JavaScript floating point never touches a total, and the same order renders identically on Screens 3 and 4.

## 6. FastAPI backend

Follows the assignment's suggested layout, extended for the async path.

```
backend/
  app/
    main.py                 app factory, routers, CORS, lifespan
    core/       settings.py, postgres.py, mongo.py, elasticsearch.py
    api/        products.py, orders.py, search.py, users.py, sync.py, health.py
    models/     product.py, order.py, search.py, user.py
    services/   order_service.py, search_service.py, sync_service.py, outbox_service.py
    repositories/ orders_repo.py, products_repo.py, search_repo.py,
                  users_repo.py, outbox_repo.py, sync_state_repo.py
    workers/    celery_app.py, tasks.py
    search/     orders_mapping.json
  sql/          001_schema.sql
  scripts/      seed.py, reindex_orders.py
  tests/
  requirements.txt
```

**Driver choice: `asyncpg` + `motor` + `AsyncElasticsearch`, no ORM.** The assignment warns against "an ORM as an excuse to skip explicit transaction boundaries." With asyncpg the boundary is literally `async with pool.acquire() as c: async with c.transaction():` — visible at the call site, which is the thing being graded. The MongoDB catalog is queried directly and is never mirrored into PostgreSQL.

`services/order_service.py` is the only module that opens the order transaction, and it is the only place the strategy branch exists.

## 7. PostgreSQL schema

```sql
CREATE TABLE users (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id),
  order_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
  status       TEXT NOT NULL CHECK (status IN ('PENDING','PROCESSING','SHIPPED')),
  total_amount NUMERIC(12,2) NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  version      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE order_items (
  id         BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL,           -- MongoDB ObjectId as text
  title      TEXT NOT NULL,           -- SNAPSHOT, immutable
  quantity   INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(12,2) NOT NULL   -- SNAPSHOT, immutable
);

-- Strategy A only; never written to under Strategy B
CREATE TABLE outbox (
  id           BIGSERIAL PRIMARY KEY,
  aggregate_id BIGINT NOT NULL,
  event_type   TEXT NOT NULL,   -- ORDER_CREATED | ORDER_STATUS_CHANGED
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT
);
CREATE INDEX ON outbox (created_at) WHERE processed_at IS NULL;

-- Strategy B only; never read under Strategy A
CREATE TABLE sync_state (
  id             SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_polled_at TIMESTAMPTZ            -- NULL means "never polled"
);

CREATE FUNCTION orders_touch() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  NEW.version    := OLD.version + 1;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER orders_touch_trg BEFORE UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION orders_touch();

CREATE INDEX ON orders (updated_at, id);   -- Strategy B's range scan
```

Both `outbox` and `sync_state` are created unconditionally, because they are cheap and it is more honest to show an empty `outbox` under Strategy B than to hide it behind a conditional migration.

**Why `version`:** timestamps compare unreliably — clock skew, same-millisecond writes. A monotonic counter gives the Screen 4 badge a truth test and lets both stores do optimistic concurrency.

**Why the trigger owns `updated_at` and `version`:** Strategy B's correctness rests entirely on `updated_at`. If any code path forgets to bump it, that change is invisible to the poller *permanently* — no error, no log, just a permanently wrong dashboard. A trigger makes that class of bug impossible rather than merely unlikely, and it gives Strategy A correct versions for free. A test asserts it.

## 8. MongoDB product documents

Exactly the assignment's shape, with `Decimal128` for price:

```json
{
  "_id": ObjectId("64f1a2b3c4d5e6f7a8b9c0d1"),
  "sku": "WM-001",
  "title": "Wireless Mouse",
  "description": "Ergonomic 2.4GHz mouse",
  "price": Decimal128("50.16"),
  "category": "peripherals",
  "tags": ["wireless", "usb", "office"],
  "attributes": { "color": "black", "dpi": 1600, "battery": "AA" },
  "variants": [
    { "sku": "WM-001-BLK", "color": "black", "stock": 40 },
    { "sku": "WM-001-WHT", "color": "white", "stock": 12 }
  ],
  "active": true,
  "updated_at": ISODate("2026-09-25T10:00:00Z")
}
```

Indexes: `sku` unique · `{category: 1, active: 1}` · `{tags: 1}`. **No text index** — storefront filtering is by category, attributes, and price only, as the assignment specifies.

**Every seeded product carries all ten fields**, including a non-empty `attributes` object and at least one `variants` entry. This is asserted by the seed's verification report, since Screen 5 exists to demonstrate that the catalog is genuinely document-oriented.

**Why `Decimal128`:** the catalog price is the *source* for order snapshots. Float drift there becomes wrong money in PostgreSQL. The one place we tolerate nothing is money.

## 9. Elasticsearch index and mapping

Index name `orders`. Document shape exactly as the assignment specifies, plus `version`:

```json
{
  "order_id": 1024,
  "order_date": "2026-07-09T19:00:00Z",
  "status": "PROCESSING",
  "total_amount": 150.50,
  "updated_at": "2026-07-09T19:05:00Z",
  "version": 1,
  "customer": { "id": 5, "name": "John Doe", "email": "john@example.com" },
  "items": [
    { "product_id": "64f1a2b3c4d5e6f7a8b9c0d1", "title": "Wireless Mouse",
      "quantity": 1, "unit_price": 50.16 }
  ]
}
```

| Field | Type | Rationale |
|---|---|---|
| `order_id` | `long` | exact lookup from Screen 3 → 4 |
| `order_date` | `date` | date-range filter |
| `status` | `keyword` | the status facet needs raw, unanalyzed values |
| `total_amount` | `scaled_float(100)` | exact cents for range filter and `sum` aggregation |
| `updated_at` | `date` | sync checks |
| `version` | `integer` | Screen 4 badge; external-version concurrency |
| `customer.id` | `long` | — |
| `customer.name` | `text` + `.keyword` + `.prefix` | analyzed matching, raw sorting, partial typing |
| `customer.email` | `keyword` | exact-match only |
| `items` | **`object`** | see below |
| `items.product_id` | `keyword` | exact |
| `items.title` | `text` + `.keyword` + `.prefix` | omni-search; raw for sorting |
| `items.quantity` | `integer` | — |
| `items.unit_price` | `scaled_float(100)` | display; future aggregations |

Settings: 1 shard, 0 replicas, `refresh_interval: 1s`, `xpack.security.enabled=false`, and a custom `autocomplete_index` analyzer (`standard` tokenizer plus `edge_ngram` 2–15) backing the `.prefix` subfields.

**Four deliberate mapping decisions:**

- **`object`, not `nested`.** `nested` costs a hidden Lucene document per line item and is required only when a query must match several fields *within the same item* ("title contains Mouse **and** quantity > 2"). Screen 3 never does that. `object` flattens `items.title` into a single field — exactly what `multi_match` wants — at a fraction of the index size and query cost.
- **`.prefix` n-gram subfields.** "Partial text" is an explicit requirement. A standard analyzer cannot match `Wir` → `Wireless`, because an inverted index stores whole tokens only. N-grams must be produced at index time; no query-time option recovers them.
- **`scaled_float(100)`, not `float`/`double`.** Summing revenue across 40+ orders in binary floating point produces a total that disagrees with PostgreSQL by a cent. The KPI card must be provably correct.
- **`keyword` for `status`.** The facet counts statuses; analyzing them would split or mangle the values.

## 10. API endpoints

| Method | Path | Store | Purpose |
|---|---|---|---|
| `GET` | `/api/products` | Mongo | `?category&tag&min_price&max_price&include_inactive` — no text search |
| `GET` | `/api/products/{id}` | Mongo | single product |
| `POST` | `/api/products` | Mongo | Screen 5 create |
| `PUT` | `/api/products/{id}` | Mongo | Screen 5 edit |
| `GET` | `/api/users` | PG | "Log In As" dropdown |
| `POST` | `/api/orders` | PG | the transactional boundary |
| `GET` | `/api/orders/{id}` | PG | Screen 4 read |
| `PATCH` | `/api/orders/{id}/status` | PG, plus ES trigger | Screen 4 status change |
| `POST` | `/api/search/orders` | **ES only** | `{q, statuses[], date_from, date_to, price_min, price_max, page, size}` |
| `GET` | `/api/sync/status/{order_id}` | PG + ES | badge state: `IN_SYNC` / `OUT_OF_SYNC` / `MISSING_IN_ES` |
| `POST` | `/api/sync/drain-outbox` | PG + ES | Strategy A manual drain |
| `POST` | `/api/sync/poll-once` | PG + ES | Strategy B manual poll |
| `POST` | `/api/sync/reset-watermark` | PG | sets `sync_state.last_polled_at` to NULL; Strategy B demo reset |
| `POST` | `/api/sync/reindex` | PG + ES | rebuild the index; same code path as `scripts/reindex_orders.py` |
| `GET` | `/api/health` | all | liveness of the three stores |

`POST /api/search/orders` is a POST because the body is a complex filter object, as the assignment specifies. Its query is `bool` → `must`: `multi_match` over `customer.name^2`, `items.title.prefix`, `items.title`, `customer.email`; plus `filter` clauses for `terms` on status and `range` on dates and price. Aggregations are a `sum` on `total_amount` and a `terms` on `status`, both scoped to the same filter set.

**Money serialization is uniform across every endpoint.** `search_repo` reads Elasticsearch's `scaled_float` result and re-quantizes it via `Decimal(...).quantize(Decimal("0.01"))`, so `total_amount` and `items[].unit_price` are emitted as JSON strings whether they originated in PostgreSQL or Elasticsearch. Without this, Screen 3 would render `$150.5` while Screen 4 rendered `$150.50` for the same order.

## 11. Order placement flow

```
POST /api/orders   { "user_id": 5, "items": [ { "product_id": "...", "quantity": 2 } ] }
```

**The client sends only `product_id` and `quantity`** — never a price or a title. The server derives both from MongoDB. Otherwise a tampered request body sets its own price and the transaction protects nothing.

1. Validate shape; user exists; every `quantity > 0`.
2. One MongoDB `$in` query for all product ids → capture `title` and `price` snapshots. A missing or `active: false` product returns `409`, **before any PostgreSQL write**.
3. `total = Σ(quantity × unit_price)` in `Decimal`, quantized to 2 decimal places.
4. **PostgreSQL transaction** via asyncpg:
   - `INSERT orders` — `status='PENDING'`, `version=1`
   - `INSERT order_items` × N, carrying the snapshots
   - *(Strategy A only)* `INSERT outbox` — `event_type='ORDER_CREATED'`
   - `COMMIT` — any failure rolls back all of the above together
5. **After commit**, branch on `ORDER_SYNC_STRATEGY`:
   - `dual_write` → `tasks.index_order.delay(order_id)`; the outbox row already exists, so a publish failure loses nothing
   - `polling` → no Elasticsearch activity at all
6. `201 { order_id, total_amount, status, sync_status }`

**`sync_status` semantics.** The `POST /api/orders` response carries exactly one of two values: `QUEUED` under Strategy A, `DEFERRED` under Strategy B. The handler returns before the worker runs, so it can never report success or failure of the index write. The states `INDEXED`, `OUT_OF_SYNC`, and `MISSING_IN_ES` belong to a **different vocabulary** — they are badge states returned by `GET /api/sync/status/{order_id}` and rendered by the Screen 4 `SyncBadge`, never response values on order creation. The two vocabularies are deliberately kept separate.

**Ordering is load-bearing: MongoDB validation precedes the transaction.** A Mongo outage aborts the request with zero partial state, rather than committing an order whose totals could not be verified.

## 12. Strategy A — dual-write

```
POST /api/orders
  ├─ 1. validate + snapshot from MongoDB
  ├─ 2. compute total
  ├─ 3. BEGIN POSTGRES TRANSACTION
  │      INSERT orders · INSERT order_items × N · INSERT outbox
  │   COMMIT                                    ← the PostgreSQL write
  └─ 4. AFTER commit, in the request:
         tasks.index_order.delay(order_id)
              ↓
        [ RabbitMQ: es.sync ]                   ← transport
              ↓
        Celery worker
              build_order_document(conn, id)    ← reads PG
              es.index(id=order_id, version=pg_version,
                       version_type="external")  ← the Elasticsearch write
              UPDATE outbox SET processed_at=now()
```

`PATCH /api/orders/{id}/status` follows the same shape: guarded PG update, outbox row, `.delay()`.

**Participation.** RabbitMQ carries the message — transient, at-least-once, trusted for nothing. Celery executes `sync.index_order` with `task_acks_late=True` and `task_ignore_result=True`; no result backend means no Redis, so still exactly the three stores the assignment locks. The outbox is the record that the ES write is *owed*; the queue is only a fast path.

**Latency:** order to searchable, approximately one second.

| Failure | Result | Recovery |
|---|---|---|
| PG transaction fails | Total rollback; nothing written anywhere | none needed |
| ES down when the worker runs | Retries with backoff; `attempts` incremented, `last_error` recorded; outbox row stays unprocessed | automatic once ES returns; visible in `outbox` |
| RabbitMQ down at `.delay()` | Publish throws, is caught and logged; the order stays committed | beat task `drain_outbox()` retries |
| Worker crashes mid-task | Message redelivered via `acks_late` | idempotent re-index — `_id` is the order id |
| A stale worker finishes late | Elasticsearch rejects via `version_type=external` | a newer task already indexed current state |
| ES down 5 minutes, orders continue | PG authoritative; Screen 3 misses them; Screen 4 correct; outbox accumulates | drain converges within one beat interval |

## 13. Strategy B — periodic polling

```
POST /api/orders
  └─ BEGIN POSTGRES TRANSACTION
        INSERT orders · INSERT order_items × N
     COMMIT
     (no outbox row, no message — Elasticsearch is not touched at all)

  Celery beat, every 15 seconds
       ↓
  sync.poll_orders()
       ├─ SELECT last_polled_at FROM sync_state          -- may be NULL
       ├─ SELECT id FROM orders
       │    WHERE $wm IS NULL
       │       OR updated_at > $wm - INTERVAL '30 seconds'
       │    ORDER BY updated_at, id
       │    LIMIT 200
       ├─ build_order_document(conn, id) for each → bulk index into ES
       └─ UPDATE sync_state SET last_polled_at = now()
```

This is **genuine periodic polling**: it holds no event log and delivers nothing. It asks PostgreSQL which orders changed since last time and reconciles. A change cannot be lost, because it is *discovered* by comparing `updated_at` against a watermark rather than transmitted. If RabbitMQ, Celery, and Elasticsearch are all down, nothing is lost — the watermark has not advanced, and the next successful poll replays the entire gap.

**Latency:** 0–15 seconds, uniformly distributed rather than a mean.

**Three correctness details that make polling safe:**

*NULL-safe first poll.* `sync_state.last_polled_at` is nullable, and `updated_at > NULL` evaluates to NULL, which would match **zero rows** and make Strategy B appear entirely broken after a fresh seed. The query therefore short-circuits on `$wm IS NULL` and returns every order. `POST /api/sync/reset-watermark` sets the column to NULL to trigger this path deliberately.

*The trigger owns `updated_at`.* See §7. A poller is only as correct as the column it reads, and a missed update means permanent, silent loss.

*The 30-second overlap.* The watermark advances only after indexing. A crash in between leaves rows indexed but the watermark stale — harmless, because re-indexing is an idempotent overwrite. The dangerous case is the reverse, which no ordering can rule out without a shared transaction: two orders sharing an identical `updated_at`, where a `WHERE updated_at > $w` scan pages past the second and `last_polled_at` then moves beyond it, dropping that order from Elasticsearch forever. The overlap re-reads a window containing any ties, and the idempotent upsert makes the duplicates free. Cheap insurance against silent permanent loss.

| Failure | Result | Recovery |
|---|---|---|
| PG transaction fails | Total rollback | none needed |
| ES down during a poll | Batch fails; **watermark not advanced** | the whole window is retried next tick |
| Poller crashes mid-batch | Watermark not advanced; partial batch reprocessed | idempotent, converges |
| RabbitMQ or Celery down | No polling happens, and **nothing logs an error** | invisible until the dashboard looks stale |
| ES down 5 minutes, orders continue | PG authoritative; polls fail; watermark frozen | one successful poll replays the entire gap |

## 14. Shared versus strategy-specific code

**Shared, identical under both strategies:**

| Component | Note |
|---|---|
| `order_service.place_order()` steps 1–4 | the transaction body is identical; **only the post-commit step branches** |
| `sync_service.build_order_document(conn, order_id)` | the single PG→ES projection, used by A's task, B's poller, status updates, reindex, and the seed — so the ES shape cannot drift between paths |
| `orders_repo.py` | `insert_order`, `insert_items`, `get_order`, `update_status`, `list_orders_updated_since`, `update_status_guarded` |
| `products_repo.py`, `users_repo.py`, `search_repo.py` | unchanged |
| ES index name, mapping, settings | identical |
| every `api/` route | same contracts; `sync_status` differs in value only |
| Celery app and RabbitMQ configuration | both strategies use Celery; only task names and the beat schedule differ |
| `scripts/seed.py`, `scripts/reindex_orders.py` | call the projection directly, deliberately bypassing either strategy, so the seed guarantees a fully caught-up index regardless of configuration |
| the entire frontend | unaware of the strategy; this is what makes the comparison fair |

**Strategy-specific:**

| Component | `dual_write` | `polling` |
|---|---|---|
| post-commit in `place_order()` | `outbox_repo.enqueue()` + `.delay()` | no-op |
| post-commit in `update_status()` | `outbox_repo.enqueue()` + `.delay()` | no-op |
| `workers/tasks.py` | `index_order(order_id)`, `drain_outbox()` | `poll_orders()`, `poll_orders_once()` |
| beat schedule | `drain-outbox` every 15s | `poll-orders` every 15s |
| `outbox_repo.py` | used | present, never called — the table stays empty |
| `sync_state` + watermark | unused | created, read, advanced |
| `sync_status` in the `POST /api/orders` response | `QUEUED` | `DEFERRED` |
| tests | `test_sync_dual_write.py`, outbox recovery | `test_sync_polling.py`, watermark, NULL first poll, overlap, drift-then-catch-up |

## 15. Product snapshot behavior

Snapshots are written once at checkout and are **immutable**. No `UPDATE` path in the codebase touches `order_items.title` or `order_items.unit_price`. Screens 3 and 4 read those snapshots; nothing joins live MongoDB at read time. MongoDB is never on the order sync path.

The seed's deliberate mismatch makes this visible: after orders exist, the MongoDB document becomes `Wireless Mouse Pro` at 79.00, while every historical `order_items` row and Elasticsearch document still reads `Wireless Mouse` at 50.16. A backend test asserts it so it cannot regress.

**Why snapshot rather than joining live MongoDB at read time:** an invoice is a financial record. If it re-reads today's catalog, editing a title silently rewrites what the customer was charged. That is the milestone-4 answer, and the seed fixture is the proof.

## 16. RabbitMQ, Celery, and the outbox — consolidated role

- **RabbitMQ** — transport for `es.sync`. At-least-once, `task_acks_late=True`. Under Strategy A a lost message is recoverable because the outbox independently records the work; under Strategy B there are no order-path messages at all, because the poller discovers work by querying PostgreSQL rather than by receiving it.
- **Celery** — execution. Hosts `index_order` and `drain_outbox` under Strategy A, `poll_orders` under Strategy B, and owns the beat schedule. No result backend, so no Redis is introduced.
- **Outbox** — durability, Strategy A only. Written inside the order's own transaction, so the intent to index is as durable as the order itself. This makes "PostgreSQL committed" and "Elasticsearch will hear about it" a single atomic fact.

**What the queue actually buys:** checkout latency and availability become independent of search-index health. It is the load-bearing justification for Strategy A's asynchronous form, and the concrete answer to the assignment's timeout question.

## 17. Failure and consistency matrix

| # | Scenario | Behavior |
|---|---|---|
| 1 | PG insert fails mid-transaction | Full rollback — no order, items, or outbox row. `409`. |
| 2 | MongoDB down at checkout | Fails at step 2, before the transaction. Zero partial state. |
| 3 | ES down, Strategy A | Order committed; task retries; `attempts` and `last_error` recorded on the outbox row; Screen 4 badge reads `MISSING_IN_ES` | automatic once `drain_outbox` succeeds |
| 4 | RabbitMQ down at publish, Strategy A | Publish throws, caught; order committed | beat drain retries |
| 5 | Worker crashes after indexing, before marking done | Message redelivered; re-index is an idempotent overwrite | none needed |
| 6 | ES rejects a document (mapping error) | Retries with backoff; `attempts` incremented and `last_error` set on the **outbox row**; the Screen 4 badge shows `MISSING_IN_ES` | visible by querying `outbox` or via the badge |
| 7 | Concurrent status updates | PG `UPDATE … WHERE id=$1 AND version=$2` rejects the stale write; `version_type=external` rejects the stale ES write | caller retries with the current version |
| 8 | ES down, Strategy B | Polls fail, watermark frozen, drift on Screen 3 | one successful poll replays the whole gap |
| 9 | Poller down, Strategy B | Drift accumulates with **no error recorded anywhere** | restart resumes from the frozen watermark |
| 10 | Catalog edited mid-checkout | Affects the next checkout only; MongoDB is never on the order sync path | none needed |
| 11 | Two orders with identical `updated_at`, Strategy B | The 30s overlap re-reads the tie; the idempotent upsert absorbs it | none needed |
| 12 | **ES down 5 minutes, orders continue** | PG authoritative throughout. Screen 4 always correct; Screen 3 stale. Recovery is bounded by one beat interval, not by a human | see `NOTES.md`, answered per strategy |

## 18. Seed data

`python -m scripts.seed --reset`. Reproducible, and never a hard-coded insert in the UI.

### 18.0 Generation method

All seed data is generated **programmatically in Python** by `backend/scripts/seed.py`. No seed content is authored by an LLM, copied from a captured API response, or hand-inserted through a shell.

- **Determinism.** The script calls `random.seed(42)` and `Faker.seed(42)` at startup. The seed is configurable via `--seed`, and the default is `42`. Two runs with the same seed against an empty database produce byte-identical data, so the demo script in the README is repeatable and the invariants in §18.6 can be asserted against known values.
- **Libraries.** Python's `random` module, plus the `Faker` library for prose. `Faker` supplies product `description` text and incidental realism. `random` supplies quantities, per-order item counts, status and date bucket assignment, and catalog padding.
- **What is a constant and what is generated.** The split is deliberate and is the reason the seed is reproducible:
  - **Hand-authored constants**, not generated: the 8 user names and emails, the 6 required products with their exact titles, categories, prices, tags and attributes, the inactive product, and the roster of filler accessory names. Everything the assignment pins, and everything a reviewer or demo depends on, is a literal in the script.
  - **Generated**: product `description` prose, variant `stock` counts, the filler products' price and attribute values, order dates, line-item quantities, and which products land on which order.
  - **Rationale:** `Faker`'s output is not guaranteed stable across library versions, and `date_time_between` relative to "now" drifts every day. Because nothing that is *asserted* or *demo-visible* depends on the RNG, a `Faker` version bump or a run on a different date cannot break the acceptance checks.
- **Invariants are constructed, then verified.** The generator does not rely on chance to satisfy the requirements in §18.6. It builds orders to a **deterministic plan** that satisfies every minimum by construction (§18.3), and only then fills in incidental detail from the seeded RNG. A separate verification pass (§18.6) re-checks every invariant against the rows actually persisted and **exits non-zero with a failure report** if any is unmet, so an unenforced invariant fails the seed loudly rather than silently producing a bad demo.
- **Fixed date anchor.** Order dates are generated within a window anchored to a **constant** reference instant (`SEED_ANCHOR_DATE = 2026-09-30T00:00:00Z`), not to `datetime.now()`. Anchoring to the run date would make "at least 5 orders within the last 7 days" silently expire as real time passes, and would break byte-reproducibility. A `--anchor-date` flag overrides the anchor if a fresher demo is wanted; every date-bucket invariant is evaluated relative to whatever anchor is in force, so the requirements hold either way.
- **`--reset` truncates** users, orders, order_items, and outbox in PostgreSQL and drops the `products` collection in MongoDB before regenerating, so the script is idempotent and re-runnable.

### 18.1 Users

Eight users, as exact literals in the script — names and emails must match so the search demos are predictable, and the "Log In As" dropdown must list all eight.

| # | Name | Email | Demo purpose |
|---|---|---|---|
| 1 | John Doe | john.doe@example.com | default happy-path shopper |
| 2 | Jane Smith | jane.smith@example.com | second default login |
| 3 | Wendy Wireless | wendy.wireless@example.com | omni-search "Wireless" must hit her **name** |
| 4 | Alex Rivera | alex.rivera@example.com | multi-order history |
| 5 | Sam Patel | sam.patel@example.com | high-value orders for price-range demos |
| 6 | Casey Nguyen | casey.nguyen@example.com | mostly PENDING |
| 7 | Morgan Lee | morgan.lee@example.com | mostly SHIPPED |
| 8 | Riley Brooks | riley.brooks@example.com | older orders, date-range edge |

### 18.2 Products

Twenty-five products — 24 `active: true` plus one `active: false` fixture.

Every product carries all ten fields: `sku`, `title`, `description`, `price`, `category`, `tags[]`, `attributes{}` (non-empty), `variants[]` (at least one), `active`, `updated_at`. The `attributes` and `variants` requirements are stated explicitly because Screen 5 exists to demonstrate that the catalog is genuinely document-oriented. The per-product field set is asserted, not assumed — invariant 3 in §18.6 checks it.

*Category minimums — at least 5 active products in each:* `peripherals`, `audio`, `cables`, `office`.

*Price bands — at least 4 active products in each:* cheap `< $25`, mid `$25–$99`, premium `≥ $100`.

*Wireless coverage — at least 6 active products* whose title **or** tags contain "wireless", case-insensitively.

*Required named products — exact literals:*

| Title | Category | Price | Must-have tags / attributes |
|---|---|---|---|
| Wireless Mouse | peripherals | 50.16 | tags include `wireless`; `attributes` include `color` **and** `dpi` |
| Mechanical Keyboard | peripherals | 100.34 | `variants` for at least two switch types or colors |
| Wireless Earbuds | audio | 79.99 | tags include `wireless` and `bluetooth` |
| USB-C Hub 7-in-1 | cables | 45.00 | `attributes` list the port types |
| Desk Lamp LED | office | 32.50 | at least two color variants |
| Noise Cancelling Headphones | audio | 199.00 | premium band, useful for the price-range filter |

The remaining **eighteen** products are realistic accessories — HDMI cables, mouse pads, laptop stands, webcams — drawn from a hand-authored roster in the script so the storefront grid is not sparse. Their `description` is generated via `Faker`; their category, price band, `tags`, `attributes`, and `variants` are generated from the seeded RNG within the per-category and per-band quotas above.

**Counting:** 6 required named products (all active) + 18 additional active accessories + 1 `active: false` fixture = **25 total**, of which **24 are active** and **1 is inactive**. Every minimum above — the four category floors, the three price bands, and the wireless count — is measured against the **24 active** products. The inactive fixture satisfies no quota and is never shown on Screen 1.

### 18.3 Orders and line items

Forty orders and roughly eighty-five line items, built from a **deterministic construction plan**, not from unconstrained random draws. The plan allocates each of the 40 order slots to a required role before any incidental detail is chosen:

| Slot allocation | Count | Satisfies |
|---|---|---|
| Orders containing "Wireless Mouse" | 8 | search fixture |
| Orders containing "Mechanical Keyboard" | 3 | search fixture |
| Orders containing **both** | 2 | search fixture (overlap with the two above) |
| Orders belonging to Wendy Wireless | 3 | per-user minimum, ≥1 containing a wireless-tagged product |
| Orders in each status | 10 / 10 / 10 minimum | status mix, uppercase |
| Orders older than 60 days from the anchor | 5 | date-range edge, attributed to Riley Brooks and/or Morgan Lee |
| Orders within 7 days of the anchor | 5 | date-range edge |
| Orders under $30 / $30–$150 / over $200 | 5 / 5 / 5 minimum | price-range slider |
| Orders with 1 item, and with 4+ items | at least 1 of each | line-item distribution |

**Roles overlap by design, and the allocations are not disjoint.** The role minimums above sum to 71 against only 40 order slots, so a single order necessarily satisfies several roles at once — an order can be Wendy's *and* older than 60 days *and* over $200 *and* `SHIPPED`. The two "both" orders are the explicit case: they count toward the Wireless Mouse and Mechanical Keyboard totals simultaneously. An implementation that treats the table as a partition of 40 disjoint slots will find the constraints unsatisfiable; the allocator must instead assign roles greedily and then verify every minimum, which is exactly what §18.6 does. The seed's own construction plan in `scripts/seed.py` is the authority for the specific assignment, and §18.6 is the authority for whether it is correct.

Any remaining slots are filled from the seeded RNG within the same quotas. Only after the plan is fixed does the generator choose *which* filler product occupies a free line, the `quantity`, and the exact timestamp inside the slot's permitted date window.

*Status mix:* at least 10 each of `PENDING`, `PROCESSING`, `SHIPPED`, uppercase, used identically in PostgreSQL, the API, and Elasticsearch.

*Dates:* spread across the 90 days preceding the anchor, with the >60-day and <7-day edges as allocated above.

*Totals:* `orders.total_amount` is **computed** as `Σ(quantity × unit_price)` from the actual line items written in the same step. It is never generated independently — a generated total would silently violate the requirement that the total equals the sum of the items.

*Per user:* every seeded user has at least 2 orders. Wendy Wireless has at least 3, at least one of which contains a wireless-tagged product, and her name is searchable.

*Line items:* each `order_items` row stores `product_id` as text, snapshot `title`, `quantity`, and snapshot `unit_price` captured from the catalog at "checkout" time. Average at least 2 items per order, with some orders at 1 item and some at 4 or more.

### 18.4 Elasticsearch population

Every PostgreSQL order is projected to Elasticsearch through the same `build_order_document` used by both sync strategies, so the index is fully caught up **by construction** rather than by a parallel code path. The seed deliberately bypasses the active strategy. Document count equals PostgreSQL order count, and document fields match the §9 mapping.

### 18.5 Snapshot mismatch fixture

After orders and the Elasticsearch projection exist, the script renames the MongoDB document `Wireless Mouse` → `Wireless Mouse Pro` at 79.00 — **MongoDB only**. It then asserts that no `order_items` row and no Elasticsearch document changed, and that the catalog now reads `Wireless Mouse Pro`. Screens 1 and 5 show the new title and price; historical orders on Screens 3 and 4 keep `Wireless Mouse` at 50.16. The README calls this fixture out explicitly, since it is the proof for learning milestone 4.

### 18.6 Invariant enforcement

After writing, the script re-reads the persisted data from all three stores and checks every requirement below. Each is satisfied by construction in §18.2–18.3 and independently verified here. **Any failure prints a report and exits non-zero**, failing the seed rather than producing a demo that silently violates the assignment.

| # | Invariant | Checked against |
|---|---|---|
| 1 | 8 users, exact names and emails | PostgreSQL |
| 2 | 25 products, 24 active, 1 inactive, Screen 1 hides the inactive one | MongoDB |
| 2a | The catalog partition reconciles: 6 named active + 18 additional active accessories + 1 inactive = 25, and 6 + 18 = 24 active — so the headline total and the active count cannot disagree | MongoDB |
| 3 | Every product has all ten fields, non-empty `attributes`, ≥1 variant | MongoDB |
| 4 | ≥5 active products in each of the four required categories | MongoDB |
| 5 | ≥4 active products in each of the three price bands | MongoDB |
| 6 | ≥6 active products with "wireless" in title or tags, case-insensitive | MongoDB |
| 7 | The 6 named products exist with exact title, category, price, and required tags/attributes | MongoDB |
| 8 | 40 orders, ≥2 per user, ≥3 for Wendy Wireless with ≥1 wireless-tagged product | PostgreSQL |
| 9 | ≥10 orders in each of the three uppercase statuses | PostgreSQL |
| 10 | Orders exist across the full 90-day window; ≥5 older than 60 days; ≥5 within 7 days | PostgreSQL |
| 11 | ≥5 orders in each of `<30`, `30–150`, `>200` | PostgreSQL |
| 12 | `total_amount == Σ(quantity × unit_price)` for every order | PostgreSQL |
| 13 | ~85 line items, average ≥2 per order, at least one 1-item and one 4+-item order | PostgreSQL |
| 14 | ≥8 orders with "Wireless Mouse", ≥3 with "Mechanical Keyboard", ≥2 with both | PostgreSQL |
| 15 | Elasticsearch document count equals PostgreSQL order count | Elasticsearch |
| 16 | Elasticsearch documents match the §9 mapping and carry the same snapshots as `order_items` | both |
| 17 | Catalog reads `Wireless Mouse Pro` at 79.00 while every historical order still reads `Wireless Mouse` at 50.16 | both |

The report prints each check with its observed value so a reviewer can confirm the seed in under two minutes.

### 18.7 Invocation

```
python -m scripts.seed --reset                 # default seed 42, default anchor
python -m scripts.seed --reset --seed 7
python -m scripts.seed --reset --anchor-date 2026-10-15
python -m scripts.seed --verify-only           # re-run §18.6 against existing data
```

## 19. Docker architecture

`docker-compose.yml` runs **four services**: `postgres:16`, `mongo:7`, `elasticsearch:8`, `rabbitmq:3-management`. Named volumes for PostgreSQL and MongoDB. Healthchecks with `depends_on: service_healthy` so seeding never races the databases.

Elasticsearch requires `discovery.type=single-node`, `xpack.security.enabled=false`, `ES_JAVA_OPTS=-Xms512m -Xmx512m`, and a `memlock` ulimit — omitting these is the most common reason Elasticsearch fails to start on a laptop, so they are set correctly from the first run.

Ports: 5432, 27017, 9200, 5672, 15672. On the host: `uvicorn --reload` on 8000, Vite on 5173, `celery worker` and `celery beat`. CORS allows `http://localhost:5173`. The README documents the boot-to-demo path, including which applications run on the host versus in containers.

## 20. Testing — backend only

`pytest` against the real containers, using FastAPI's async client.

| File | Covers |
|---|---|
| `test_order_placement.py` | happy path persists order, items, and outbox row; `total == Σ(items)`; snapshots captured from MongoDB; missing or inactive product returns 409 with **no** PostgreSQL rows; a simulated failure mid-insert rolls everything back |
| `test_snapshot.py` | place an order, rename the product in MongoDB, assert `order_items` and the Elasticsearch document are unchanged |
| `test_orders_touch_trigger.py` | `updated_at` and `version` advance on every update, regardless of the code path |
| `test_sync_dual_write.py` | the order reaches ES via RabbitMQ/Celery; ES down leaves the outbox row pending; `drain_outbox` repairs it; a redelivered task is idempotent |
| `test_sync_polling.py` | a change with no event is still discovered; a NULL watermark returns all orders rather than none; identical `updated_at` rows are not dropped; a frozen watermark replays the whole gap; the watermark does not advance on failure |
| `test_search.py` | "Wireless" returns both Wendy Wireless's orders and orders containing wireless products; status, date, and price filters each shrink the result set; the revenue aggregation equals the sum of the filtered hits; money fields serialize as strings from both stores |
| `test_data_source_isolation.py` | asserts Screen 3's service imports no PostgreSQL or MongoDB repository — the structural rule from §4, enforced by test |
| `test_seed_determinism.py` | the §18.3 construction plan is a **pure function of `(seed, anchor_date)`**: two calls with the same inputs yield identical slot allocations, statuses, date buckets, and per-order line items. Needs no database and no containers, so it is cheap. This is the mechanism that keeps "reproducible" in §18.0 an enforced property rather than a claim |

`test_seed_determinism.py` deliberately tests the **plan**, not the database. The assertion is that `build_order_plan(seed, anchor_date)` is referentially transparent — no module-level RNG state, no `datetime.now()`, no database reads — so the whole seed can be proven repeatable by a unit test rather than only by running `--reset` twice and diffing.

## 21. README demonstration and comparison plan

**Part 0 — boot and baseline.** Start the four containers, run migrations, seed, run `python -m scripts.reindex_orders.py`, start the API, Vite, and Celery. Verify the seed report.

**Part 1 — Strategy A (`ORDER_SYNC_STRATEGY=dual_write`).** Reindex → place an order → it appears in Screen 3 within about a second. Change its status in Screen 4 → Screen 3 follows immediately. Then `docker compose stop elasticsearch` and place another order: it appears in Screen 4, is **missing** from Screen 3, the badge reads `MISSING_IN_ES`, and `SELECT * FROM outbox WHERE processed_at IS NULL` shows a pending row carrying the error. Restart Elasticsearch → `drain-outbox` → Screen 3 converges. This is the assignment's timeout question, demonstrated rather than asserted.

**Part 2 — Strategy B (`ORDER_SYNC_STRATEGY=polling`).** Reindex → `reset-watermark` → place an order → **not** in Screen 3. Change its status → still not. `poll-once` → both appear at once. Then stop the Celery worker, place three more orders, and restart it: all three appear, with no per-event record anywhere. That is B's blind spot, made visible.

**Part 3 — measured comparison.** A small script places an order and polls the search endpoint until it appears, printing the observed latency for the active strategy. Run it under each strategy and paste both real numbers into the README table:

| | A: dual-write | B: polling |
|---|---|---|
| Order → searchable | *measured* | *measured* |
| ES down 5 minutes | orders missing from Screen 3; pending outbox rows; self-recovering | polls fail, watermark frozen, whole gap replayed |
| Broker down | outbox retains intent | no polling occurs |
| Worker down | messages redelivered, retry visible | **silent** drift |
| Extra tables | `outbox` | `sync_state` |
| PostgreSQL load after commit | none | one range scan per tick |
| Failure record | per-event (`attempts`, `last_error`) | none |

**Part 4 — `NOTES.md`, answering all five learning milestones** from behavior observed in Parts 1–3 rather than a theoretical account:

1. **Split-brain** — what happens to the admin dashboard if Elasticsearch is down for five minutes while customers keep placing orders, and how each strategy recovers.
2. **Why not SQL search** — why a large PostgreSQL join plus `LIKE '%term%'` is a poor fit for Screen 3, contrasting inverted indexes with B-Trees.
3. **Why MongoDB for the catalog** — which modeling problem (variants, sparse attributes, evolving fields) is easier in documents than in normalized tables for this POC.
4. **Snapshotting** — why title and price are copied into `order_items` and the Elasticsearch document at checkout instead of joining live MongoDB at read time.
5. **Write-path discipline** — which screens may write to which store, and what goes wrong if the app dual-writes orders into MongoDB "for convenience".

`NOTES.md` also contrasts our `A-queued` form against the `A-inline` synchronous baseline with recorded latency numbers.

## 22. Deliverables

**Required by the assignment:** `backend/` and `frontend/` source following the specified layout · `docker-compose.yml` for PostgreSQL, MongoDB, and Elasticsearch, plus RabbitMQ · `requirements.txt` and `frontend/package.json` with install and run scripts · `frontend/vite.config.js` · `sql/001_schema.sql` · `scripts/seed.py` and `scripts/reindex_orders.py` · `orders_mapping.json` and a one-step reindex command · `.env.example` with no real secrets · `README.md` covering boot, install, migrate, seed, run, all five screens, and both sync strategies · `NOTES.md` answering the five learning milestones above.

**Added by agreement:** `backend/tests/` as specified in §20, each test evidencing a specific claim made in `NOTES.md`; a `Makefile` with `restart` and `reset-watermark` targets used by the demo, which is a developer convenience only and changes no application architecture.

## 23. Component rationale

- **PostgreSQL** — orders touch money and fulfillment and require ACID. One `orders` row and N `order_items` rows must appear together or not at all.
- **MongoDB** — the catalog's `attributes` and `variants` are sparse and evolving. A new spec key per product is a migration in a relational store and a document edit here.
- **Elasticsearch** — Screen 3 needs full-text across two denormalized arrays plus faceted aggregations. `LIKE '%Wireless%'` cannot use a B-Tree index; an inverted index tokenizes at write time and answers in milliseconds.
- **RabbitMQ** — transports the ES write off the checkout path so search-index health does not govern order latency.
- **Celery** — executes that write with retries, backoff, and late acknowledgement, and owns the beat schedule for both strategies.
- **The outbox** — makes "PostgreSQL committed" and "Elasticsearch will hear about it" a single atomic fact, and makes every Strategy A failure individually visible.
- **`sync_state` and the watermark** — give Strategy B the property that no change can be lost, because nothing needs to be delivered.
- **The `orders_touch` trigger** — makes Strategy B's correctness a property of the database rather than of every future code path.
- **`build_order_document`** — one projection, five callers, so dual-write, polling, status updates, reindex, and the seed cannot disagree about the Elasticsearch document shape.
- **`version` on both sides** — turns "is this in sync?" from a guess into a comparison the UI can display, and blocks stale writes in both stores.
- **Five Pinia stores** — makes the data-source rule a structural boundary rather than a code-review habit.
- **`scaled_float(100)` and `Decimal128`** — the two places where binary floating point would otherwise put a wrong number on screen.

## 24. Verification gates before the project is considered complete

1. Reindex rebuilds the index correctly from an empty Elasticsearch.
2. The seed prints a report in which every invariant in §18.6 passes.
3. Both strategies demonstrably converge, and each failure mode in §17 is reproducible on demand.
4. `NOTES.md` milestone 1 is answered from observed behavior for both strategies.
5. Screens 1–5 run with zero manual data entry after seeding.
