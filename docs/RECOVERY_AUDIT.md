# Recovery Audit — Session 2

**Date:** 2026-09-30
**Branch:** `feature/strategy1-dual-write` (6 commits, all `docs:`; `main` untouched)
**Auditor:** implementing agent, resuming an interrupted session
**Method:** filesystem inspection, `git` inspection, live service probes, real database queries, real test run.
**Evidence rule:** every status below is backed by a command that was actually run in this session.

Status vocabulary: `IMPLEMENTED` · `PARTIAL` · `MISSING` · `BROKEN` · `BLOCKED`

---

## Summary of the recovery

The previous session completed **Phase 0 (planning + repository audit)** and began **Phase 1
(infrastructure)**. It wrote all four approved documents, brought the four real stores up
natively, created the Python virtualenv, and wrote `backend/requirements.txt` plus one RED test.

**It wrote no application code at all.** There is no `app/`, no `sql/`, no `docker-compose.yml`,
no `frontend/`, no `scripts/`, no schema, no seed, no tests beyond one file.

**First genuinely incomplete phase: Task 1 of the approved plan** (project skeleton, settings,
`docker-compose.yml`, `.env.example`, `tests/conftest.py`). The resume point is Task 1 Step 3.

---

## A. Environment status — `PARTIAL`

| Tool | Version | State |
|---|---|---|
| `python3` | 3.12.3 | `IMPLEMENTED` (spec floor is 3.11+) |
| `python` | — | `MISSING` — only `python3` exists; all commands use `python3` or the venv's `python` |
| `pip` | 24.0 (system) / 26.2.1 (venv) | `IMPLEMENTED` |
| `node` | **v18.19.1** | `PARTIAL` — too old for current Vite majors |
| `npm` | 9.2.0 | `IMPLEMENTED` |
| `docker` | — | **MISSING — `command not found`** |
| `docker compose` | — | **MISSING** (follows from the above) |
| `git` | 2.43.0 | `IMPLEMENTED` |

Mitigations already in place from the previous session:
- Node **22.11.0** installed at `~/.local/stack/node22` and used for the frontend build.
- Node 18 remains the host default.

Python dependencies: `backend/.venv` existed but was **empty** (only `pip`). Installed from
`backend/requirements.txt` in this session — all 39 packages resolved cleanly:

```
asyncpg 0.31.0 · motor 3.7.1 · pymongo 4.18.2 · elasticsearch 8.19.3 · celery 5.6.3
fastapi 0.142.1 · uvicorn 0.54.0 · pydantic 2.13.5 · pydantic-settings 2.15.0
pytest 9.1.1 · pytest-asyncio 1.4.0 · httpx 0.28.1 · faker 40.40.0
```

`elasticsearch 8.19.3` satisfies the plan's load-bearing `<9` ceiling.
`pytest-asyncio 1.4.0` is a major bump past the `>=0.24` floor; `asyncio_mode = "auto"` is
still supported, so the plan's test style is unaffected.

## B. Docker status — `BLOCKED`

`docker` is not installed and `sudo` requires an interactive password, so it cannot be
installed non-interactively.

Per `docs/REPOSITORY_AUDIT.md` §5 C2 (a ruling the previous session recorded and this session
re-verified), the four stores run **natively** at the exact major versions the plan specifies,
started by `~/.local/stack/stack.sh`. `docker-compose.yml` is still authored and shipped,
because it is a required assignment deliverable.

**These are the real databases, not substitutes, not mocks, not containers.** Verified below.

> Human action available: `sudo apt-get install -y docker.io docker-compose-v2` followed by
> adding `$USER` to the `docker` group. Not required for the deliverable to run.

## C. PostgreSQL status — `IMPLEMENTED` (empty)

- Version: **PostgreSQL 16.15** on `127.0.0.1:55432`, data dir `~/.local/stackdata/pgdata`.
  Port 55432 because a **system PostgreSQL 18 already owns 5432** and is deliberately left
  untouched (audit §5 C3).
- Credentials: `postgresql://ecommerce:ecommerce@127.0.0.1:55432/ecommerce`
- Probe: `psql -tAc "select version()"` → `PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)`
- `\dt` → **`Did not find any relations.`**

So: the server is up, the role and database exist, and the **schema is entirely absent**.
`users`, `orders`, `order_items`, `outbox` — none exist. This is Task 2, not started.

## D. MongoDB status — `IMPLEMENTED` (empty)

- Version: **MongoDB 7.0.14** on `127.0.0.1:27017`, dbpath `~/.local/stackdata/mongo`.
- Probe: `pymongo` `list_database_names()` → `['admin', 'config', 'local']`; `ping` → `{'ok': 1.0}`
- **No application database exists.** No `products` collection. The catalog is empty.

