# E-Commerce Order Management & Search (Strategy 1)

Vue 3 SPA over FastAPI. PostgreSQL is the source of truth for orders;
MongoDB owns the product catalog; Elasticsearch is an admin-search
projection. Sync is **asynchronous queued dual-write**:
`PG COMMIT → outbox → RabbitMQ → Celery → Elasticsearch` (~1s window).

## Run (one container)

```bash
docker build -t ecommerce-single .
docker run -d --name ecommerce -p 8080:8080 -v ecommerce-data:/data ecommerce-single
```

UI at http://127.0.0.1:8080 (API proxied at `/api/`). First boot seeds
8 users · 25 products · 40 orders automatically. Data persists in the
`ecommerce-data` volume.

## Run (develop)

```bash
docker compose up -d                                   # PG 5432, Mongo 27017, ES 9200, RabbitMQ 5672/15672
cd backend && python -m scripts.seed --reset           # 8 users, 25 products, 40 orders
python -m uvicorn app.main:app --port 8000 &           # API on :8000
celery -A app.workers.celery_app.celery_app worker &   # sync worker
celery -A app.workers.celery_app.celery_app beat &     # 15s outbox drain
cd ../frontend && npm install && npm run dev           # UI on :5173
```

Prod UI: `npm run build`, serve `dist/` with `nginx.conf`
(`try_files` SPA fallback, `/api/` → `:8000`).

Native (no Docker): `scripts/dev-stack.sh start` (PG on **55432**),
then `PG_DSN=postgresql://ecommerce:ecommerce@127.0.0.1:55432/ecommerce`
for every backend command.

## Demo path

Scope note: this build ships **one** sync strategy — asynchronous queued
dual-write with outbox (assignment Option A+C combined). The strategy
comparison lives analytically in `NOTES.md`; there is no second runtime
code path, by explicit project decision (see `docs/RECOVERY_AUDIT.md` C1).

1. `/` storefront (Mongo) → add to cart → `/checkout` → place order → `QUEUED`.
2. Worker indexes within ~1s; `/admin/orders` (ES only) finds it by "Wir".
3. `/admin/orders/:id` (PG) status change → badge `QUEUED` → ES follows.
4. `GET /api/sync/status/{id}`: `IN_SYNC` / `OUT_OF_SYNC` / `MISSING_IN_ES`.
5. ES down: orders still commit; outbox accumulates; `POST /api/sync/drain-outbox` converges.
6. Rename a product in `/admin/catalog` (Mongo) → history on screens 3/4 unchanged (snapshots).

## Tests

```bash
cd backend && python -m pytest tests/   # 140+ against the real stores
```

## Env

See `.env.example`. `ORDER_SYNC_STRATEGY=dual_write` is the only value;
anything else raises `ValidationError`. Money crosses the wire as a JSON
string (`"50.16"`), `Decimal` in Python, `NUMERIC(12,2)` in PG,
`Decimal128` in Mongo, `scaled_float(100)` in ES.
