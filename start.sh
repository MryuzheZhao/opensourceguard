#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${1:-$ROOT/examples/buggy_csv}"
PORT="${2:-8787}"

if [[ -f "$ROOT/.env.local" ]]; then
  while IFS='=' read -r name value; do
    [[ "$name" =~ ^[[:space:]]*(OSG_|TYPESAFE_)[A-Za-z0-9_]*[[:space:]]*$ ]] || continue
    name="${name//[[:space:]]/}"
    value="${value%$'\r'}"
    value="${value#\"}"; value="${value%\"}"
    export "$name=$value"
  done < "$ROOT/.env.local"
fi

if [[ ! -d "$REPO" ]]; then
  echo "项目目录不存在：$REPO" >&2
  exit 1
fi

PYTHON="${OSG_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$PYTHON" ]]; then
  echo "没有找到 Python 3，请先安装 Python 3.10 或更高版本。" >&2
  exit 1
fi

cd "$ROOT"
"$PYTHON" -m opensourceguard.cli serve --repo "$REPO" --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

for _ in {1..40}; do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "OpenSourceGuard 已启动：http://127.0.0.1:$PORT/"
    if command -v open >/dev/null 2>&1; then
      open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 || true
    fi
    wait "$SERVER_PID"
    exit $?
  fi
  sleep 0.5
done
echo "服务启动超时，请检查端口 $PORT 或 Python 环境。" >&2
exit 1
