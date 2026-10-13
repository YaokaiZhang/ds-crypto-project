#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .runtime
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/apps/backend:$PWD/packages"
export ANALYSIS_MODE=demo FEED_ENABLED=true
export DEMO_DATABASE_PATH="$PWD/.runtime/forecast-browser.sqlite3" FEED_DATABASE_PATH="$PWD/.runtime/feed.sqlite3"
python_bin="${CHAINRISK_PYTHON:-/scratch/project_2020551/miniconda3/bin/python}"
for service in api feed; do
  pidfile="$PWD/.runtime/$service.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$service already running: $(cat "$pidfile")"
    continue
  fi
  if [[ "$service" == api ]]; then
    nohup "$python_bin" -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000 >.runtime/api.log 2>&1 &
  else
    nohup "$python_bin" -m app.workers.feed >.runtime/feed.log 2>&1 &
  fi
  echo "$!" > "$pidfile"
  echo "$service started: $!"
done