`mongosh` is not shipped in this MongoDB tarball (`bin/` contains only `mongod`, `mongos`,
`install_compass`). All catalog inspection therefore goes through `pymongo`, which is a real
driver against the real server.

## E. Elasticsearch status — `IMPLEMENTED` (empty)

- Version: **Elasticsearch 8.13.4** on `127.0.0.1:9200`, cluster `ecommerce-poc`, node `ecommerce-es-1`.
- Probe: `GET /` → 200 with full cluster JSON (`"number" : "8.13.4"`).
- `GET /_cat/indices?v` → **zero indices.**

The `orders` index does not exist. Nothing has ever been indexed.

## F. RabbitMQ status — `IMPLEMENTED` (empty)

- Version: **RabbitMQ 3.12.14**, listeners on `127.0.0.1:5672` (AMQP) and `127.0.0.1:15672` (management).
- Probe: `GET :15672/api/overview` → 200, `"management_version":"3.12.14"`.
- `GET :15672/api/queues` → **`[]`** — no queues, no exchanges, no Celery queue declared.

No Celery worker has ever run against this broker. Task 8 territory.

## G. Backend status — `MISSING`

Complete inventory of every file under `backend/` excluding `.venv`:

| File | State |
|---|---|
| `backend/requirements.txt` | `IMPLEMENTED` (14 lines, matches plan Task 1 Step 3) |
| `backend/.venv/` | `PARTIAL` — was empty; now populated by this session |
| `backend/tests/test_settings.py` | `IMPLEMENTED` as a RED test |
| `backend/app/**` | `MISSING` — no `__init__.py`, no `core/`, no `models/`, no `repositories/`, no `services/`, no `api/`, no `workers/`, no `search/` |
| `backend/sql/` | `MISSING` |
| `backend/scripts/` | `MISSING` |
| `backend/pyproject.toml` / `pytest.ini` | `MISSING` |

Real test run in this session, before any change:

```
$ cd backend && .venv/bin/python -m pytest tests/test_settings.py -v
tests/test_settings.py:1: in <module>
    from app.core.settings import get_settings, Settings
E   ModuleNotFoundError: No module named 'app.core.settings'
```

This matches the plan's Task 1 Step 2 `Expected:` exactly — the test is genuinely RED for the
right reason, not a false negative.

`test_settings.py` as written already encodes the Strategy 1 lock: it asserts the default is
`dual_write` **and** asserts that `ORDER_SYNC_STRATEGY=polling` raises `ValidationError`. Good.

## H. Celery status — `MISSING`

No `backend/app/workers/`, no `celery_app.py`, no `tasks.py`, no broker connectivity from
Python. The broker itself is healthy and empty.

## I. Frontend status — `MISSING`

No `frontend/` directory at all. No `package.json`, no `vite.config.js`, no Vue sources.
Node 22.11 is available to build it once it exists.

## J. Database data counts — actual, queried

| Store | Expected after seed | Actual now |
|---|---|---|
| PostgreSQL `users` | 8 | **table does not exist → 0** |
| PostgreSQL `orders` | 40 | **table does not exist → 0** |
| PostgreSQL `order_items` | ~85 | **table does not exist → 0** |
| PostgreSQL `outbox` | strategy rows | **table does not exist → 0** |
| MongoDB `products` | 25 (24 active + 1 inactive) | **collection does not exist → 0** |
| Elasticsearch `orders` index | 40 docs | **index does not exist → 0** |
| RabbitMQ queues | `celery` | **0** |

Every required dataset — 8 users, 25 products, 40 orders, the snapshot mismatch — is absent
because the schema, the seed script, and the index do not exist yet. Nothing is missing data;
the machinery that would produce it is missing.

## K. Implemented features

Only these, all from Phase 0/1:

1. `docs/superpowers/specs/2026-09-30-ecommerce-order-management-design.md` (676 lines) — approved design.
2. `docs/superpowers/plans/2026-09-30-ecommerce-order-management.md` (1285 lines, 17 tasks) — approved plan.
3. `docs/REPOSITORY_AUDIT.md` — the previous session's Phase 0 audit, with 5 recorded conflict rulings.
4. `docs/IMPLEMENTATION_TODO.md` — the previous session's phase tracker (superseded by this audit's rewrite).
5. `.superpowers/sdd/2026-09-30-ecommerce-order-management/progress.md` — the execution ledger.
6. `~/.local/stack/stack.sh` — the native four-service runtime.
7. `backend/requirements.txt`, `backend/.venv`, `backend/tests/test_settings.py`.

## L. Partially implemented features

1. **Phase 1 (infrastructure)** — stores are up and verified; `docker-compose.yml` and
   `.env.example` are **not** authored. `.venv` was empty; now populated.
