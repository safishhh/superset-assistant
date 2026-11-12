#!/usr/bin/env bash
# 发布前检查：确认没有把密钥、运行数据、构建产物或个人信息提交进 git。
# 用法：git init && git add -A && bash scripts/check-release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "请先在仓库根目录执行 git init / git add，再运行本脚本。" >&2
  exit 1
fi

fail=0
say() { printf '\n== %s ==\n' "$1"; }

say "被跟踪的敏感/产物路径"
bad="$(git ls-files | grep -E \
  '(^|/)(node_modules|dist|__pycache__|\.pytest_cache)/|^infra/\.env$|^infra/runtime/|^infra/translations/|^infra/extensions/|^superset-7\.0\.0rc2/|^\.mimosa/|^vibe_images/|\.supx$|\.log$|\.db$' \
  || true)"
if [ -n "$bad" ]; then echo "$bad"; fail=1; else echo "OK"; fi

say "个人信息 / 凭证残留（只扫描已跟踪的文本文件）"
leaks="$(git ls-files -z \
  | grep -zv '^scripts/check-release.sh$' \
  | xargs -0 -r grep -InE \
    'BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|sk-[A-Za-z0-9]{16,}|/home/[a-z0-9_-]+/|[A-Za-z0-9._%+-]+@(163|qq|gmail|outlook|hotmail)\.(com|cn)' \
    2>/dev/null || true)"
if [ -n "$leaks" ]; then echo "$leaks"; fail=1; else echo "OK"; fi

say "关键初始化文件"
for f in \
  infra/.env.example \
  infra/seed_superset.py \
  scripts/init_mysql.py \
  scripts/init-stack.sh \
  agent-service/src/assistant_agent/admin/store.py; do
  if [ -f "$f" ]; then echo "OK  $f"; else echo "MISSING  $f"; fail=1; fi
done

exit "$fail"
