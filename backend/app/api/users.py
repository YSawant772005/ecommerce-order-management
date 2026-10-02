"""Customer routes. PostgreSQL only."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.user import User

router = APIRouter()


@router.get("/users", response_model=list[User])
async def list_users() -> list[User]:
    from app.core.postgres import get_pool
    from app.repositories import users_repo

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await users_repo.list_users(conn)
    return [User.model_validate(r) for r in rows]
