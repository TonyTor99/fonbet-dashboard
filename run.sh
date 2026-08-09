#!/usr/bin/env bash
# Локальный запуск панели fonbet-dashboard.
# Останавливает старый процесс на порту 8080 и поднимает заново.
set -e
cd "$(dirname "$0")"

PORT=8080
fuser -k -n tcp $PORT 2>/dev/null || true
sleep 1

echo "Панель: http://localhost:$PORT"
exec ./venv/bin/uvicorn app:app --app-dir backend --host 0.0.0.0 --port $PORT
