# Repository Audit — Phase 0

**Date:** 2026-09-30
**Branch:** `feature/strategy1-dual-write`
**Auditor:** implementing agent, before any application code was written

## 1. Current structure

```
ecommerce-order-management/
├── .gitignore                       # already present; .env/node_modules/dist/__pycache__ ignored
└── docs/
    ├── ecommerce-postgres-mongo-es.pdf                                    # the assignment (gitignored by design)
    ├── Ecommerce_Strategy_1_Dual_Write_Architecture_and_Workflow.docx    # Strategy 1 decision record (untracked at audit time)
    └── superpowers/
        ├── specs/2026-09-30-ecommerce-order-management-design.md          # approved design spec (676 lines)
        ├── plans/2026-09-30-ecommerce-order-management.md                 # approved implementation plan (1285 lines, 17 tasks)
        └── (no plans dir collision; no drafts)
```

**The repository contains documentation only.** There is no `backend/`, no `frontend/`,
no `docker-compose.yml`, no `.env.example`, no `Makefile`, no `README.md`, no `NOTES.md`,
no `sql/`, no `scripts/`, and no tests. Six commits exist, all docs-only:

| Commit | Message |
|---|---|
| `8022e61` | docs: resolve final review items in the implementation plan |
| `b370bc8` | docs: fix plan defects found in review |
| `f2935df` | docs: strengthen plan on isolation, PG version guard, money serialization |
| `3325c53` | docs: add implementation plan derived from the approved design spec |
| `be7aee7` | docs: correct product count in §18.2 (6+18+1=25) |
| `2e459ef` | docs: add design spec for order management POC |

## 2. Reusable files

| File | Reuse |
|---|---|
| `docs/superpowers/specs/…-design.md` | Authoritative schema (§7), MongoDB document shape (§8), Elasticsearch mapping (§9), API table (§10), order-placement flow (§11), seed rules (§18). Executed verbatim. |
| `docs/superpowers/plans/…-management.md` | The 17-task execution order with per-task files, interfaces, failing tests, and commit steps. Executed task-by-task. |
| `.gitignore` | Extended only with `.superpowers/` (the SDD ledger workspace). |
| `docs/ecommerce-postgres-mongo-es.pdf` | Assignment requirements (9 pages, read in full). |
| `docs/Ecommerce_…Workflow.docx` | Locks the deliverable to Strategy 1 only. |

## 3. Obsolete files

None. Nothing had to be deleted. The untracked `.docx` is the Strategy 1 decision record and
is **added to git**, not discarded.

## 4. Missing components

Everything the plan creates. Full list in the plan's *File Structure* section; summarised:

- **Infrastructure:** `docker-compose.yml`, `.env.example`, `Makefile`
- **Backend:** `backend/app/{main,core,api,models,services,repositories,workers,search}`, `backend/sql/001_schema.sql`, `backend/scripts/{seed,reindex_orders}.py`, `backend/tests/`
- **Frontend:** `frontend/` — Vite + Vue 3 + Router + Pinia, 5 views, 9 components, 5 stores, 4 API modules
- **Docs:** `README.md`, `NOTES.md`, `docs/IMPLEMENTATION_TODO.md`, this audit, `docs/FINAL_IMPLEMENTATION_AUDIT.md`

## 5. Conflicts with the architecture — and how each is resolved

