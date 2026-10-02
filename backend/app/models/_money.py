"""The one definition of what money looks like.

Every monetary field in every model is annotated `Money`, which means:

* in Python it is a `Decimal` — never a `float`, so `0.1 + 0.2` cannot occur;
* in JSON it is a `str` — `150.50`, never `150.5`, so no JavaScript float and no
  disagreement between what Screen 3 and Screen 4 render for the same order;
* it is quantized to two places on the way out, so a value that arrived with
  spurious precision still serializes as exact cents.

The four store boundaries (Python, PostgreSQL `NUMERIC(12,2)`, MongoDB
`Decimal128`, Elasticsearch `scaled_float(100)`) are converted in the repository
layer, not here. This module is deliberately storage-agnostic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

CENTS = Decimal("0.01")


def quantize(value: Decimal) -> Decimal:
    """Round to cents using the rule humans and databases both use."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def to_money_str(value: Decimal) -> str:
    """`Decimal("150.5")` -> `"150.50"`. Always two places, never an exponent."""
    return format(quantize(value), "f")


Money = Annotated[
    Decimal,
    PlainSerializer(to_money_str, return_type=str, when_used="json"),
    Field(
        json_schema_extra={
            "type": "string",
            "pattern": r"^-?\d+\.\d{2}$",
            "examples": ["50.16"],
            "description": "Exact decimal amount as a string. Never a JSON float.",
        }
    ),
]
