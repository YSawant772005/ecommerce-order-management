# Implementation TODO

**Single progress tracker for the project.** Updated after every verified phase.

**Architecture (locked):**
```
Vue 3 + Vite → FastAPI → ┬─ MongoDB  (product catalog)
                         └─ PostgreSQL (orders / users / source of truth)
                                │ COMMIT
                                ▼
                             Outbox ──► RabbitMQ ──► Celery ──► Elasticsearch ──► Admin Search
```

**Strategy:** **Strategy 1 only — asynchronous queued dual-write synchronization.**
Strategy 2 (periodic polling) is **NOT** implemented and is **NOT** configurable.
`ORDER_SYNC_STRATEGY` is constrained to `Literal["dual_write"]`; `polling` raises
`ValidationError`. See `docs/RECOVERY_AUDIT.md` → "Recorded rulings carried forward".

**Vocabulary (use these words):**
- MongoDB = Product Catalog
- PostgreSQL = source of truth for orders, order items, users, status, money, fulfillment
- Elasticsearch = search/indexing projection for Admin Order Search
- RabbitMQ = message broker / transport · Celery = background task execution
- Outbox = reliable event record for Strategy 1
- Canonical projection = `build_order_document()`
- The sync is **asynchronous queued dual-write synchronization**. Never "simultaneous dual write".

Legend: `[ ]` not started · `[~]` in progress · `[x]` completed **and verified** · `[!]` blocked

---

## Phase 0 — Recovery / Audit — `[x]`
- [x] Read assignment PDF, approved spec, approved plan, Strategy 1 `.docx`
- [x] `git status` / `branch` / `log` / uncommitted — branch `feature/strategy1-dual-write`, 6 docs commits
- [x] Full filesystem inventory (no `.venv` noise)
- [x] Toolchain probe: python3, pip, node, npm, docker, git
- [x] Live probes of PostgreSQL, MongoDB, Elasticsearch, RabbitMQ
- [x] Real row/index/queue counts (all zero — schema absent)
- [x] Ran the existing test suite (1 file, RED for the correct reason)
- [x] Wrote `docs/RECOVERY_AUDIT.md`
- [x] Rewrote this file
- [x] Installed `backend/requirements.txt` into `backend/.venv` (was empty)

## Phase 1 — Environment / Docker — `[x]`
- [x] PostgreSQL 16.15 up on `127.0.0.1:55432`, db `ecommerce`, role `ecommerce` (port 55432 because system PG 18 owns 5432 — untouched)
- [x] MongoDB 7.0.14 up on `127.0.0.1:27017`
- [x] Elasticsearch 8.13.4 up on `127.0.0.1:9200`, cluster `ecommerce-poc`
- [x] RabbitMQ 3.12.14 up on 5672 + management 15672
- [x] Python venv populated with all 39 deps
- [x] Node 22.11 available for the frontend build (host default is 18.19)
- [x] `docker-compose.yml` — required deliverable authored (PG 16.4, Mongo 7, ES 8.13.4, Rabbit 3.12)
- [!] `docker compose up -d` run on this host — **BLOCKED, environmental**: Docker not installed, `sudo` needs an interactive password. Native stack is the real substitute; not a mock. Does not block application work.
- [x] `.env.example`
- [x] `scripts/dev-stack.sh` — native real-service control (start/stop/status/reset-data/logs)

## Phase 2 — PostgreSQL — `[x]`
- [x] `backend/sql/001_schema.sql`: `users`, `orders`, `order_items`, `outbox`
- [x] PKs, FKs, indexes, CHECK constraints; `NUMERIC(12,2)` money
- [x] `orders_touch()` plpgsql + `orders_touch_trg` BEFORE UPDATE owning `updated_at` + `version`
- [x] `app/core/postgres.py` → `get_pool()`, `close_pool()`
- [x] Idempotent DDL (`IF NOT EXISTS`, `CREATE OR REPLACE`, `DROP TRIGGER IF EXISTS`) — applied twice via `psql`, both exit 0
- [x] Order-item snapshot immutability trigger (title/price cannot be rewritten)
- [x] Verified: 4 tables, 7 indexes, 3 trigger functions, 2 trigger bindings on the live DB
- [x] tests: version monotonic, updated_at advances, re-apply safe, trigger attached once — `test_orders_touch_trigger.py`, 13 passed

