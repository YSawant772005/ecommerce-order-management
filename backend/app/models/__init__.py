"""Pydantic models for the HTTP boundary.

Money is `Decimal` in Python and a **string** in JSON — one representation per
boundary, defined once in `_money.py` so no model can drift from it.
"""

from app.models.order import (
    OrderCreate,
    OrderDetail,
    OrderItemIn,
    OrderItemOut,
    OrderOut,
    StatusUpdate,
)
from app.models.product import Product, ProductCreate, ProductUpdate, Variant
from app.models.search import SearchHit, SearchRequest, SearchResponse
from app.models.sync import SyncStatusOut
from app.models.user import User

__all__ = [
    "OrderCreate",
    "OrderDetail",
    "OrderItemIn",
    "OrderItemOut",
    "OrderOut",
    "Product",
    "ProductCreate",
    "ProductUpdate",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    "StatusUpdate",
    "SyncStatusOut",
    "User",
    "Variant",
]
