"""FastAPI entrypoint for the local research dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.api import router
from backend.services.runner import DEFAULT_TIMEOUT_SECONDS, AnalysisRunner
from backend.storage.db import DashboardStore


def create_app(
    store: DashboardStore | None = None,
    runner: AnalysisRunner | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> FastAPI:
    store = store or DashboardStore()
    runner = runner or AnalysisRunner(store, timeout_seconds=timeout_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.fail_unfinished(
            "The dashboard stopped before this analysis finished. It was not cancelled."
        )
        yield
        runner.shutdown()

    app = FastAPI(title="TradingAgents Dashboard", lifespan=lifespan)
    app.state.store = store
    app.state.runner = runner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/")
    def root():
        return {
            "service": "tradingagents-dashboard",
            "health": "/api/health",
            "docs": "/docs",
        }

    return app


app = create_app()