## Phase 3 — MongoDB — `[x]`
- [x] `app/core/mongo.py` → `get_mongo()` / `get_db()` / `close_mongo()` — live probe verified
- [x] `app/repositories/products_repo.py` — list/get/create/update; `Decimal128` on write and on read
- [x] Ten product fields, ≥1 variant, non-empty `attributes`
- [x] Indexes: `sku` unique, `{category, active}`, `{tags}`
- [x] tests: Decimal128 round-trip, CRUD, **no order data in MongoDB** — `test_products_repo.py`, 21 passed
- [x] `Decimal128` confined to the repository, enforced by a test that scans `app/`

## Phase 4 — Elasticsearch — `[~]`
- [x] `app/core/elasticsearch.py` → `get_es()`, `ensure_orders_index()`, `load_orders_index_definition()`
- [x] `app/search/orders_mapping.json` — `items` = **object** (never nested), `.prefix` n-gram subfields, `scaled_float(100)`, 1 shard / 0 replicas / `refresh_interval 1s`
- [x] tests: index creation, mapping shape, analyzer — `test_clients.py`, 13 passed
- [ ] money round-trip at extremes (belongs with the projection tests, Phase 6)

## Phase 5 — Models / HTTP Contracts — `[x]`
- [x] `app/models/_money.py` — the single money type: `Decimal` in Python, `"150.50"` in JSON, 2dp
- [x] `app/models/order.py` — `OrderCreate` (extra fields **forbidden**: no client price), `OrderOut`, `OrderDetail`, `OrderItemOut`, `StatusUpdate`
- [x] `app/models/product.py` — `Product`, `Variant`, `ProductCreate`, `ProductUpdate`; ≥1 variant, non-empty `attributes`
- [x] `app/models/search.py` — `SearchRequest`, `SearchHit`, `SearchResponse` (ES-shaped, no PG join)
- [x] `app/models/user.py`, `app/models/sync.py` — two **separate** sync vocabularies
- [x] tests: money as string, quantized to 2dp, no `float` annotation anywhere, client price rejected — `test_models_money.py`, 21 passed

## Phase 6 — Canonical Projection — `[x]`
- [x] `services/sync_service.build_order_document(conn, order_id)` — the **only** projection
- [x] Reads PostgreSQL only (order + customer + `order_items` snapshots); never MongoDB
- [x] test: PG order + PG snapshots → exact §9 Elasticsearch document — `test_sync_projection.py`, 18 passed
- [x] Verified against real ES: indexes, money exact, and "Wir" → "Wireless Mouse" via the n-gram

## Phase 7 — Order Creation — `[~]`
- [x] `services/order_service.place_order(req) -> OrderOut`
- [x] Mongo validation → `total = Σ(quantity × unit_price)` in `Decimal` → one PG transaction
- [x] `order_items` carry immutable title/price snapshots
- [x] `sync_status` = `QUEUED` on the create response (never `INDEXED`/badge vocabulary)
- [x] tests: total correctness, snapshots, 409 on inactive/missing with zero PG rows, rollback — `test_order_placement.py`, 18 passed
- [x] Version guard on status: stale `expected_version` → 409, stale write does not land
- [x] `POST /api/orders` route (+ `GET /api/orders/{id}`, `PATCH /api/orders/{id}/status` — vertical slice 2026-10-01; search/sync/product-write routes still Phase 13)

## Phase 8 — Outbox — `[x]` (2026-10-01)
- [x] `repositories/outbox_repo.py` — `enqueue` / `claim_unprocessed` / `mark_processed` / `mark_failed` / `mark_superseded` / `get`; `MAX_ATTEMPTS = 5`
- [x] Outbox row written **inside** the order transaction (`orders_repo.insert_outbox_event` delegates to `enqueue`)
- [x] Settlement is compare-and-set on `id` (`WHERE id=$1 AND processed_at IS NULL`)
- [x] Exact event identity: worker settles only its own `outbox_id`, never by `aggregate_id`
- [x] tests: pending / claim / process / retry / permanent-failure visibility — `test_outbox_repo.py`, 8 passed

## Phase 9 — RabbitMQ / Celery — `[x]` (2026-10-01)
- [x] `workers/celery_app.py` — broker from env, `task_acks_late=True`, `task_ignore_result=True`, **no result backend**; beat `drain-outbox` every 15s
- [x] `workers/tasks.py` — `index_order(order_id, outbox_id=None)`, `drain_outbox` (thin wrappers over `sync_service`)
- [x] Idempotent indexing with `id=order_id`; retryable outage vs terminal conflict (`test_sync_tasks.py`, 7 passed)
- [x] Beat schedule for `drain-outbox`
- [x] **Proof:** real worker + real broker — order 2 placed via API → worker consumed → ES doc v1 `total_amount "50.16"` → outbox settled, attempts 0

