# tradingagents-desk

This repository is a personal research desk built on [TradingAgents](https://github.com/TauricResearch/TradingAgents) by Tauric Research. It is not the official TradingAgents project.

The framework, CLI, package API, and citation live in the upstream README: <https://github.com/TauricResearch/TradingAgents>. This file replaces that README for this derivative. The upstream project and this derivative are licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE). Upstream files modified here are `.dockerignore`, `.env.example`, `.gitignore`, `pyproject.toml`, and `tests/conftest.py`. The desk is added under `backend/`, `frontend/`, `deploy/`, `docs/desk.md`, and `scripts/desk.sh`.

TradingAgents is research software. It is not financial, investment, or trading advice. The upstream disclaimer is at <https://tauric.ai/disclaimer/>.

## Run

The desk is a React app and a FastAPI service. It opens at <http://127.0.0.1:5173>. That port is bound only on the loopback address. The API container is not published on the host. The web container proxies `/api` to it.

The API key stays in the host `.env` file and is not baked into the image. The page does not store the key, and the desk does not use ChatGPT subscription sign-in. Start from a clean git worktree:

```bash
cp .env.example .env
./scripts/desk.sh test
./scripts/desk.sh build
./scripts/desk.sh up
```

Set `OPENAI_API_KEY` in `.env` before `up`. `docker-compose.yml` still starts the upstream CLI and is separate from this stack. Hot reload is `docker compose -f compose.desk.dev.yml up`. It also uses port 5173, so do not run it beside the command above.

## What the page shows

Charts use Yahoo Finance through the engine's data loader. A data failure is shown as an error. Entry, stop, and target prices are research hypotheses and appear only when the saved report has a single labeled number. Share counts, planned loss, and capital use are calculated in Python from capital inputs you enter. Fields the run did not supply stay unavailable.

Backups, updating the agent from upstream, and rollback are documented in [`docs/desk.md`](docs/desk.md).
