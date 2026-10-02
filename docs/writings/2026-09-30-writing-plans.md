# Writing Plans - Draft Preparation Notes

This document records the decision rationale for generating the implementation plan from the approved design specification (docs/superpowers/specs/2026-09-30-ecommerce-order-management-design.md).

## Approved design (key points)
- Five screens with strict per-screen data source rules (PG/Mongo/ES)
- Two sync strategies (A dual-write with outbox + Celery/RabbitMQ; B polling with sync_state watermark and trigger)
- Backend-only pytest, no ORM, drivers: asyncpg, motor, AsyncElasticsearch
- Money as strings/Decimal; snapshots immutable; versioned external concurrency
- Seed deterministic (construction plan + verifier), anchor 2026-09-30T00:00:00Z

## Plan scope
- Generate detailed, task-by-task plan with test-first steps, file paths, interfaces, verification commands.
- Each task independently testable; commits per task.
- Respect constraints: no application code yet; this is the plan document only.

## File to produce
- docs/superpowers/plans/2026-09-30-ecommerce-order-management.md

## Global constraints (extracted from spec)
- Backend-only pytest. No ORM (asyncpg, motor, AsyncElasticsearch).
- Money as strings across API; use Decimal for calculations. Snapshots immutable.
- Screens enforce data-source boundaries structurally.
- Outbox confined to Strategy A; sync_state only Strategy B; trigger owns updated_at/version.
- Docker topology: postgres, mongo, elasticsearch, rabbitmq (4 services). Apps on host.
- ES mapping uses scaled_float(100), object (not nested), prefix n-grams; index 'orders'.
- Strategy switch via ORDER_SYNC_STRATEGY=dual_write|polling.

## Review focus (5)
- Snapshot immutability: editing catalog must not change historical order items/ES docs.
- Versioned concurrency: external version on ES + PG version guard prevent stale overwrites.
- Polling watermark NULL-safety and 30s overlap with identical updated_at ties.
- Money correctness: Decimal quantized to cents end-to-end; uniform serialization.
- Data-source isolation: Screen 3 imports no PG/Mongo repositories.

## Suggested task breakdown (coarse)
1. Project skeleton: backend/app layout, config, requirements.txt
2. DB/clients: postgres (asyncpg), mongo (motor), es (AsyncElasticsearch), settings
3. SQL schema: 001_schema.sql (users/orders/order_items/outbox/sync_state/trigger/index)
4. Models/Pydantic + serialization helpers (Decimal as string)
5. Repos: users, products, orders, search, outbox, sync_state
6. ES mapping + search module
7. Services: order_service (branch by strategy), search_service, sync_service, outbox_service
8. Workers: celery_app, tasks (index_order/drain_outbox or poll)
9. API routers: products, orders, search, users, sync, health
10. Scripts: seed.py (deterministic plan + verifier), reindex_orders.py
11. Frontend skeleton: Vite/Vue3, Pinia, router, 5 views, stores, API layer
12. Docker: docker-compose.yml (4 services), env.example
13. Tests: order placement, snapshot, trigger, dual-write, polling, search, isolation, determinism
14. Docs: README, NOTES (milestones), Makefile (optional)

This writing notes file is just preparation; plan generation comes next.