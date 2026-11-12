#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 默认用仓库内自带的 Superset 7.0.0rc2 源码树构建；可用 SUPERSET_SRC 覆盖，
# 例如 git clone --depth 1 --branch 4.0.0rc2 换其他版本源码。
SRC="${SUPERSET_SRC:-$ROOT/superset-7.0.0rc2}"

if [ ! -f "$SRC/setup.py" ] || [ ! -d "$SRC/superset-frontend" ]; then
  echo "superset source tree not found at $SRC" >&2
  echo "set SUPERSET_SRC=/path/to/superset-7.0.0rc2 (needs setup.py + superset-frontend/)" >&2
  exit 1
fi

echo "==> building dataagent-superset:7.0-mysql from $SRC"
echo "    (Node 前端编译 + pip 依赖安装，首次约 20-60 分钟；Docker 构建缓存命中时显著加速)"
docker build \
  -f "$ROOT/infra/Dockerfile.superset7" \
  --target superset-mysql \
  -t dataagent-superset:7.0-mysql \
  "$SRC"

echo "==> done: dataagent-superset:7.0-mysql"
docker image inspect dataagent-superset:7.0-mysql --format 'image {{.Id}} created {{.Created}}'