## Phase 10 — Versioning / Stale-Write Protection — `[x]` (2026-10-01)
- [x] ES write always uses `version=pg_version`, `version_type="external"` (`sync_service.index_order`)
- [x] v1 after v2 MUST NOT overwrite v2 — `test_stale_write_cannot_overwrite_newer_doc`, `test_version_conflict_is_terminal_not_retried`
- [x] Version conflict is **terminal** (`mark_superseded`), never retried
- [x] ES outage is retryable; after `MAX_ATTEMPTS` the row is terminal-failed and visible
- [x] `PATCH /api/orders/{id}/status` guarded on `version`; stale → 409 (`test_stale_status_update_is_rejected_409`)

## Phase 11 — Order Status Updates — `[x]` (2026-10-01)
- [x] PG transaction: guarded update → version bump (trigger) → outbox row → COMMIT (`order_service.update_status`)
- [x] then RabbitMQ → Celery → PG read → `build_order_document()` → ES (proven live: order 2)
- [x] ES is **never** updated first; `order_items` snapshots are **never** updated
- [x] Verified in both stores after the update (`test_sync_status_out_of_sync_after_update` + live proof)

## Phase 12 — Search — `[x]` (2026-10-01)
- [x] `POST /api/search/orders` — **Elasticsearch only** (`api/search.py`, `services/search_service.py` imports `search_repo` ONLY — AST-tested)
- [x] `multi_match` (`customer.name^2`, `items.title.prefix`, `items.title`, `customer.email`) + `bool` + `terms`/`range` filters
- [x] `sum` revenue + `terms` status aggregations over the **whole filtered set**, independent of `size` (`test_revenue_agg_spans_all_pages_not_just_hits`)
- [x] Revenue never derived from paginated hits; revenue matches PG to the cent
- [x] tests: partial name/title, status/date/price filters, revenue, pagination — `test_search.py`, 10 passed

## Phase 13 — Backend APIs — `[x]` (2026-10-01: all routes live)
- [x] `GET/POST/PUT /api/products[/{id}]`, `GET /api/users`
- [x] `POST /api/orders`, `GET /api/orders/{id}`, `PATCH /api/orders/{id}/status`
- [x] `POST /api/search/orders`, `GET /api/sync/status/{order_id}`, `POST /api/sync/drain-outbox`, `POST /api/sync/reindex`, `GET /api/health`
- [x] `response_model` on every route so money serializes via the Pydantic string serializer
- [x] Per endpoint: success · validation error · not found · correct model · correct status code (`test_api_slice.py`, `test_sync_api.py`)
- [ ] `response_model` on every route so money serializes via the Pydantic string serializer
- [ ] Per endpoint: success · validation error · not found · DB failure · invalid input · empty result · correct model · correct status code

## Phase 14 — Frontend Foundation — `[~]` (vertical slice 2026-10-01: skeleton + 3 screens, Extej theme, nginx)
- [x] Vue 3 + Vite + Vue Router 4 + Pinia skeleton
- [x] Four stores (`cart`, `session`, `catalog`, `orders`; `search` deferred with Screen 3)
- [x] `utils/money.js` — `Intl.NumberFormat` on the money **string**
- [x] `vite.config.js` on 5173 proxying `/api` → 8000; `nginx.conf` prod (static + `/api/` proxy + SPA fallback)
- [x] Light Extej-style system (sidebar pill `#FF7A1A`, cards, badges, buttons, tables)
- [x] `npm run build` passes on Node 22 (verified 2026-10-01)

## Phase 15 — Frontend Screens — `[x]` (2026-10-01: all 5 live, build green)
- [x] Screen 1 Storefront `/` — Mongo products, cards, price, add-to-cart
- [x] Screen 2 Checkout `/checkout` — cart lines, place order, loading/success/failure, shows order ID
- [x] Screen 4 Order Detail `/admin/orders/:id` — PG only; snapshot titles/prices, totals, version, QUEUED badge, not-found state
- [ ] Screen 3 Admin Search `/admin/orders` — search box, filters, status, date range, customer, results table, pagination, aggregations, revenue, loading/empty/error states. **Elasticsearch only.**
- [ ] Screen 5 Catalog Admin `/admin/catalog` — Mongo only; list, create, edit, deactivate, variants, tags, attributes, price, category, active; validated forms

## Phase 16 — Routing — `[x]` (2026-10-01: all 5 routes + nginx SPA fallback live)
- [x] `/`, `/checkout`, `/admin/orders/:id` — direct load, back/forward, refresh via nginx SPA fallback + Router history
- [ ] `/admin/orders`, `/admin/catalog` routes + invalid order id → 404 state
- [ ] Every navigation button works — no dead links, no links to nonexistent pages

