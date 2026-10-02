"""Sync badge vocabulary.

This is the **second** of two deliberately separate vocabularies:

* `POST /api/orders` answers `sync_status: QUEUED` — a statement about the
  *request*, made before any worker has run;
* `GET /api/sync/status/{order_id}` answers `state` — a statement about
  *reality*, comparing the committed PostgreSQL `version` against what
  Elasticsearch currently holds.

The creation response must never report `IN_SYNC`: the handler returns before
the worker runs, so it cannot know.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SyncState = Literal["IN_SYNC", "OUT_OF_SYNC", "MISSING_IN_ES"]


class SyncStatusOut(BaseModel):
    order_id: int
    state: SyncState
    pg_version: int
    es_version: int | None = None
    pending_outbox_events: int = 0
    last_error: str | None = None
