"""Seed determinism: the construction plan is a pure function of inputs."""

from __future__ import annotations

from scripts.seed import build_order_plan


def test_plan_is_deterministic():
    a = build_order_plan(42, "2026-09-30T00:00:00Z")
    b = build_order_plan(42, "2026-09-30T00:00:00Z")
    assert a == b


def test_plan_depends_on_inputs():
    a = build_order_plan(42, "2026-09-30T00:00:00Z")
    assert build_order_plan(7, "2026-09-30T00:00:00Z") != a
    assert build_order_plan(42, "2026-10-15T00:00:00Z") != a


def test_plan_satisfies_slot_minimums():
    plan = build_order_plan(42, "2026-09-30T00:00:00Z")
    assert len(plan["orders"]) == 40
    statuses = [o["status"] for o in plan["orders"]]
    for s in ("PENDING", "PROCESSING", "SHIPPED"):
        assert statuses.count(s) >= 10
