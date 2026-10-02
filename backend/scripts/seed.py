"""Deterministic seed: 8 users, 25 products, 40 orders, ~85 items.

All randomness flows from `random.Random(seed)`; dates anchor to a constant,
never `datetime.now()`. `build_order_plan()` is pure (no DB, no clock) so
`test_seed_determinism.py` proves repeatability without containers.

Usage (from `backend/`):
    python -m scripts.seed --reset
    python -m scripts.seed --reset --seed 7 --anchor-date 2026-10-15T00:00:00Z
    python -m scripts.seed --verify-only
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone

ANCHOR_DEFAULT = "2026-09-30T00:00:00Z"

USERS = [
    ("John Doe", "john.doe@example.com"),
    ("Jane Smith", "jane.smith@example.com"),
    ("Wendy Wireless", "wendy.wireless@example.com"),
    ("Alex Rivera", "alex.rivera@example.com"),
    ("Sam Patel", "sam.patel@example.com"),
    ("Casey Nguyen", "casey.nguyen@example.com"),
    ("Morgan Lee", "morgan.lee@example.com"),
    ("Riley Brooks", "riley.brooks@example.com"),
]

NAMED_PRODUCTS = [
    {"sku": "WM-001", "title": "Wireless Mouse", "price": "50.16",
     "category": "peripherals", "tags": ["wireless", "usb", "office"],
     "attributes": {"color": "black", "dpi": 1600}},
    {"sku": "MK-002", "title": "Mechanical Keyboard", "price": "100.34",
     "category": "peripherals", "tags": ["keyboard", "rgb"],
     "attributes": {"switch": "brown", "layout": "TKL"},
     "variants": [{"sku": "MK-002-BRN", "color": "black", "stock": 20},
                  {"sku": "MK-002-RED", "color": "white", "stock": 15}]},
    {"sku": "WE-003", "title": "Wireless Earbuds", "price": "79.99",
     "category": "audio", "tags": ["wireless", "bluetooth"],
     "attributes": {"battery_hours": 24, "color": "white"}},
    {"sku": "UH-004", "title": "USB-C Hub 7-in-1", "price": "45.00",
     "category": "cables", "tags": ["usb-c", "hub"],
     "attributes": {"ports": "hdmi,usb-a,usb-c,sd,ethernet"}},
    {"sku": "DL-005", "title": "Desk Lamp LED", "price": "32.50",
     "category": "office", "tags": ["lamp", "led"],
     "attributes": {"color_temp": "3000K-6000K", "power": "12W"},
     "variants": [{"sku": "DL-005-WHT", "color": "white", "stock": 30},
                  {"sku": "DL-005-BLK", "color": "black", "stock": 25}]},
    {"sku": "NH-006", "title": "Noise Cancelling Headphones", "price": "199.00",
     "category": "audio", "tags": ["bluetooth", "anc"],
     "attributes": {"battery_hours": 40, "color": "black"}},
]

# 18 fillers: peripherals 4, audio 4, cables 5, office 5 -> 6 per category
# with the named ones. Cheap x5, premium x3 by construction.
FILLERS = [
    ("HDMI Cable 2m", "cables", "12.99", ["hdmi", "cable"], {"length_m": 2}),
    ("USB-C Cable 1m", "cables", "9.99", ["usb-c", "cable"], {"length_m": 1}),
    ("Wireless Charger Pad", "cables", "24.99", ["wireless", "charging"], {"watts": 15}),
    ("Ethernet Cable 5m", "cables", "14.99", ["ethernet", "cable"], {"length_m": 5}),
    ("Cable Organizer Kit", "cables", "19.99", ["organizer"], {"pieces": 20}),
    ("Mouse Pad XL", "peripherals", "22.99", ["desk"], {"size": "XL"}),
    ("Wireless Keyboard Mini", "peripherals", "59.99", ["wireless", "keyboard"], {"layout": "60%"}),
    ("Webcam 1080p", "peripherals", "69.99", ["video"], {"resolution": "1080p"}),
    ("Laptop Stand Aluminum", "peripherals", "39.99", ["stand"], {"material": "aluminum"}),
    ("Bluetooth Speaker", "audio", "89.99", ["wireless", "bluetooth"], {"watts": 20}),
    ("Wired Earbuds", "audio", "15.99", ["audio"], {"color": "black"}),
    ("Studio Monitor Headphones", "audio", "149.00", ["audio", "studio"], {"impedance": "32ohm"}),
    ("USB Microphone", "audio", "119.00", ["audio", "mic"], {"pattern": "cardioid"}),
    ("Notebook Set", "office", "18.99", ["paper"], {"count": 3}),
    ("Wireless Presenter", "office", "29.99", ["wireless", "office"], {"range_m": 30}),
    ("Desk Organizer", "office", "27.99", ["desk"], {"trays": 4}),
    ("Monitor Light Bar", "office", "49.99", ["lamp", "monitor"], {"power": "5W"}),
    ("Ergonomic Foot Rest", "office", "34.99", ["ergonomic"], {"material": "foam"}),
]

INACTIVE = {"sku": "OLD-999", "title": "Retired Dock", "price": "199.99",
            "category": "cables", "tags": ["retired"],
            "attributes": {"reason": "discontinued"}}

CATEGORIES = ["peripherals", "audio", "cables", "office"]


def _parse_anchor(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_order_plan(seed: int, anchor_date: str) -> dict:
    """Pure construction plan: 40 order slots with roles assigned.

    No DB, no clock, no module-level RNG: every draw comes from a local
    `random.Random(seed)`. Roles overlap by design (40 slots, ~71 role
    minimums); the verifier in this module checks the persisted result.
    """
    rng = random.Random(seed)
    anchor = _parse_anchor(anchor_date)
    statuses = (["PENDING"] * 14 + ["PROCESSING"] * 13 + ["SHIPPED"] * 13)
    rng.shuffle(statuses)

    # Product indices: 0=WM, 1=keyboard; fillers start at 6.
    cheap = [6, 7, 8, 9, 10, 11, 16, 19]   # all <$25 fillers
    premium = [1, 5, 17, 18]                # all >=$100 (for the >$200 band)
    orders: list[dict] = []

    def lines_for(kind: str) -> list[tuple[int, int]]:
        if kind == "cheap":
            # Single unit of a sub-$25 filler: total always lands under $30.
            return [(rng.choice(cheap), 1)]
        if kind == "rich":
            p1, p2 = rng.sample(premium, 2)
            return [(p1, 2), (p2, 1)]
        n = rng.choice([1, 2, 2, 3, 4])
        pool = [0, 1, 2, 3, 4, 5] + list(range(6, 24))
        picks = rng.sample(pool, min(n, len(pool)))
        return [(p, rng.randint(1, 3)) for p in picks]

    # Forced fixtures first (indices into orders).
    wm_orders = rng.sample(range(40), 8)
    kb_pool = [i for i in range(40) if i not in wm_orders]
    kb_orders = rng.sample(kb_pool, 3)
    both = rng.sample(wm_orders, 2)
    for i in both:
        kb_orders.append(i)
    wendy_orders = rng.sample(range(40), 5)
    # Old orders belong to Riley/Morgan (date-range edge), never to Wendy:
    # her 5 orders and wireless fixture stay intact.
    old_orders = rng.sample([i for i in range(40) if i not in wendy_orders], 5)
    new_orders = rng.sample([i for i in range(40) if i not in old_orders], 5)
    taken = set(wm_orders) | set(kb_orders)
    # Cheap/rich bands must survive intact: no fixture lines, no Wendy top-up.
    plain = [i for i in range(40) if i not in taken and i not in wendy_orders]
    cheap_orders = rng.sample(plain, 5)
    rich_orders = rng.sample([i for i in plain if i not in cheap_orders], 5)
    one_item = rng.choice(range(40))
    many_item = rng.choice([i for i in range(40) if i != one_item])

    for i in range(40):
        user_idx = i % 8
        if i in wm_orders and i in kb_orders:
            lines = [(0, 1), (1, 1)] + lines_for("mid")[:1]
        elif i in wm_orders:
            lines = [(0, rng.randint(1, 2))] + (lines_for("mid")[:1] if rng.random() < 0.5 else [])
        elif i in kb_orders:
            lines = [(1, 1)] + (lines_for("mid")[:1] if rng.random() < 0.5 else [])
        elif i in cheap_orders:
            lines = lines_for("cheap")
        elif i in rich_orders:
            lines = lines_for("rich")
        elif i == one_item:
            lines = [(rng.randrange(24), 1)]
        elif i == many_item:
            lines = [(p, rng.randint(1, 2)) for p in rng.sample(range(24), 4)]
        else:
            lines = lines_for("mid")
        if i in wendy_orders:
            user_idx = 2
        elif i in old_orders:
            # Date-range edge belongs to Riley Brooks / Morgan Lee.
            user_idx = 7 if old_orders.index(i) % 2 == 0 else 6
        if i in wendy_orders[:3] and not any(p in (0, 2, 8, 12, 15, 20) for p, _ in lines):
            lines = [(2, 1)] + lines
        if i in old_orders:
            day = rng.randint(61, 90)
        elif i in new_orders:
            day = rng.randint(0, 6)
        else:
            day = rng.randint(7, 60)
        orders.append({
            "user_idx": user_idx,
            "lines": lines,
            "status": statuses[i],
            "date": (anchor - timedelta(days=day)).isoformat(),
        })
    return {"seed": seed, "anchor_date": anchor_date, "orders": orders}


def _product_docs(rng: random.Random, faker) -> list[dict]:
    from decimal import Decimal

    from bson.decimal128 import Decimal128

    docs = []
    for spec in NAMED_PRODUCTS + [
        {"sku": t, "title": t, "price": p, "category": c, "tags": tg, "attributes": at}
        for (t, c, p, tg, at) in FILLERS
    ]:
        variants = spec.get("variants") or [
            {"sku": f"{spec['sku']}-V1", "color": "black",
             "stock": rng.randint(5, 50)}
        ]
        docs.append({
            "sku": spec["sku"], "title": spec["title"],
            "description": faker.sentence(),
            "price": Decimal128(str(Decimal(spec["price"]))),
            "category": spec["category"], "tags": spec["tags"],
            "attributes": spec["attributes"],
            "variants": variants,
            "active": True, "updated_at": datetime.now(timezone.utc),
        })
    docs.append({
        "sku": INACTIVE["sku"], "title": INACTIVE["title"],
        "description": faker.sentence(),
        "price": Decimal128(str(INACTIVE["price"])),
        "category": INACTIVE["category"], "tags": INACTIVE["tags"],
        "attributes": INACTIVE["attributes"],
        "variants": [{"sku": "OLD-999-V1", "color": "grey", "stock": 0}],
        "active": False, "updated_at": datetime.now(timezone.utc),
    })
    return docs


async def _reset(pg_pool, mongo_db, es_client, index: str) -> None:
    await pg_pool.execute("TRUNCATE order_items, outbox, orders, users RESTART IDENTITY CASCADE")
    await mongo_db.products.drop()
    if await es_client.indices.exists(index=index):
        await es_client.indices.delete(index=index)


async def run_seed(seed: int, anchor_date: str, reset: bool) -> dict:
    """Write all stores from the plan. Returns the invariant report."""
    import asyncpg
    from elasticsearch import AsyncElasticsearch
    from faker import Faker
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.core.settings import get_settings

    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed)
    plan = build_order_plan(seed, anchor_date)
    settings = get_settings()

    pg_pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=5)
    mongo = AsyncIOMotorClient(settings.mongo_dsn)
    mongo_db = mongo[settings.mongo_db_name]
    es_client = AsyncElasticsearch(settings.es_url, request_timeout=30)
    try:
        from app.core.elasticsearch import ensure_orders_index

        if reset:
            await _reset(pg_pool, mongo_db, es_client, settings.es_orders_index)
        await ensure_orders_index()

        async with pg_pool.acquire() as conn:
            user_ids = [
                await conn.fetchval(
                    "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
                    name, email,
                )
                for name, email in USERS
            ]
        docs = _product_docs(rng, fake)
        await mongo_db.products.insert_many(docs)
        from app.repositories.products_repo import ProductsRepo

        await ProductsRepo(mongo_db).ensure_indexes()
        catalog = await mongo_db.products.find({"active": True}).to_list(length=30)
        by_title = {d["title"]: d for d in catalog}
        prices = {d["title"]: d["price"].to_decimal() for d in catalog}

        from decimal import Decimal

        from app.models._money import quantize

        order_ids = []
        async with pg_pool.acquire() as conn:
            for spec in plan["orders"]:
                # Resolve product index -> snapshot from the live catalog.
                lines = []
                total = Decimal("0")
                for p_idx, qty in spec["lines"]:
                    title = _title_for(p_idx)
                    unit = prices[title]
                    lines.append((str(by_title[title]["_id"]), title, qty, unit))
                    total += unit * qty
                total = quantize(total)
                oid = await conn.fetchval(
                    "INSERT INTO orders (user_id, order_date, status, total_amount)"
                    " VALUES ($1, $2, $3, $4) RETURNING id",
                    user_ids[spec["user_idx"]],
                    datetime.fromisoformat(spec["date"]), spec["status"], total,
                )
                await conn.executemany(
                    "INSERT INTO order_items (order_id, product_id, title, quantity, unit_price)"
                    " VALUES ($1, $2, $3, $4, $5)",
                    [(oid, pid, t, q, u) for pid, t, q, u in lines],
                )
                order_ids.append(oid)

        from app.services.sync_service import build_order_document

        async with pg_pool.acquire() as conn:
            for oid in order_ids:
                doc = await build_order_document(conn, oid)
                pg_version = doc["version"]
                await es_client.index(
                    index=settings.es_orders_index, id=str(oid), document=doc,
                    version=pg_version, version_type="external",
                )
        await es_client.indices.refresh(index=settings.es_orders_index)
        # Snapshot-mismatch fixture: MongoDB only.
        await mongo_db.products.update_one(
            {"sku": "WM-001"},
            {"$set": {"title": "Wireless Mouse Pro", "price": __import__("bson").Decimal128("79.00")}},
        )
        return await verify(pg_pool, mongo_db, es_client, settings.es_orders_index)
    finally:
        await es_client.close()
        mongo.close()
        await pg_pool.close()


def _title_for(idx: int) -> str:
    if idx < 6:
        return NAMED_PRODUCTS[idx]["title"]
    t, _, _, _, _ = FILLERS[idx - 6]
    return t


async def verify(pg_pool, mongo_db, es_client, index: str) -> dict:
    """Re-read all three stores; every invariant must hold. Raises on failure."""
    from decimal import Decimal

    failures: list[str] = []
    report: dict[str, object] = {}

    def check(name: str, ok: bool, detail: object = "") -> None:
        report[name] = detail
        if not ok:
            failures.append(f"{name}: {detail}")

    n_users = await pg_pool.fetchval("SELECT count(*) FROM users")
    check("8 users", n_users == 8, n_users)
    n_products = await mongo_db.products.count_documents({})
    n_active = await mongo_db.products.count_documents({"active": True})
    check("25 products / 24 active", (n_products, n_active) == (25, 24), (n_products, n_active))
    for cat in CATEGORIES:
        n = await mongo_db.products.count_documents({"category": cat, "active": True})
        check(f"category {cat} >= 5", n >= 5, n)
    wireless = await mongo_db.products.count_documents(
        {"active": True, "$or": [{"title": {"$regex": "wireless", "$options": "i"}},
                                 {"tags": {"$regex": "^wireless$", "$options": "i"}}]}
    )
    check("wireless >= 6", wireless >= 6, wireless)
    bands = {"cheap": 0, "mid": 0, "premium": 0}
    async for d in mongo_db.products.find({"active": True}):
        p = float(d["price"].to_decimal())
        bands["cheap" if p < 25 else "mid" if p < 100 else "premium"] += 1
    check("price bands >= 4", all(v >= 4 for v in bands.values()), bands)
    n_orders = await pg_pool.fetchval("SELECT count(*) FROM orders")
    check("40 orders", n_orders == 40, n_orders)
    bands_o = await pg_pool.fetchrow(
        "SELECT count(*) FILTER (WHERE total_amount < 30) AS cheap,"
        " count(*) FILTER (WHERE total_amount BETWEEN 30 AND 150) AS mid,"
        " count(*) FILTER (WHERE total_amount > 200) AS premium FROM orders"
    )
    check("order bands >= 5", all(bands_o[k] >= 5 for k in ("cheap", "mid", "premium")),
          dict(bands_o))
    for st in ("PENDING", "PROCESSING", "SHIPPED"):
        n = await pg_pool.fetchval("SELECT count(*) FROM orders WHERE status=$1", st)
        check(f"status {st} >= 10", n >= 10, n)
    rows = await pg_pool.fetch(
        "SELECT id, total_amount FROM orders WHERE total_amount != "
        "(SELECT COALESCE(SUM(quantity * unit_price), 0) FROM order_items WHERE order_id = orders.id)"
    )
    check("totals == sum(lines)", len(rows) == 0, len(rows))
    n_items = await pg_pool.fetchval("SELECT count(*) FROM order_items")
    check("~85 items, avg >= 2", n_items >= 80, n_items)
    wm = await pg_pool.fetchval(
        "SELECT count(DISTINCT order_id) FROM order_items WHERE title='Wireless Mouse'")
    check("WM orders >= 8", wm >= 8, wm)
    kb = await pg_pool.fetchval(
        "SELECT count(DISTINCT order_id) FROM order_items WHERE title='Mechanical Keyboard'")
    check("keyboard orders >= 3", kb >= 3, kb)
    both = await pg_pool.fetchval(
        "SELECT count(*) FROM orders o WHERE EXISTS "
        "(SELECT 1 FROM order_items WHERE order_id=o.id AND title='Wireless Mouse')"
        " AND EXISTS (SELECT 1 FROM order_items WHERE order_id=o.id"
        " AND title='Mechanical Keyboard')")
    check("both >= 2", both >= 2, both)
    wendy_wireless = await pg_pool.fetchval(
        "SELECT count(DISTINCT o.id) FROM orders o JOIN users u ON u.id=o.user_id"
        " WHERE u.email='wendy.wireless@example.com' AND EXISTS "
        "(SELECT 1 FROM order_items WHERE order_id=o.id AND title IN "
        "('Wireless Mouse','Wireless Earbuds','Wireless Charger Pad',"
        "'Wireless Keyboard Mini','Bluetooth Speaker','Wireless Presenter'))")
    check("wendy wireless orders >= 3", wendy_wireless >= 3, wendy_wireless)
    kb_doc = await mongo_db.products.find_one({"sku": "MK-002"})
    check("keyboard >= 2 variants", len(kb_doc.get("variants", [])) >= 2,
          len(kb_doc.get("variants", [])))
    lamp_doc = await mongo_db.products.find_one({"sku": "DL-005"})
    lamp_colors = {v.get("color") for v in lamp_doc.get("variants", [])}
    check("lamp >= 2 color variants", len(lamp_colors) >= 2, sorted(lamp_colors))
    wm_doc = await mongo_db.products.find_one({"sku": "WM-001"})
    check("WM tags/attrs", "wireless" in wm_doc["tags"]
          and "color" in wm_doc["attributes"] and "dpi" in wm_doc["attributes"],
          (wm_doc["tags"], sorted(wm_doc["attributes"])))
    shape_ok = True
    async for d in mongo_db.products.find({}):
        if not all(k in d for k in ("sku", "title", "description", "price", "category",
                                    "tags", "attributes", "variants", "active", "updated_at")):
            shape_ok = False
        if not d.get("attributes") or not d.get("variants"):
            shape_ok = False
    check("ten fields + attrs + variants everywhere", shape_ok, "")
    if await es_client.indices.exists(index=index):
        es_count = (await es_client.count(index=index))["count"]
    else:
        es_count = -1
    check("ES caught up", es_count == n_orders, (es_count, n_orders))
    cat = await mongo_db.products.find_one({"sku": "WM-001"})
    hist = await pg_pool.fetchval(
        "SELECT count(*) FROM order_items WHERE title='Wireless Mouse'")
    check("snapshot mismatch", cat["title"] == "Wireless Mouse Pro" and hist == wm,
          (cat["title"], hist))
    if failures:
        raise SystemExit("SEED VERIFY FAILED:\n- " + "\n- ".join(failures))
    return report


async def _verify_only() -> dict:
    import asyncpg
    from elasticsearch import AsyncElasticsearch
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.core.settings import get_settings

    settings = get_settings()
    pg_pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=5)
    mongo = AsyncIOMotorClient(settings.mongo_dsn)
    es_client = AsyncElasticsearch(settings.es_url, request_timeout=30)
    try:
        return await verify(pg_pool, mongo[settings.mongo_db_name],
                            es_client, settings.es_orders_index)
    finally:
        await es_client.close()
        mongo.close()
        await pg_pool.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--anchor-date", default=ANCHOR_DEFAULT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only:
        report = asyncio.run(_verify_only())
    else:
        report = asyncio.run(run_seed(args.seed, args.anchor_date, args.reset))
    for name, detail in report.items():
        print(f"{name}: {detail}")


if __name__ == "__main__":
    main()
