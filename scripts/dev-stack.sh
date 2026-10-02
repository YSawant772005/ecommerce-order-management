#!/usr/bin/env bash
# Start / stop / inspect the four real data stores.
#
# Preferred path is `docker compose up -d` (see docker-compose.yml). On a host
# where Docker is unavailable this script runs the SAME four real services
# natively: PostgreSQL 16, MongoDB 7, Elasticsearch 8, RabbitMQ 3. Both paths
# give the application real databases over real sockets -- neither is a mock.
#
#   scripts/dev-stack.sh start|status|stop|logs
#
# Native layout:
#   binaries   ~/.local/stack        (postgres from the distro at /usr/lib/postgresql/16)
#   data       ~/.local/stackdata
#   logs       ~/.local/stackdata/logs
#
# PostgreSQL listens on 55432 because a system PostgreSQL already owns 5432 on
# this host and is left untouched. That is why backend/app/core/settings.py and
# .env.example default PG_DSN to port 55432.
set -uo pipefail

STACK="${STACK_DIR:-$HOME/.local/stack}"
DATA="${STACK_DATA_DIR:-$HOME/.local/stackdata}"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/16/bin}"
PGPORT="${PGPORT:-55432}"

export PGDATA="$DATA/pgdata"
export PGPORT
export PATH="$STACK/mongodb/bin:$STACK/elasticsearch/bin:$STACK/rabbitmq/bin:$STACK/erlang/bin:$PATH"
export ERL_ROOTDIR="$STACK/erlang"
export ERL_EPMD_ADDRESS=127.0.0.1
export RABBITMQ_NODENAME=rabbit@localhost
export RABBITMQ_MNESIA_BASE="$DATA/rabbitmq/mnesia"
export RABBITMQ_LOG_BASE="$DATA/rabbitmq/log"
export RABBITMQ_NODE_IP_ADDRESS=127.0.0.1
export RABBITMQ_NODE_PORT=5672
export RABBITMQ_CONFIG_FILE="$DATA/rabbitmq/rabbitmq"
export RABBITMQ_PID_FILE="$DATA/run/rabbitmq.pid"
export RABBITMQ_ENABLED_PLUGINS_FILE="$DATA/rabbitmq/enabled_plugins"

RUN="$DATA/run"
LOGS="$DATA/logs"
MONGO_DBPATH="$DATA/mongo"
EGDATA="$DATA/es"

mkdir -p "$RUN" "$LOGS" "$DATA/rabbitmq" "$MONGO_DBPATH" "$EGDATA"

