#!/bin/sh
set -e
case "$1" in
  api)
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' \
      --workers "${API_WORKERS:-2}"
    ;;
  worker)
    exec python -m app.workers.main
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  test)
    shift
    exec python -m pytest "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
