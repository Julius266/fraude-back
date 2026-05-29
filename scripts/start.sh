#!/bin/sh
set -e

echo "Aplicando migraciones..."
python -m alembic upgrade head

PORT="${PORT:-8000}"
echo "Iniciando uvicorn en 0.0.0.0:${PORT}..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
