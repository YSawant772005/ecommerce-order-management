# Notes (5 learning milestones)

## 1. Split-brain (ES down 5 min, orders continue)

PG stays authoritative; Screen 4 correct, Screen 3 stale. Each order's
outbox row stays unprocessed with `attempts`/`last_error`. On recovery the
15s beat drain replays the gap; `POST /api/sync/reindex` repairs anything
terminal. Verified in `test_es_outage_is_retried_then_terminal`.

## 2. Why not SQL search

Screen 3 needs partial text (`Wir` → `Wireless Mouse`), faceted counts and
revenue over the filtered set. In PG that is `LIKE '%wir%'` (no B-Tree use)
plus a big join per keystroke. ES stores edge n-grams at index time and
computes `sum`/`terms` aggregations document-scoped, independent of paging.

## 3. Why MongoDB for the catalog

Variants arrays and sparse `attributes` (`dpi` vs `battery_hours` vs
`ports`) evolve per product. In PG that is EAV or nullable-column sprawl;
in Mongo it is one document, validated by `ProductCreate` (≥1 variant,
non-empty attributes) and enforced by the `sku` unique + compound indexes.

## 4. Snapshotting

`order_items.title`/`unit_price` are copied at checkout and immutable by DB
trigger. The seed renames `Wireless Mouse` → `Wireless Mouse Pro` @ 79.00
in Mongo only; every historical row and ES doc keeps `Wireless Mouse` @
50.16. An invoice must not re-read today's catalog.

## 5. Write-path discipline

Only `order_service` writes orders (one PG transaction). Screen 3 never
writes; Screen 4 writes PG status only; Screen 5 writes Mongo only
(AST-tested). Dual-writing orders into Mongo "for convenience" would fork
truth: two totals, two statuses, no trigger-owned version to arbitrate.

## A-queued vs A-inline vs B (analytic comparison, one code path)

| | A-queued (built) | A-inline (not built) | B polling (not built) |
|---|---|---|---|
| Order → searchable | ~1s | ms (inline call) | 0–15s tick |
| ES down at checkout | commits fine, recovers | checkout fails/slow | commits fine, drifts silently |
| Checkout depends on | PG only | PG + ES + network | PG only |
| Failure record | per-event outbox row | none (500 to shopper) | none |

A-inline pays ES latency on every checkout and turns search degradation
into order-placement degradation. B needs a watermark + overlap window and
records no per-event failure. A-queued is the measured middle.
