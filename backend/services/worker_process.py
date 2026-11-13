"""Child-process entry point for one analysis.

The child sends progress to the parent and does not write the dashboard database.
"""

from __future__ import annotations

import importlib

from backend.errors import classify_exception


class ChildHandle:
    def __init__(self, connection, stop_event, preferences: dict):
        self._connection = connection
        self._stop_event = stop_event
        self._preferences = preferences

    def should_stop(self) -> bool:
        return bool(self._stop_event.is_set())

    def preferences(self) -> dict:
        return dict(self._preferences)

    def update(self, **kwargs) -> None:
        self._connection.send({"op": "update", "fields": kwargs})

    def mark_timeout(self) -> None:
        self._stop_event.set()

    def fail_exception(self, exc: BaseException) -> None:
        code, message = classify_exception(exc)
        self._connection.send({"op": "fail", "code": code, "message": message})

    def ensure_closed(self) -> None:
        self._connection.send({"op": "ensure_closed"})


def _load_worker(worker_ref: str):
    module_name, function_name = worker_ref.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, function_name)


def main(analysis_id: str, settings: dict, preferences: dict, connection, stop_event, worker_ref: str) -> None:
    from backend.services.runner import AnalysisJob

    handle = ChildHandle(connection, stop_event, preferences)
    job = AnalysisJob(analysis_id, settings)
    try:
        _load_worker(worker_ref)(job, handle)
        connection.send({"op": "closed"})
    except Exception as exc:
        code, message = classify_exception(exc, ref=analysis_id)
        connection.send({"op": "fail", "code": code, "message": message})
    finally:
        connection.close()
