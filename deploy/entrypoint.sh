#!/usr/bin/env bash
# Single-container boot: init data dirs, start everything, seed once, stay up.
set -e
export PG_DSN="postgresql://ecommerce:ecommerce@127.0.0.1:5432/ecommerce"
export MONGO_DSN="mongodb://127.0.0.1:27017"
export MONGO_DB_NAME="ecommerce"
export ES_URL="http://127.0.0.1:9200"
export RABBITMQ_URL="amqp://guest:guest@127.0.0.1:5672//"
mkdir -p /data/pg /data/mongo /data/es /data/eslogs /data/rabbit /data/logs
chown -R es:es /data/es /data/eslogs
chown postgres:postgres /data/pg
mkdir -p /data/rabbit/mnesia /data/rabbit/log
chown -R rabbitmq:rabbitmq /data/rabbit

if [ ! -s /data/pg/PG_VERSION ]; then
  su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /data/pg -U postgres --auth=trust -E UTF8" >/data/logs/initdb.log 2>&1
fi
chown -R postgres:postgres /data/pg

supervisord -c /etc/supervisor/supervisord.conf &
SUP_PID=$!

for _ in $(seq 1 60); do
  su postgres -c "/usr/lib/postgresql/16/bin/pg_isready -h 127.0.0.1 -p 5432 -q" 2>/dev/null && break
  sleep 2
done
if ! psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='ecommerce'" | grep -q 1; then
  psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
CREATE ROLE ecommerce LOGIN PASSWORD 'ecommerce' SUPERUSER;
CREATE DATABASE ecommerce OWNER ecommerce;
SQL
fi
export PGPASSWORD=ecommerce
psql -h 127.0.0.1 -p 5432 -U ecommerce -d ecommerce -f /app/backend/sql/001_schema.sql >/dev/null

for _ in $(seq 1 45); do (exec 3<>/dev/tcp/127.0.0.1/27017) 2>/dev/null && break; sleep 2; done
for _ in $(seq 1 90); do curl -fsS http://127.0.0.1:9200/ >/dev/null 2>&1 && break; sleep 2; done
for _ in $(seq 1 45); do curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 2; done

USERS=$(psql -h 127.0.0.1 -p 5432 -U ecommerce -d ecommerce -tAc "SELECT count(*) FROM users" | tr -d ' ')
if [ "$USERS" = "0" ]; then
  cd /app/backend && /opt/venv/bin/python -m scripts.seed --reset >>/data/logs/seed.log 2>&1 || tail -20 /data/logs/seed.log
fi
echo "single container ready: users=$USERS"
wait "$SUP_PID"
