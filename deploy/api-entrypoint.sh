#!/bin/sh
set -eu

data_dir="${TRADINGAGENTS_HOME:-/home/appuser/.tradingagents}"
if [ ! -d "$data_dir" ] || [ ! -w "$data_dir" ]; then
  echo "Data directory $data_dir is missing or not writable by the API user." >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