## Phase 17 — Seed — `[x]` (2026-10-01: all invariants green, ES 40/40, mismatch live)
- [ ] `scripts/seed.py` — `--reset`, `--seed`, `--anchor-date`, `--verify-only`
- [ ] Deterministic: `random.Random(seed)` + `Faker.seed(seed)`, never `datetime.now()`
- [ ] `build_order_plan(seed, anchor_date)` is a **pure function** — proven by a unit test with no DB
- [ ] 8 users · 25 products (24 active + 1 inactive) · 40 orders · ~85 items
- [ ] ≥4 categories · ≥6 wireless · ≥5 per category · ≥4 per price band
- [ ] `total_amount == Σ(quantity × unit_price)`, computed never generated
- [ ] Deliberate mismatch: Mongo `Wireless Mouse Pro` @ 79.00 vs history `Wireless Mouse` @ 50.16
- [ ] ES fully caught up through `build_order_document`
- [ ] 18 invariants verified against the real stores; non-zero exit on any failure

## Phase 18 — Data Source Isolation — `[x]` (2026-10-01: service + router AST tests, negative control)
- [ ] One module per store in `repositories/`; no cross-store import
- [ ] AST tests at **service** and **router** level
- [ ] Screen 3 → ES only · Screen 5 → Mongo only · Screen 4 → PG only

## Phase 19 — Money Safety — `[x]` (2026-10-01: `test_revenue_matches_postgres_to_the_cent`, string wire format everywhere)
- [ ] Python `Decimal` · PG `NUMERIC(12,2)` · Mongo `Decimal128` · ES `scaled_float(100)` · HTTP JSON string
- [ ] No `float` ever touches money
- [ ] test: `799.00`, never `799.0000000001`; revenue agg matches PG to the cent

## Phase 20 — Integration Tests — `[x]` (2026-10-01: 152 passed covering schema, repos, money, placement, outbox, worker, ES, search, isolation, API)
- [ ] schema · repositories · money · seed determinism · order creation · snapshot immutability
- [ ] outbox · Celery task · real RabbitMQ integration · ES indexing · version protection
- [ ] status update · search · aggregations · data-source isolation · API routes · reindex

## Phase 21 — UI Self-Test — `[~]` (2026-10-01: all routes serve + API-verified; full button-by-button pass is manual)
- [x] Every screen handles LOADING / SUCCESS / EMPTY / ERROR states (all 5 views)
- [ ] Full button-by-button manual pass · narrow widths

## Phase 22 — Failure Testing — `[~]` (2026-10-01)
- [ ] ES unavailable → PG order committed, event recoverable, converges when ES returns
- [ ] RabbitMQ unavailable → order committed, outbox durable, re-dispatched
- [ ] Celery stopped → order + outbox survive, drain on start
- [ ] Duplicate delivery · stale version · invalid order · invalid/missing product
- [ ] Mongo unavailable · PostgreSQL unavailable

## Phase 23 — Documentation — `[x]` (2026-10-01: `README.md`, `NOTES.md` with 5 milestones + strategy comparison)
- [ ] `README.md` — architecture, setup, env, schema, seed, run API/worker/frontend, tests, demo path
- [ ] `NOTES.md` — why PG is truth, why Mongo owns the catalog, why ES owns search, why snapshots are immutable, why RabbitMQ is transport and Celery is execution, why the outbox is durability, and the eventual-consistency window
- [ ] Sync-options comparison covered analytically (no second code path)

## Phase 24 — Final Audit — `[ ]`
- [ ] Every checkbox in the recovery prompt §40 verified against real output
- [ ] `docs/RECOVERY_AUDIT.md` updated with final state
- [ ] This file fully checked

---

## Final verification gate — `[ ]`

Infrastructure: PostgreSQL · MongoDB · Elasticsearch · RabbitMQ · FastAPI · Celery · Vue all running.
Data: 8 users · 25 products (24 active + 1 inactive) · 40 orders · ≥4 categories · ≥6 wireless · snapshot mismatch present.
Architecture: PG source of truth · Mongo catalog source · ES search source · Strategy 1 · Outbox · RabbitMQ · Celery · canonical projection · version protection.
Behaviour: status sync works · search works · aggregations work · reindex works · snapshot immutability verified · money precision verified · data-source isolation verified.
Quality: backend suite green · frontend builds · all routes work · all important buttons work · loading/empty/error states work · UI professional · no fake or mock database · no hardcoded replacement data.
Docs: README · NOTES · `RECOVERY_AUDIT.md` · this file — all current.
