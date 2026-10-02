"""Admin order search request and response.

Every field in `SearchHit` is read from **Elasticsearch only**. There is no
PostgreSQL join behind this model and no MongoDB lookup: the projection was
built from committed PostgreSQL rows by `build_order_document()` at index time.

Money arrives here from an Elasticsearch `scaled_float(100)`, so
`total_amount` and `items[].unit_price` are re-quantized to `Decimal` cents by
`search_repo` before validation. Without that, Screen 3 would render `$150.5`
while Screen 4 rendered `$150.50` for the same order.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models._money import Money
from app.models.order import OrderItemOut
from app.models.user import User


class SearchRequest(BaseModel):
    """The admin search filter object. `POST` because the body is complex."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200)
    statuses: list[str] = Field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    price_min: Money | None = None
    price_max: Money | None = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class SearchHit(BaseModel):
    """One indexed order. Field names match `build_order_document()` exactly."""

    order_id: int
    status: str
    total_amount: Money
    order_date: datetime
    updated_at: datetime
    version: int
    customer: User
    items: list[OrderItemOut]


class SearchResponse(BaseModel):
    """Hits plus aggregations.

    `revenue` and `status_facets` come from Elasticsearch aggregations computed
    over the **whole filtered result set**, independent of `page`/`size`. They
    are never summed in Python from the returned page.
    """

    total: int
    page: int
    size: int
    revenue: Money
    status_facets: dict[str, int] = Field(default_factory=dict)
    hits: list[SearchHit] = Field(default_factory=list)
