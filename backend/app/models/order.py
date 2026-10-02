"""Order request and response models.

`OrderCreate` forbids extra keys on purpose. The client sends only `product_id`
and `quantity`; the server derives `title` and `unit_price` from MongoDB. If the
body were allowed to carry a price, the transaction would protect nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models._money import Money

OrderStatus = Literal["PENDING", "PROCESSING", "SHIPPED"]

#: Vocabulary of `POST /api/orders`. Deliberately NOT the badge vocabulary.
PlacementSyncStatus = Literal["QUEUED"]


class OrderItemIn(BaseModel):
    """One cart line as the client may describe it — nothing more."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    items: list[OrderItemIn] = Field(min_length=1)


class OrderItemOut(BaseModel):
    """A historical line. `title` and `unit_price` are snapshots, not live data."""

    product_id: str
    title: str
    quantity: int
    unit_price: Money


class OrderOut(BaseModel):
    """The 201 response. Says the event was queued, never that it was indexed."""

    order_id: int
    total_amount: Money
    status: OrderStatus
    sync_status: PlacementSyncStatus


class OrderDetail(BaseModel):
    """Screen 4, read from PostgreSQL only."""

    order_id: int
    user_id: int
    user_name: str
    user_email: str
    order_date: datetime
    updated_at: datetime
    status: OrderStatus
    total_amount: Money
    version: int
    items: list[OrderItemOut]


class StatusUpdate(BaseModel):
    """Guarded status change: the caller states the version it believes is current."""

    model_config = ConfigDict(extra="forbid")

    status: OrderStatus
    expected_version: int = Field(ge=1)
