"""PostgreSQL access for users. Read-only for the slice."""

from __future__ import annotations

import asyncpg


async def list_users(conn: asyncpg.Connection) -> list[dict]:
    """All customers for the Log In As dropdown, ordered by id."""
    rows = await conn.fetch("SELECT id, name, email FROM users ORDER BY id")
    return [{"id": r["id"], "name": r["name"], "email": r["email"]} for r in rows]
