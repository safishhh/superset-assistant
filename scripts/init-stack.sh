#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/infra/.env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT/infra/docker-compose.yml")

if [ ! -f "$ENV_FILE" ]; then
  echo "infra/.env is missing; copy infra/.env.example and fill it in" >&2
  exit 1
fi

read_env() {
  grep -E "^$1=" "$ENV_FILE" | head -n 1 | cut -d= -f2-
}

env_or() {
  local value
  value="$(read_env "$1" || true)"
  printf '%s' "${value:-$2}"
}

SUPERSET_HTTP_PORT="$(env_or SUPERSET_HTTP_PORT 8088)"
AGENT_HTTP_PORT="$(env_or AGENT_HTTP_PORT 28088)"
MCP_HTTP_PORT="$(env_or MCP_HTTP_PORT 25008)"

mkdir -p "$ROOT/infra/runtime" "$ROOT/infra/extensions"

# The Superset image is built from the in-repo source tree (never pulled).
if ! docker image inspect dataagent-superset:7.0-mysql >/dev/null 2>&1; then
  echo "==> dataagent-superset:7.0-mysql is missing; building from source"
  "$ROOT/scripts/build-superset.sh"
fi

if [ ! -f "$ROOT/assistant-ext/assistant/dist/manifest.json" ]; then
  echo "==> extension is not built; building"
  "$ROOT/scripts/build-extension.sh"
fi

if [ ! -f "$ROOT/assistant-admin/dist/index.html" ]; then
  echo "==> AI admin UI is not built; building"
  "$ROOT/scripts/build-admin.sh"
fi

# The old DataAgent stack is the previous implementation. Stop (do not remove)
# it only when it publishes the same Superset host port we are about to use.
if docker ps --format '{{.Names}}' | grep -qx 'dataagent-superset-1'; then
  old_ports="$(docker port dataagent-superset-1 8088/tcp 2>/dev/null || true)"
  if printf '%s\n' "$old_ports" | grep -q ":$SUPERSET_HTTP_PORT$"; then
    echo "==> stopping old dataagent Superset containers to free port $SUPERSET_HTTP_PORT"
    docker stop dataagent-superset-1 dataagent-superset-mcp-1 >/dev/null 2>&1 || true
  fi
fi

# Re-running this script is a refresh: stop our own app containers so the
# one-shot migration/seed commands do not fight the live SQLite writers.
if docker ps --format '{{.Names}}' | grep -qx 'assistant-superset'; then
  echo "==> stopping current assistant app containers for refresh"
  "${COMPOSE[@]}" stop superset superset-worker superset-beat superset-mcp agent >/dev/null 2>&1 || true
fi

listening="$(ss -ltn 2>/dev/null || true)"
if printf '%s\n' "$listening" | grep -q ":$SUPERSET_HTTP_PORT "; then
  echo "port $SUPERSET_HTTP_PORT is still in use; stop the process holding it first" >&2
  exit 1
fi

echo "==> starting Redis"
"${COMPOSE[@]}" up -d redis

echo "==> ensuring MySQL databases (skipped for SQLite URLs)"
"${COMPOSE[@]}" run --rm --no-deps \
  -v "$ROOT/scripts:/scripts:ro" \
  --entrypoint python superset /scripts/init_mysql.py

echo "==> upgrading metadata database"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint superset superset db upgrade

echo "==> creating admin (ignored if it already exists)"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint superset superset fab create-admin \
  --username "$(read_env SUPERSET_ADMIN_USERNAME)" \
  --firstname Admin --lastname User \
  --email "$(read_env SUPERSET_ADMIN_EMAIL)" \
  --password "$(read_env SUPERSET_ADMIN_PASSWORD)" || true

echo "==> initializing Superset roles and permissions"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint superset superset init

echo "==> seeding demo data, dataset, users, and RLS"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint python \
  superset /app/pythonpath/seed_superset.py

echo "==> starting Superset"
"${COMPOSE[@]}" up -d superset

echo "==> waiting for Superset HTTP on port $SUPERSET_HTTP_PORT"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$SUPERSET_HTTP_PORT/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "==> starting MCP, Agent, and report worker/beat"
"${COMPOSE[@]}" up -d superset-mcp agent superset-worker superset-beat

echo "==> waiting for Agent HTTP on port $AGENT_HTTP_PORT"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$AGENT_HTTP_PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

cat <<EOF

Ready:
  Superset  http://localhost:$SUPERSET_HTTP_PORT   $(read_env SUPERSET_ADMIN_USERNAME) / $(read_env SUPERSET_ADMIN_PASSWORD)
  Agent     http://localhost:$AGENT_HTTP_PORT/healthz
  MCP       http://localhost:$MCP_HTTP_PORT/mcp (debug only)

Demo users (password = username):
  east  -> RLS region = 'east'
  west  -> RLS region = 'west'

Run scripts/verify.sh for the smoke checks.
EOF