| # | Conflict | Resolution |
|---|---|---|
| C1 | **The approved plan and spec implement two sync strategies (A `dual_write`, B `polling`)** behind `ORDER_SYNC_STRATEGY`, including a `sync_state` table, a watermark poller, `poll_orders`/`poll_once` tasks, `/api/sync/poll-once`, `/api/sync/reset-watermark`, `sync_state_repo`, `list_orders_updated_since`, and `test_sync_polling.py`. | **Ruled out.** The human partner's instruction and `docs/Ecommerce_Strategy_1_Dual_Write_Architecture_and_Workflow.docx` lock the deliverable to **Strategy 1 only — asynchronous queued dual-write**. All Strategy B artefacts are dropped. `ORDER_SYNC_STRATEGY` is retained but typed `Literal["dual_write"]`, so Strategy B is unconfigurable and a test proves `polling` is rejected. **Cost if wrong:** the assignment asks to "compare at least two" sync options; we implement one, and `NOTES.md` covers the comparison analytically (A-queued vs A-inline vs B) with no second code path. |
| C2 | **Docker is not installed** on this machine and `sudo` requires a password, so it cannot be installed non-interactively. The plan's Task 1 assumes `docker compose up -d`. | All four stores installed and run **natively**, at the exact major versions the plan specifies, via `~/.local/stack/stack.sh`: PostgreSQL **16.15**, MongoDB **7.0.14**, Elasticsearch **8.13.4**, RabbitMQ **3.12.14** (+ management plugin). `docker-compose.yml` is still authored and shipped, because it is a required deliverable. These are the **real** databases, not substitutes or mocks. **Cost if wrong:** the `docker compose` path is unexecuted on this machine; the code paths it would start are identical. |
| C3 | **A system PostgreSQL 18 service already occupies port 5432** (started at boot, not created by this project). | The project's PostgreSQL 16 runs on **55432** with its own data directory in `~/.local/stackdata/pgdata`. The system service is not touched, stopped, or reconfigured. **Cost if wrong:** none; `PG_DSN` is env-driven. |
| C4 | **Host Node is 18.19**, while current Vite majors require Node 20.19+. | Node **22.11.0** installed at `~/.local/stack/node22` and used for the frontend build. **Cost if wrong:** none; `frontend/package.json` declares no engine pin that would break on Node 18. |
| C5 | Assignment §"The Sync Challenge" asks to *"implement and compare at least two"* of A/B/C. | Same root cause as C1. Documented as an intentional deviation in `docs/FINAL_IMPLEMENTATION_AUDIT.md`, sourced to the human partner's explicit instruction. |

## 6. Environment verification (Phase 1 evidence, recorded early)

| Service | Version | Endpoint | Verified by |
|---|---|---|---|
| PostgreSQL | 16.15 | `127.0.0.1:55432` | `psql -tAc "select version()"` |
| MongoDB | 7.0.14 | `127.0.0.1:27017` | `mongod --version`, TCP connect, driver ping |
| Elasticsearch | 8.13.4 | `127.0.0.1:9200` | `GET /` returns 200 + cluster JSON |
| RabbitMQ | 3.12.14 | `127.0.0.1:5672`, mgmt `15672` | `rabbitmqctl version`, `rabbitmqctl status` listeners, `GET :15672/` → 200 |

Credentials: `postgresql://ecommerce:ecommerce@127.0.0.1:55432/ecommerce`,
`mongodb://127.0.0.1:27017`, `http://127.0.0.1:9200`, `amqp://guest:guest@127.0.0.1:5672//`.

## 7. Proposed implementation sequence

The approved plan's 17 tasks, unchanged in order, with Strategy B removed:

| # | Task | Note |
|---|---|---|
| 1 | Project skeleton, settings, Docker stores | stores come up natively |
| 2 | PostgreSQL schema + `orders_touch` trigger | |
| 3 | Mongo + ES clients, `orders` index | |
| 4 | Pydantic models, string money | |
| 5 | Repositories + data-source isolation | `sync_state_repo` dropped |
| 6 | Order placement transaction | strategy branch removed |
| 7 | Celery app, tasks, `build_order_document` | `poll_*` tasks dropped |
| 8 | API routers + app wiring | `poll-once`/`reset-watermark` routes dropped |
| 9 | Deterministic seed + 18-invariant verifier | |
| 10 | Reindex script | |
| 11 | Snapshot immutability test | |
| 12 | Search correctness test | |
| 13 | Dual-write sync tests | **polling half dropped** |
| 14 | Frontend skeleton | |
| 15 | The five screens | |
| 16 | Makefile, README, NOTES | strategy comparison reframed |
| 17 | Final verification gate | |