_pg_ready()     { "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$PGPORT" -q >/dev/null 2>&1; }
_mongo_ready()  { (exec 3<>/dev/tcp/127.0.0.1/27017) 2>/dev/null && exec 3>&-; }
_es_ready()     { curl -fsS http://127.0.0.1:9200/ >/dev/null 2>&1; }
_rabbit_ready() { "$STACK/rabbitmq/bin/rabbitmq-diagnostics" -q ping >/dev/null 2>&1; }

start_postgres() {
  _pg_ready && { echo "postgres:      already up on $PGPORT"; return 0; }
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "postgres:      initdb"
    "$PG_BIN/initdb" -D "$PGDATA" -U postgres --auth-local=trust --auth-host=trust -E UTF8 \
      >"$LOGS/pg-initdb.log" 2>&1 || { echo "postgres:      initdb FAILED"; tail -20 "$LOGS/pg-initdb.log"; return 1; }
  fi
  "$PG_BIN/pg_ctl" -D "$PGDATA" -o "-p $PGPORT -h 127.0.0.1 -k $RUN" -l "$LOGS/postgres.log" -w start >/dev/null 2>&1
  for _ in $(seq 1 30); do _pg_ready && break; sleep 1; done
  _pg_ready || { echo "postgres:      FAILED"; tail -20 "$LOGS/postgres.log"; return 1; }
  if ! "$PG_BIN/psql" -h 127.0.0.1 -p "$PGPORT" -U postgres -d postgres -tAc \
       "SELECT 1 FROM pg_roles WHERE rolname='ecommerce'" 2>/dev/null | grep -q 1; then
    "$PG_BIN/psql" -h 127.0.0.1 -p "$PGPORT" -U postgres -d postgres -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
CREATE ROLE ecommerce LOGIN PASSWORD 'ecommerce' SUPERUSER;
CREATE DATABASE ecommerce OWNER ecommerce;
SQL
  fi
  echo "postgres:      up on $PGPORT (db ecommerce)"
}

start_mongo() {
  _mongo_ready && { echo "mongodb:       already up on 27017"; return 0; }
  "$STACK/mongodb/bin/mongod" --dbpath "$MONGO_DBPATH" --bind_ip 127.0.0.1 --port 27017 \
    --logpath "$LOGS/mongod.log" --fork >/dev/null 2>&1
  for _ in $(seq 1 30); do _mongo_ready && break; sleep 1; done
  _mongo_ready && echo "mongodb:       up on 27017" || { echo "mongodb:       FAILED"; tail -20 "$LOGS/mongod.log"; return 1; }
}

start_es() {
  _es_ready && { echo "elasticsearch: already up on 9200"; return 0; }
  mkdir -p "$EGDATA/data" "$EGDATA/logs"
  nohup "$STACK/elasticsearch/bin/elasticsearch" \
    -E path.data="$EGDATA/data" -E path.logs="$EGDATA/logs" \
    -E cluster.name=ecommerce-poc -E node.name=ecommerce-es-1 \
    -E discovery.type=single-node -E xpack.security.enabled=false \
    -E network.host=127.0.0.1 -E http.port=9200 >"$LOGS/es-console.log" 2>&1 &
  for _ in $(seq 1 90); do _es_ready && break; sleep 2; done
  _es_ready && echo "elasticsearch: up on 9200" || { echo "elasticsearch: FAILED"; tail -30 "$LOGS/es-console.log"; return 1; }
}

start_rabbit() {
  _rabbit_ready && { echo "rabbitmq:      already up on 5672 (mgmt 15672)"; return 0; }
  "$STACK/erlang/bin/epmd" -daemon >/dev/null 2>&1
  sleep 1
  nohup "$STACK/rabbitmq/bin/rabbitmq-server" >"$LOGS/rabbitmq.log" 2>&1 &
  for _ in $(seq 1 60); do _rabbit_ready && break; sleep 2; done
  if _rabbit_ready; then
    "$STACK/rabbitmq/bin/rabbitmq-plugins" enable rabbitmq_management >/dev/null 2>&1
    echo "rabbitmq:      up on 5672 (mgmt 15672)"
  else
    echo "rabbitmq:      FAILED"; tail -40 "$LOGS/rabbitmq.log"; return 1
  fi
}

status() {
  printf 'postgres:       '; _pg_ready      && echo UP || echo DOWN
  printf 'mongodb:        '; _mongo_ready   && echo UP || echo DOWN
  printf 'elasticsearch:  '; _es_ready      && echo UP || echo DOWN
  printf 'rabbitmq:       '; _rabbit_ready  && echo UP || echo DOWN
}

stop_all() {
  "$STACK/rabbitmq/bin/rabbitmqctl" stop >/dev/null 2>&1
  pkill -f 'org.elasticsearch.bootstrap.Elasticsearch' >/dev/null 2>&1
  "$STACK/mongodb/bin/mongod" --dbpath "$MONGO_DBPATH" --shutdown >/dev/null 2>&1
  "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast stop >/dev/null 2>&1
  echo "stack:          stopped"
}

case "${1:-start}" in
  start)  start_postgres; start_mongo; start_es; start_rabbit; status ;;
  pg)     start_postgres ;;
  mongo)  start_mongo ;;
  es)     start_es ;;
  rabbit) start_rabbit ;;
  status) status ;;
  stop)   stop_all ;;
  logs)   tail -n 60 "$LOGS"/*.log ;;
  *) echo "usage: $0 {start|pg|mongo|es|rabbit|status|stop|logs}"; exit 1 ;;
esac
