#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/infra/.env"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT/infra/docker-compose.yml")
fail=0

read_env() {
  grep -E "^$1=" "$ENV_FILE" | head -n 1 | cut -d= -f2-
}

env_or() {
  local value
  value="$(read_env "$1" || true)"
  printf '%s' "${value:-$2}"
}

export SUPERSET_HTTP_PORT="$(env_or SUPERSET_HTTP_PORT 8088)"
export AGENT_HTTP_PORT="$(env_or AGENT_HTTP_PORT 28088)"

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "OK   $name"
  else
    echo "FAIL $name"
    fail=1
  fi
}

check "Superset health" curl -fsS "http://localhost:$SUPERSET_HTTP_PORT/health"
check "Report worker running" bash -c \
  'test "$(docker inspect -f "{{.State.Running}}" assistant-superset-worker)" = "true"'
check "Report beat running" bash -c \
  'test "$(docker inspect -f "{{.State.Running}}" assistant-superset-beat)" = "true"'
check "Agent health" curl -fsS "http://localhost:$AGENT_HTTP_PORT/healthz"
check "Agent rejects anonymous /api/chat" bash -c \
  'test "$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:$AGENT_HTTP_PORT/api/chat" -H "content-type: application/json" -d "{}")" = "401"'
check "User history rejects anonymous" bash -c \
  'test "$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$AGENT_HTTP_PORT/api/conversations")" = "401"'
check "Admin page served" bash -c \
  'test "$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$AGENT_HTTP_PORT/admin")" = "200"'
check "Admin API rejects anonymous" bash -c \
  'test "$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$AGENT_HTTP_PORT/admin/api/me")" = "401"'
check "Admin session rejects missing ticket" bash -c \
  'test "$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:$AGENT_HTTP_PORT/admin/api/session" -H "content-type: application/json" -d "{}")" = "422"'
check "Extension token requires login" bash -c \
  'test "$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$SUPERSET_HTTP_PORT/extensions/dataagent/assistant/token")" != "200"'
check "MySQL databases reachable" "${COMPOSE[@]}" exec -T agent python -c '
import os
from urllib.parse import urlsplit
import pymysql
for key in ("SUPERSET_METADATA_URI", "DEMO_DB_URI", "ADMIN_DB_URL"):
    url = urlsplit(os.environ[key])
    if url.scheme not in ("mysql", "mysql+pymysql"):
        continue
    conn = pymysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.path.lstrip("/"),
    )
    conn.close()
'
check "Agent unit tests" "${COMPOSE[@]}" exec -T agent python -m pytest /app/tests -q -p no:cacheprovider

if grep -q '^AGENT_MOCK_LLM=true' "$ROOT/infra/.env"; then
  check "RLS smoke (east/west/admin)" python3 "$ROOT/scripts/smoke_chat.py"
  check "Audit log exists" test -f "$ROOT/infra/runtime/audit.jsonl"
else
  echo "SKIP RLS smoke: AGENT_MOCK_LLM is not true"
fi

if [ "$fail" -ne 0 ]; then
  echo "verification failed" >&2
  exit 1
fi
echo "all checks passed"
