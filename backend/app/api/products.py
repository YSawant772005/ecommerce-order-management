"""Catalog routes. MongoDB only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.product import Product, ProductCreate, ProductUpdate

router = APIRouter()


@router.post("/products", response_model=Product, status_code=201)
async def create_product(product: ProductCreate) -> Product:
    from app.core.mongo import get_db
    from app.repositories.products_repo import DuplicateSku, ProductsRepo

    try:
        repo = ProductsRepo(await get_db())
        await repo.ensure_indexes()
        return await repo.create(product)
    except DuplicateSku as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/products/{product_id}", response_model=Product)
async def update_product(product_id: str, product: ProductUpdate) -> Product:
    from app.core.mongo import get_db
    from app.repositories.products_repo import DuplicateSku, ProductsRepo

    try:
        repo = ProductsRepo(await get_db())
        await repo.ensure_indexes()
        updated = await repo.update(product_id, product)
    except DuplicateSku as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"product {product_id} not found")
    return updated


@router.get("/products", response_model=list[Product])
async def list_products(
    category: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    search: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[Product]:
    from app.core.mongo import get_db
    from app.repositories.products_repo import ProductsRepo

    repo = ProductsRepo(await get_db())
    active: bool | None = None if include_inactive else True
    items, _ = await repo.list(
        search=search, category=category, active=active, skip=skip, limit=limit
    )
    return items


@router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str) -> Product:
    from app.core.mongo import get_db
    from app.repositories.products_repo import ProductsRepo

    product = await ProductsRepo(await get_db()).get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"product {product_id} not found")
    return product
