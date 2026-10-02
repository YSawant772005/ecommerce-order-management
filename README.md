Updated todo list

Paste this into `README.md`:

```markdown
E-Commerce Order Management & Search Service

A full-stack ecommerce application with:

- Vue 3 storefront
- FastAPI backend
- PostgreSQL for users, orders, order items, and outbox events
- MongoDB for the product catalog
- Elasticsearch for admin order search
- RabbitMQ and Celery for asynchronous order synchronization
- Nginx for serving the frontend and proxying API requests

Run With Docker

Start Docker Desktop first.

From the project directory:

```powershell
cd "C:\Users\Dell\Downloads\ecommerce-order-management-friend-clean-baseline\ecommerce-order-management-friend-clean-baseline"
docker compose up -d
```

Open the application:

```text
http://127.0.0.1:5173
```

The API is available at:

```text
http://127.0.0.1:8000
```

RabbitMQ management dashboard:

```text
http://127.0.0.1:15672
```

The current Docker Compose stack starts:

- Frontend/Nginx
- FastAPI backend
- PostgreSQL
- MongoDB
- Elasticsearch
- RabbitMQ
- Celery worker
- Celery beat

## First-Time Database Setup

If the database volumes are empty, apply the PostgreSQL schema:

```powershell
Get-Content .\backend\sql\001_schema.sql | docker compose exec -T postgres psql -U ecommerce -d ecommerce
```

Seed the demo data:

```powershell
docker compose exec backend python -m scripts.seed --reset
```

The seed creates:

- 8 users
- 25 products
- 40 orders
- Order items and search projections

## Frontend Development

The production Docker setup serves the compiled frontend through Nginx.

You do not need to run `npm run dev` when using Docker.

After changing frontend source files:

```powershell
cd frontend
npm install
npm run build
cd ..
docker compose build frontend
docker compose up -d frontend
```

Then open:

```text
http://127.0.0.1:5173
```

## Login

The current frontend login is a demo client-side login.

Admin account:

```text
Email: admin@nest.local
Password: admin123
```

Shopper login uses one of the seeded customer accounts.

The backend currently does not implement production authentication, password storage, tokens, or server-side authorization.

## Main User Flows

### Shopper

1. Open `/login`.
2. Select Shopper.
3. Browse products.
4. Search or filter by category.
5. Add products to the cart.
6. Open Checkout.
7. Place an order.

### Admin

1. Open `/login`.
2. Select Admin.
3. Use the demo admin credentials.
4. Search orders through Elasticsearch.
5. Open PostgreSQL-backed order details.
6. Update order status.
7. Manage products through the MongoDB catalog page.

## Synchronization Flow

Order synchronization uses asynchronous queued dual-write:

```text
PostgreSQL transaction
        |
        v
Outbox event
        |
        v
RabbitMQ
        |
        v
Celery worker
        |
        v
Elasticsearch order projection
```

PostgreSQL is the source of truth. Elasticsearch is a rebuildable search projection.

The order placement response initially reports:

```text
QUEUED
```

The actual projection state can be checked with:

```text
GET /api/sync/status/{order_id}
```

Possible states:

```text
IN_SYNC
OUT_OF_SYNC
MISSING_IN_ES
```

## Useful Commands

Show service status:

```powershell
docker compose ps
```

View backend logs:

```powershell
docker compose logs -f backend
```

View worker logs:

```powershell
docker compose logs -f celery-worker
```

View frontend logs:

```powershell
docker compose logs -f frontend
```

Stop the current Compose project:

```powershell
docker compose down
```

Stop and remove the old single-container version, if it exists:

```powershell
docker stop ecommerce
docker rm ecommerce
```

Do not remove Docker volumes unless you intentionally want to delete the database data.

## Backend Tests

Run the backend tests:

```powershell
cd backend
python -m pytest tests/
```

The tests use real PostgreSQL, MongoDB, Elasticsearch, and RabbitMQ services.

## Important Data Rules

- PostgreSQL owns users, orders, order items, statuses, money, versions, and outbox events.
- MongoDB owns products.
- Elasticsearch only stores order search projections.
- Product titles and prices are copied into order items during checkout.
- Historical order snapshots must not be replaced with current catalog data.
- PostgreSQL order versions protect Elasticsearch from stale writes.
- Outbox events are created inside the same transaction as the order.
- Indexing is dispatched only after the transaction commits.
- Elasticsearch can be rebuilt from PostgreSQL.

## Current Architecture Limitation

The frontend includes a demo login and role-based navigation, but authentication is not enforced by the backend. This is suitable for the current demonstration environment, not production security.
```