2. **Task 1** — RED test and dependency manifest exist; `settings.py`, `conftest.py`,
   `pyproject.toml`, `docker-compose.yml`, `.env.example` do not.

## M. Missing features

Everything from Task 1 Step 3 onward:

- **Task 1** — `app/core/settings.py`, `tests/conftest.py`, `pyproject.toml` (`asyncio_mode=auto`),
  `docker-compose.yml`, `.env.example`.
- **Task 2** — `sql/001_schema.sql`, `app/core/postgres.py`, `orders_touch` trigger.
- **Task 3** — `app/core/mongo.py`, `app/core/elasticsearch.py`, `search/orders_mapping.json`.
- **Task 4** — all Pydantic models.
- **Task 5** — all seven repository modules, `search_service`, isolation test.
- **Task 6** — `order_service.place_order` / `update_status`.
- **Task 7** — `sync_service.build_order_document`, `outbox_service`, `celery_app`, `tasks`.
- **Task 8** — six routers, `main.py`, smoke tests.
- **Task 9** — `scripts/seed.py` + determinism and invariant tests.
- **Task 10** — `scripts/reindex_orders.py`.
- **Tasks 11–13** — snapshot, search, and sync test suites.
- **Tasks 14–15** — the entire frontend, five screens.
- **Tasks 16–17** — `Makefile`, `README.md`, `NOTES.md`, final gate.

## N. Broken features

**None.** Nothing was built, so nothing is broken. The one honest caveat: nothing has been
proven working, so "not broken" must not be read as "working".

## O. Existing tests

| File | Lines | State |
|---|---|---|
| `backend/tests/test_settings.py` | 22 | `IMPLEMENTED`, currently **RED** for the correct reason |

3 tests: default strategy is `dual_write`; `polling` is **rejected** with `ValidationError`;
the seed anchor default is `2026-09-30T00:00:00Z`.

## P. Failed tests

`tests/test_settings.py` — collection error, `ModuleNotFoundError: No module named
'app.core.settings'`. Expected for this point in the plan. No other test exists.

## Q. Frontend route status

`MISSING` — no frontend, therefore no routes. Spec §4 requires `/`, `/checkout`,
`/admin/orders`, `/admin/orders/:id`, `/admin/catalog`.

## R. Final recommended resume point

**Task 1, Step 3.** Dependencies are installed and the RED test is verified; the next
actions are `docker-compose.yml`, `.env.example`, `app/core/settings.py`,
`tests/conftest.py`, and `backend/pyproject.toml`.

Nothing needs to be repaired, reverted, or deleted. Nothing needs redesigning. The plan and
spec are internally consistent with the Strategy 1 lock already ruled into the ledger.

---

## Recorded rulings carried forward from the previous session (re-verified)

| # | Conflict | Ruling |
|---|---|---|
| C1 | The spec/plan implement **two** sync strategies behind `ORDER_SYNC_STRATEGY`; the Strategy 1 `.docx` and the human partner lock the deliverable to Strategy 1 only. | **Strategy B is dropped entirely.** `ORDER_SYNC_STRATEGY` is constrained to `Literal["dual_write"]`, so `polling` is unconfigurable, and `test_settings.py` asserts it raises `ValidationError`. The sync-options comparison is covered analytically in `NOTES.md` with no second code path. |
| C2 | Docker is not installed and needs `sudo`. | Four stores run natively via `~/.local/stack/stack.sh` at the exact specified major versions. `docker-compose.yml` is still shipped. |
| C3 | System PostgreSQL 18 owns port 5432. | Project PostgreSQL 16 runs on **55432** with its own data directory. The system service is untouched. |
| C4 | Host Node is 18.19; Vite majors need 20.19+. | Node 22.11 installed at `~/.local/stack/node22` for the build. |

## New ruling recorded in this session

**R6 — status-update route path.** The Strategy 1 `.docx` §20 lists `PATCH /api/orders/{id}`;
the approved spec §10 and the plan list `PATCH /api/orders/{id}/status`.
**Decided:** implement the spec's `/status` path. **Why:** the spec is the binding authority and
the human partner's recovery prompt §13/§16 also describes a status sub-resource.
**Cost if wrong:** one alias route, ~3 lines, added to `api/orders.py`.

**R7 — `sync_status` vocabulary.** The spec §11 fixes `POST /api/orders` to return exactly
`QUEUED` (Strategy A) and defines `IN_SYNC`/`OUT_OF_SYNC`/`MISSING_IN_ES` as badge states from
`GET /api/sync/status/{order_id}`. **Decided:** keep the two vocabularies separate exactly as
the spec says; the order-creation response never reports index success or failure.
**Cost if wrong:** one field's value set; no architectural impact.
