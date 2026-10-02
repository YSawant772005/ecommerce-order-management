"""FastAPI application factory. JSON only, no server-side HTML."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, orders, products, search, sync, users
from app.core.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the ES orders index exists. Best-effort: a down ES must not
    prevent the API from serving PG/Mongo reads."""
    try:
        from app.core.elasticsearch import ensure_orders_index

        await ensure_orders_index()
    except Exception:
        pass
    yield
    try:
        from app.core.elasticsearch import close_es
        from app.core.mongo import close_mongo
        from app.core.postgres import close_pool

        await close_es()
        await close_mongo()
        await close_pool()
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="E-commerce Order Management", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(products.router, prefix="/api", tags=["products"])
    app.include_router(users.router, prefix="/api", tags=["users"])
    app.include_router(orders.router, prefix="/api", tags=["orders"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(sync.router, prefix="/api", tags=["sync"])
    return app


app = create_app()
