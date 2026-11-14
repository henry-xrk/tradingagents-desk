#!/bin/sh
# Research desk maintenance. A failed check stops the command.
# This script does not stash, reset, clean, or pull on startup.
set -eu

code_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
if [ -n "${DESK_ROOT:-}" ]; then
  root=$DESK_ROOT
else
  root=$code_root
fi
cd "$root"
export PYTHONPATH="$code_root${PYTHONPATH:+:$PYTHONPATH}"
if [ -x "$root/.venv/bin/python" ]; then
  py="$root/.venv/bin/python"
else
  py=python3
fi
compose="docker compose -f $root/compose.desk.yml"

die() {
  echo "desk: $*" >&2
  exit 1
}

require_clean() {
  if [ -n "$(git status --porcelain)" ]; then
    die "working tree is dirty. Commit or set aside your changes manually; this script will not stash or reset."
  fi
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
    if curl -fsS "${DESK_HEALTH_URL:-http://127.0.0.1:5173/api/health}"; then
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
    "$py" -m backend.ops.backup || exit $?
    ;;
  restore)
    [ -n "${2:-}" ] && [ -n "${3:-}" ] || die "usage: scripts/desk.sh restore <backup> <destination>"
    "$py" -m backend.ops.backup restore "$2" "$3" || exit $?
    ;;
  merge)
    require_clean
    ref=${2:-}
    [ -n "$ref" ] || die "usage: scripts/desk.sh merge <ref>"
    git merge --no-edit "$ref"
    ;;
  test)
    "$py" -m pytest tests/dashboard -q || exit $?
    (cd frontend && npm run lint && npx tsc -b && node --experimental-strip-types --test src/lib/deskState.test.ts && npm run build) || exit $?
    "$py" -m backend.ops.gates stamp || exit $?
    ;;
  build)
    identity=$("$py" -m backend.ops.gates prepare-build) || exit $?
    commit=$(printf '%s\n' "$identity" | sed -n '1p')
    tree=$(printf '%s\n' "$identity" | sed -n '2p')
    tag=$(printf '%s' "$commit" | cut -c1-12)
    export DESK_GIT_COMMIT="$commit" DESK_TREE="$tree" DESK_IMAGE_TAG="$tag"
    $compose build
    "$py" -m backend.ops.gates bind "$tag" || exit $?
    echo "built tradingagents-desk-api:$tag and tradingagents-desk-web:$tag"
    ;;
  up)
    tag=$("$py" -c 'from backend.ops.gates import read_stamp; from pathlib import Path; stamp=read_stamp(Path(".")) or {}; print(str(stamp.get("commit") or "")[:12])')
    [ -n "$tag" ] || die "tests have not passed for the current source tree"
    export DESK_IMAGE_TAG="$tag"
    "$py" -m backend.ops.gates up || exit $?
    ;;
  rollback)
    tag=${2:-}
    [ -n "$tag" ] || die "usage: scripts/desk.sh rollback <image-tag>"
    "$py" -m backend.ops.gates rollback "$tag" || exit $?
    ;;
  *)
    die "usage: scripts/desk.sh status|upstream|backup|restore <backup> <dest>|merge <ref>|test|build|up|rollback <tag>"
    ;;
esac
