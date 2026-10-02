"""Order routes. PostgreSQL is the source of truth."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.order import OrderCreate, OrderDetail, OrderOut, StatusUpdate

router = APIRouter()


@router.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(req: OrderCreate) -> OrderOut:
    from app.services import order_service

    return await order_service.place_order(req)


@router.get("/orders/{order_id}", response_model=OrderDetail)
async def get_order(order_id: int) -> OrderDetail:
    from app.core.postgres import get_pool
    from app.repositories import orders_repo

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await orders_repo.fetch_order_row(conn, order_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"order {order_id} not found")
        items = await orders_repo.fetch_order_items(conn, order_id)
    return OrderDetail(
        order_id=row["id"],
        user_id=row["user_id"],
        user_name=row["customer_name"],
        user_email=row["customer_email"],
        order_date=row["order_date"],
        updated_at=row["updated_at"],
        status=row["status"],
        total_amount=row["total_amount"],
        version=row["version"],
        items=[
            {
                "product_id": i["product_id"],
                "title": i["title"],
                "quantity": i["quantity"],
                "unit_price": i["unit_price"],
            }
            for i in items
        ],
    )


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
async def patch_status(order_id: int, req: StatusUpdate) -> OrderOut:
    from app.services import order_service

    return await order_service.update_status(order_id, req.status, req.expected_version)
