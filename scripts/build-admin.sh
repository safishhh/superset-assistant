#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN="$ROOT/assistant-admin"

cd "$ADMIN"
if [ ! -d node_modules ]; then
  npm install --registry=https://registry.npmmirror.com
fi
npm run build
echo "built assistant-admin/dist"
