"""Background tasks. Thin Celery wrappers around `sync_service`.

`index_order` carries the exact `(order_id, outbox_id)` pair so the worker
settles only its own event. Retries come from the beat `drain_outbox`, not
from Celery redelivery loops: a stale version is terminal, an outage stays
pending in the outbox.
"""

from __future__ import annotations

import asyncio

from app.services import sync_service
from app.workers.celery_app import celery_app

#: One event loop for the lifetime of this worker process. `asyncio.run()`
#: would open a fresh loop per task and close it on return, but the asyncpg
#: pool, the Elasticsearch client and the Mongo client are cached
#: process-wide and bound to the loop they were created on — a closed loop
#: makes every later task fail with "Event loop is closed". Keeping one loop
#: alive means every task shares the same (open) loop as those clients.
_loop: asyncio.AbstractEventLoop | None = None


def _run(coro) -> object:
    """Run `coro` on the worker's persistent event loop."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


@celery_app.task(
    name="app.workers.tasks.index_order", acks_late=True, ignore_result=True
)
def index_order(order_id: int, outbox_id: int | None = None) -> None:
    _run(sync_service.index_order(order_id, outbox_id))


@celery_app.task(
    name="app.workers.tasks.drain_outbox", acks_late=True, ignore_result=True
)
def drain_outbox(limit: int = 100) -> dict:
    return _run(sync_service.drain_outbox(limit))
