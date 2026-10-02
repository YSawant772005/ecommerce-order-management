-- PostgreSQL schema for the e-commerce order management POC.
--
-- PostgreSQL is the source of truth for orders, order items, users, status,
-- money and fulfillment. Nothing here is derived from MongoDB, and nothing
-- here is a search projection.
--
-- Written idempotently because conftest applies this file on every test
-- session: CREATE TABLE IF NOT EXISTS, CREATE INDEX IF NOT EXISTS,
-- CREATE OR REPLACE FUNCTION, and DROP TRIGGER IF EXISTS before CREATE TRIGGER.

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  email      TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- orders
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES users(id),
  order_date   TIMESTAMPTZ NOT NULL DEFAULT now(),
  status       TEXT NOT NULL CHECK (status IN ('PENDING','PROCESSING','SHIPPED')),
  total_amount NUMERIC(12,2) NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  version      INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- order_items
--
-- `title` and `unit_price` are SNAPSHOTS captured from the MongoDB catalog at
-- checkout. A later catalog edit must never rewrite a financial record, so the
-- database refuses to change these two columns at all (see
-- order_items_snapshot_immutable() below).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items (
  id         BIGSERIAL PRIMARY KEY,
  order_id   BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL,
  title      TEXT NOT NULL,
  quantity   INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(12,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS order_items_order_id_idx ON order_items (order_id);

-- ---------------------------------------------------------------------------
-- outbox  (Strategy 1 durability)
--
-- Written INSIDE the order transaction, so "PostgreSQL committed" and
-- "Elasticsearch will hear about it" are a single atomic fact. Without it, a
-- RabbitMQ outage at dispatch time would lose the index intent permanently.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outbox (
  id           BIGSERIAL PRIMARY KEY,
  aggregate_id BIGINT NOT NULL,
  event_type   TEXT NOT NULL CHECK (event_type IN ('ORDER_CREATED','ORDER_STATUS_CHANGED')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,
  attempts     INTEGER NOT NULL DEFAULT 0,
  last_error   TEXT
);

-- The drain query only ever looks at unprocessed rows.
CREATE INDEX IF NOT EXISTS outbox_unprocessed_idx ON outbox (created_at) WHERE processed_at IS NULL;

-- ---------------------------------------------------------------------------
-- orders_touch: the trigger owns updated_at and version
--
-- Elasticsearch stale-write protection keys on `version`, so `version` must be
-- correct for every mutation of an order -- including mutations written by code
-- that does not exist yet. Letting the database own it makes that structural
-- instead of a review convention: no UPDATE path can forget to bump it.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION orders_touch() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  NEW.version    := OLD.version + 1;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS orders_touch_trg ON orders;
CREATE TRIGGER orders_touch_trg BEFORE UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION orders_touch();

-- ---------------------------------------------------------------------------
-- order_items_snapshot_immutable
--
-- An invoice is a financial record. `title` and `unit_price` are copied from
-- the catalog at checkout precisely so that editing a product later cannot
-- silently rewrite what the customer was charged. Enforcing that with a
-- database refusal, rather than with a code-review rule, means the guarantee
-- survives any future code path.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION order_items_snapshot_immutable() RETURNS trigger AS $$
BEGIN
  IF NEW.title IS DISTINCT FROM OLD.title OR NEW.unit_price IS DISTINCT FROM OLD.unit_price THEN
    RAISE EXCEPTION
      'order_items snapshot is immutable: title and unit_price are captured at checkout and never rewritten (order_id=%, product_id=%)',
      OLD.order_id, OLD.product_id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS order_items_snapshot_immutable_trg ON order_items;
CREATE TRIGGER order_items_snapshot_immutable_trg BEFORE UPDATE ON order_items
  FOR EACH ROW EXECUTE FUNCTION order_items_snapshot_immutable();
