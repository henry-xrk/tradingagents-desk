# Research desk

The desk runs beside the TradingAgents CLI. `docker-compose.yml` still starts the CLI. The desk uses `compose.desk.yml` and is opened at http://127.0.0.1:5173. Port 5173 is bound only on the loopback address. The API container is not published on the host; the web container proxies `/api` to the Compose service name `api`.

Agent updates come from <https://github.com/TauricResearch/TradingAgents>. `./scripts/desk.sh upstream` fetches that repository's `main` into `official/main`. It does not use the remote named `origin`. Review those commits, then merge `official/main` into a clean worktree. Use merge, not rebase. Push the `desk` branch to this repository. Do not push it to Tauric Research.

## Three configuration layers

- The project `.env` file stays on the host. It is gitignored and excluded from the image.
- `${DESK_DATA_DIR}`, `${DESK_IMAGE_TAG}`, and `${DESK_GIT_COMMIT}` are replaced by Compose while it reads `compose.desk.yml`. They do not by themselves enter the container.
- `env_file: .env` injects `OPENAI_API_KEY` into the API process. The frontend build has no `VITE_` secret, and the browser does not store the key.

A configured key is not proof that the key is valid or that the account has balance. The Settings page can run a provider check only after you confirm that the call may incur a charge. That check requests `/models` on `TRADINGAGENTS_LLM_BACKEND_URL` when it is set, and otherwise uses `https://api.openai.com/v1`.

## Data

`data/desk` is mounted at `/home/appuser/.tradingagents` inside the API container. It holds the dashboard SQLite database, reports under `logs`, the Yahoo cache, the research memory log, and future checkpoints. Memory and checkpoints can contain research content; they are not committed. The directory is mode `0700` on the host.

The original files under `~/.tradingagents` are not the container's data and are not deleted by these commands. `chatgpt-auth.json` is not part of the desk copy.

Report paths in the desk database are relative to `logs`, for example `reports/<run>/complete_report.html`. Schema version 1 rewrites those paths and drops global price ladders without assigning them to a ticker. Schema version 2 copies each existing saved trade plan into `plan_versions` once; it does not invent older versions. Schema version 3 adds endpoint and credential-digest columns to connection checks and does not rewrite research rows. These steps can run again. If a migration fails, the API process exits and that version is not recorded. The default research date uses the America/New_York calendar. Stored timestamps stay in UTC.

`DESK_DATA_DIR` in the process environment wins. If it is unset, both Compose and `scripts/desk.sh` read the same `DESK_DATA_DIR=` line from `.env`. The script does not execute the file.

A backup is one directory under `data/backups/<timestamp>/`, mode `0700`. It contains a SQLite backup of `dashboard/research.db` checked with `integrity_check`, HTML and Markdown reports, `memory`, and `checkpoints`, plus `manifest.json`. It does not include `chatgpt-auth.json` or `.env`. The command prints the directory only after that check passes. Restore validates the manifest, database, hashes, and paths before it changes the destination. A failed restore leaves the previous database and files in place. Restoring the live data directory stops unless no desk container exists:

```bash
docker compose -f compose.desk.yml stop
docker compose -f compose.desk.yml rm -f
./scripts/desk.sh restore data/backups/<timestamp> data/desk
```

Image rollback swaps the running image. It does not restore the database. If the database schema is newer than the target image label `desk.schema`, rollback stops. Use `restore` only when the data itself must return to a backup, and only after the service is stopped.

`up` and `rollback` do not pull, stash, or reset. They stop when the service state is unknown, when research is active, when merge conflicts are present, when either target image or its schema label is missing, when `.desk/test-ok` does not match the full HEAD, the tested source tree, and both image ids, or when an existing database has no verified backup at the same schema. A first install still requires the conflict, image, and test checks. A stopped deployment is not a first install. `test` writes `.desk/test-ok` only after the dashboard tests, typecheck, lint, and production build all exit zero. `build` refuses to run when that stamp does not match the current tree, then records the built image ids. Health reports the commit and tree baked into the image; `TRADINGAGENTS_BUILD_COMMIT` is not accepted as proof. If startup fails, the command reports the service state and does not claim success.

## Commands

Check the branch, commit, and health. A dirty tree exits non-zero:

```bash
./scripts/desk.sh status
```

Review upstream commits before merging. This does not merge or overwrite the worktree:

```bash
./scripts/desk.sh upstream
```

When the diff is acceptable and the worktree is clean, merge that ref yourself. If Git stops with conflicts, resolve them and run the tests.

```bash
./scripts/desk.sh merge official/main
```

Back up the desk database, reports, memory, and checkpoints:

```bash
./scripts/desk.sh backup
```

Merge a fetched upstream ref into the clean `desk` branch. Resolve conflicts yourself, then run the tests:

```bash
./scripts/desk.sh merge official/main
./scripts/desk.sh test
```

The repeatable update order is: fetch and review, merge, test, backup, build, deploy, then compare `/api/health` with `/desk-build.json`. Both images from one build share the tested commit and tree.

```bash
./scripts/desk.sh test
./scripts/desk.sh backup
./scripts/desk.sh build
./scripts/desk.sh up
curl -fsS http://127.0.0.1:5173/api/health
curl -fsS http://127.0.0.1:5173/desk-build.json
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

Roll back the service to an image tag that is already built and labeled with `desk.schema`. This does not restore data. If the live schema is newer than that label, the command stops:

```bash
./scripts/desk.sh rollback <commit>
```

Hot reload is `docker compose -f compose.desk.dev.yml up`. It is separate from the production file and also wants port 5173, so do not run both.

## What the page shows

Settings shows the package version and the commit baked into the image. Compare it with `git rev-parse HEAD` after an update. A connection check is not a completed research run, and it expires when the endpoint or credential configuration changes. Estimated model cost stays unknown unless a run reports usage and a verified price exists. The call budget counts steps; it is not a dollar cap.
