# Research desk

The desk runs beside the TradingAgents CLI. `docker-compose.yml` still starts the CLI. The desk uses `compose.desk.yml` and is opened at http://127.0.0.1:5173. Port 5173 is bound only on the loopback address. The API container is not published on the host; the web container proxies `/api` to the Compose service name `api`.

Agent updates come from <https://github.com/TauricResearch/TradingAgents>. `./scripts/desk.sh upstream` fetches that repository's `main` into `official/main`. It does not use the remote named `origin`. Review those commits, then merge `official/main` into a clean worktree. Use merge, not rebase. Push the `desk` branch to this repository. Do not push it to Tauric Research.

## Three configuration layers

- The project `.env` file stays on the host. It is gitignored and excluded from the image.
- `${DESK_DATA_DIR}`, `${DESK_IMAGE_TAG}`, and `${DESK_GIT_COMMIT}` are replaced by Compose while it reads `compose.desk.yml`. They do not by themselves enter the container.
- `env_file: .env` injects `OPENAI_API_KEY` into the API process. The frontend build has no `VITE_` secret, and the browser does not store the key.

A configured key is not proof that the key is valid or that the account has balance. The Settings page can run a provider check only after you confirm that the call may incur a charge.

## Data

`data/desk` is mounted at `/home/appuser/.tradingagents` inside the API container. It holds the dashboard SQLite database, reports under `logs`, the Yahoo cache, the research memory log, and future checkpoints. Memory and checkpoints can contain research content; they are not committed. The directory is mode `0700` on the host.

The original files under `~/.tradingagents` are not the container's data and are not deleted by these commands. `chatgpt-auth.json` is not part of the desk copy.

Report paths in the desk database are relative to `logs`, for example `reports/<run>/complete_report.html`. A migration records schema version 1 and can run again. It drops global price ladders without assigning them to a ticker. If it fails, the API process exits and the version is not recorded. Restore the database from `data/backups/<timestamp>/research.db` with SQLite's backup API; do not copy the file while a process is writing it.

`scripts/desk.sh` refuses to continue after a dirty tree, a merge conflict, a failed test, a failed backup, or an active research run. It does not stash, reset, clean, or delete data. Containers do not pull git on startup.

## Commands

Check the branch, commit, and health. A dirty tree exits non-zero:

```bash
./scripts/desk.sh status
```

Show upstream commits that are not in this branch:

```bash
./scripts/desk.sh upstream
```

Back up the desk database:

```bash
./scripts/desk.sh backup
```

Merge a fetched upstream ref into the clean `desk` branch. Resolve conflicts yourself, then run the tests:

```bash
./scripts/desk.sh merge official/main
./scripts/desk.sh test
```

Build images tagged with the current commit and start them. `up` stops when research is still active:

```bash
./scripts/desk.sh build
./scripts/desk.sh up
```

Logs and health:

```bash
docker compose -f compose.desk.yml logs -f
curl -fsS http://127.0.0.1:5173/api/health
```

Stop without deleting the data directory or volume:

```bash
docker compose -f compose.desk.yml stop
```

Do not run `docker compose down -v` or a volume prune.

Roll back to an image tag that is already built. This does not reverse a database migration. If a future migration cannot be read by the older image, restore the backup taken before that migration:

```bash
./scripts/desk.sh rollback <commit>
```

Hot reload is `docker compose -f compose.desk.dev.yml up`. It is separate from the production file and also wants port 5173, so do not run both.

## What the page shows

Settings shows the package version and `TRADINGAGENTS_BUILD_COMMIT`. Compare that commit with `git rev-parse --short HEAD` after an update. Estimated model cost stays unknown unless a run reports usage and a verified price exists. The call budget counts steps; it is not a dollar cap.
