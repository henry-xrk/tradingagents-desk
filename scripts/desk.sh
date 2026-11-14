#!/bin/sh
# Research desk maintenance. Each command stops on its own failure.
# This script does not stash, reset, clean, or pull during container start.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
compose="docker compose -f compose.desk.yml"
data_dir="${DESK_DATA_DIR:-$root/data/desk}"
db="$data_dir/dashboard/research.db"

die() {
  echo "desk: $*" >&2
  exit 1
}

require_clean() {
  if [ -n "$(git status --porcelain)" ]; then
    die "working tree is dirty. Commit or set aside your changes manually; this script will not stash or reset."
  fi
}

backup_db() {
  [ -f "$db" ] || die "no dashboard database at $db"
  stamp=$(date +%Y%m%d-%H%M%S)
  dest="$root/data/backups/$stamp"
  mkdir -p "$dest"
  python3 - "$db" "$dest/research.db" << 'PY'
import sqlite3, sys
source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
with target:
    source.backup(target)
target.close()
source.close()
PY
  echo "$dest/research.db"
}

active_runs() {
  python3 - << 'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:5173/api/analyses/active", timeout=5) as response:
        rows = json.load(response)
except Exception as exc:
    print(f"desk: could not read active research ({exc})", file=sys.stderr)
    sys.exit(2)
if rows:
    print(f"desk: {len(rows)} analysis run(s) are still active", file=sys.stderr)
    sys.exit(1)
PY
}

case "${1:-}" in
  status)
    echo "branch $(git rev-parse --abbrev-ref HEAD)"
    echo "commit $(git rev-parse --short HEAD)"
    if [ -n "$(git status --porcelain)" ]; then
      echo "workspace dirty"
      exit 1
    fi
    echo "workspace clean"
    if curl -fsS http://127.0.0.1:5173/api/health; then
      echo
    else
      echo "health endpoint is not responding"
      exit 1
    fi
    ;;
  upstream)
    git fetch https://github.com/TauricResearch/TradingAgents.git main:refs/remotes/official/main
    echo "Commits on official/main that are not in HEAD:"
    git log --oneline HEAD..official/main || true
    ;;
  backup)
    echo "backup $(backup_db)"
    ;;
  merge)
    require_clean
    ref=${2:-}
    [ -n "$ref" ] || die "usage: scripts/desk.sh merge <ref>"
    git merge --no-edit "$ref"
    ;;
  test)
    .venv/bin/python -m pytest tests/dashboard -q
    (cd frontend && npm run lint && npx tsc -b && npm run build)
    ;;
  build)
    require_clean
    commit=$(git rev-parse --short HEAD)
    export DESK_GIT_COMMIT="$commit" DESK_IMAGE_TAG="$commit"
    $compose build
    echo "built tradingagents-desk-api:$commit and tradingagents-desk-web:$commit"
    ;;
  up)
    if curl -fsS http://127.0.0.1:5173/api/health >/dev/null 2>&1; then
      active_runs
    fi
    commit=${DESK_IMAGE_TAG:-$(git rev-parse --short HEAD)}
    export DESK_GIT_COMMIT="${DESK_GIT_COMMIT:-$commit}" DESK_IMAGE_TAG="$commit"
    $compose up -d
    $compose ps
    ;;
  rollback)
    tag=${2:-}
    [ -n "$tag" ] || die "usage: scripts/desk.sh rollback <image-tag>"
    docker image inspect "tradingagents-desk-api:$tag" >/dev/null
    docker image inspect "tradingagents-desk-web:$tag" >/dev/null
    if curl -fsS http://127.0.0.1:5173/api/health >/dev/null 2>&1; then
      active_runs
    fi
    export DESK_IMAGE_TAG="$tag" DESK_GIT_COMMIT="$tag"
    $compose up -d --no-build
    echo "rolled back to $tag. If a database migration is incompatible, restore a backup from data/backups instead of only changing the image."
    ;;
  *)
    die "usage: scripts/desk.sh status|upstream|backup|merge <ref>|test|build|up|rollback <tag>"
    ;;
esac
