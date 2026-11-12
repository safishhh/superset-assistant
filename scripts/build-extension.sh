#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="$ROOT/assistant-ext/assistant"
CLI="${SUPERSET_EXTENSIONS_CLI:-$HOME/.local/bin/superset-extensions}"

if [ ! -x "$CLI" ]; then
  echo "superset-extensions CLI not found at $CLI" >&2
  exit 1
fi

cd "$EXT/frontend"
if [ ! -d node_modules ]; then
  npm install --registry=https://registry.npmmirror.com
fi

cd "$EXT"
"$CLI" validate
"$CLI" build
"$CLI" bundle

mkdir -p "$ROOT/infra/extensions"
SUPX="$(find "$EXT" -maxdepth 1 -name '*.supx' -type f | head -n 1)"
if [ -z "$SUPX" ]; then
  echo "no .supx produced" >&2
  exit 1
fi
cp -f "$SUPX" "$ROOT/infra/extensions/"

if [ ! -f "$EXT/dist/manifest.json" ]; then
  echo "manifest.json missing from extension dist" >&2
  exit 1
fi
if ! find "$EXT/dist/frontend" -type f -name '*.js' | grep -q .; then
  echo "frontend assets missing from extension dist" >&2
  exit 1
fi
echo "built $(basename "$SUPX")"
