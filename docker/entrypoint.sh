#!/bin/sh
set -e

if [ -n "$DB_HOST" ]; then
    echo "Waiting for database at $DB_HOST:${DB_PORT:-5432}..."
    python - <<'PY'
import os, socket, sys, time

host = os.environ["DB_HOST"]
port = int(os.environ.get("DB_PORT", "5432"))
deadline = time.time() + 60
while True:
    try:
        socket.create_connection((host, port), timeout=3).close()
        break
    except OSError:
        if time.time() > deadline:
            sys.exit("Database %s:%s not reachable after 60s" % (host, port))
        time.sleep(1)
PY
fi

if [ "$SKIP_MIGRATE" != "1" ]; then
    python manage.py migrate --noinput
fi

if [ "$SKIP_COLLECTSTATIC" != "1" ]; then
    python manage.py collectstatic --noinput
fi

exec "$@"
