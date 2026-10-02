"""A single customer. Lives in PostgreSQL — the catalog is MongoDB's alone."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str
    email: str
    created_at: datetime | None = None
