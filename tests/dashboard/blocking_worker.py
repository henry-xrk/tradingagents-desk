"""Importable worker used by process-isolation tests."""

from __future__ import annotations

import time


def block(job, handle) -> None:
    handle.update(
        status="running",
        phase="analysts",
        message="blocking",
        reports={"market_report": "partial note"},
    )
    for _ in range(80):
        if handle.should_stop():
            return
        time.sleep(0.05)
    handle.update(status="completed", phase="completed", message="finished")
