"""Background analysis runs, duplicate protection, and server-sent events.

The default worker is a child process. The parent writes the database. An
injected worker stays in a thread so tests can use local functions.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import multiprocessing
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from backend.errors import DashboardError, classify_exception
from backend.services.engine import execute_analysis
from backend.services.progress import ProgressState
from backend.storage.db import ACTIVE_STATUSES, DashboardStore, utcnow

TERMINAL = frozenset({"completed", "failed", "timed_out", "stopped", "interrupted"})
DEFAULT_TIMEOUT_SECONDS = 45 * 60
MAX_RUNNING = 1
MAX_QUEUED = 2

Worker = Callable[["AnalysisJob", "RunHandle"], None]


def analysis_fingerprint(settings: dict) -> str:
    payload = {
        "ticker": settings["ticker"],
        "analysis_date": settings["analysis_date"],
        "analysts": list(settings["analysts"]),
        "research_depth": settings["research_depth"],
        "output_language": settings["output_language"],
        "llm_provider": settings["llm_provider"],
        "quick_think_llm": settings["quick_think_llm"],
        "deep_think_llm": settings["deep_think_llm"],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def worker_ref_for(worker: Worker) -> str:
    name = getattr(worker, "__name__", "")
    module = getattr(worker, "__module__", "")
    qualname = getattr(worker, "__qualname__", "")
    if not name or not module or "<locals>" in qualname:
        raise DashboardError(
            "This worker cannot run in a separate process.",
            status=500,
            code="worker",
        )
    return f"{module}:{name}"


@dataclass
class AnalysisJob:
    id: str
    settings: dict

    @property
    def ticker(self) -> str:
        return self.settings["ticker"]

    @property
    def analysis_date(self) -> str:
        return self.settings["analysis_date"]


class RunHandle:
    """The worker's view of one run. Updates are serialized by the runner."""

    def __init__(self, runner: AnalysisRunner, analysis_id: str):
        self.runner = runner
        self.analysis_id = analysis_id

    def should_stop(self) -> bool:
        return self.runner.should_stop(self.analysis_id)

    def preferences(self) -> dict:
        return self.runner.store.get_preferences()

    def update(self, **kwargs) -> None:
        self.runner.update(self.analysis_id, **kwargs)

    def mark_timeout(self) -> None:
        self.runner.mark_timeout(self.analysis_id)

    def fail_exception(self, exc: BaseException) -> None:
        self.runner.fail_exception(self.analysis_id, exc)

    def ensure_closed(self) -> None:
        self.runner.ensure_closed(self.analysis_id)


class _Session:
    def __init__(self, record: dict):
        self.record = record
        self.events: list[dict] = []
        self.subscribers: list[queue.Queue] = []
        self.process: multiprocessing.Process | None = None
        self.stop_event = None
        self.stop_reason: str | None = None
        self.reader: threading.Thread | None = None


class AnalysisRunner:
    def __init__(
        self,
        store: DashboardStore,
        worker: Worker | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        isolate: bool | None = None,
        max_running: int = MAX_RUNNING,
        max_queued: int = MAX_QUEUED,
    ):
        self.store = store
        self._worker = worker or execute_analysis
        self._isolate = (worker is None) if isolate is None else isolate
        self.timeout_seconds = timeout_seconds
        self.max_running = max_running
        self.max_queued = max_queued
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._active: dict[str, str] = {}
        self._jobs: dict[str, AnalysisJob] = {}
        self._closing = False
        self._mp = multiprocessing.get_context("spawn")

    def start(self, settings: dict) -> dict:
        fingerprint = analysis_fingerprint(settings)
        with self._lock:
            existing_id = self._active.get(fingerprint)
            if existing_id and existing_id in self._sessions:
                view = copy.deepcopy(self._sessions[existing_id].record)
                view["reused"] = True
                return view
            stored = self.store.find_active_fingerprint(fingerprint)
            if stored is not None:
                stored["reused"] = True
                return stored
            self._reject_if_full_locked()

            analysis_id = uuid.uuid4().hex
            progress = ProgressState(list(settings["analysts"]))
            now = utcnow()
            record = {
                "id": analysis_id,
                "fingerprint": fingerprint,
                "ticker": settings["ticker"],
                "analysis_date": settings["analysis_date"],
                "settings": settings,
                "status": "queued",
                "phase": "queued",
                "agent_status": dict(progress.agent_status),
                "reports": {},
                "rating": None,
                "trade_plan": None,
                "error": None,
                "error_code": None,
                "data_sources": {},
                "activity": [],
                "html_report_path": None,
                "markdown_report_path": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "reused": False,
            }
            self.store.insert_analysis(record)
            session = _Session(record)
            self._sessions[analysis_id] = session
            self._active[fingerprint] = analysis_id
            self._jobs[analysis_id] = AnalysisJob(analysis_id, settings)
            self._emit(session, "status", "Analysis queued", False)
        self._dispatch()
        with self._lock:
            view = copy.deepcopy(self._sessions[analysis_id].record)
        view["reused"] = False
        return view

    def cancel(self, analysis_id: str) -> dict | None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            record = session.record if session is not None else self.store.get_analysis(analysis_id)
            if record is None:
                return None
            if record["status"] in TERMINAL:
                return copy.deepcopy(record)
            if session is None:
                return copy.deepcopy(record)
            if record["status"] == "queued" and session.process is None and session.reader is None:
                self._close_locked(
                    session,
                    status="stopped",
                    phase="stopped",
                    code="stopped",
                    message="The queued analysis was stopped before it started.",
                )
                view = copy.deepcopy(session.record)
            else:
                session.stop_reason = "cancel"
                record["status"] = "cancel_requested"
                record["phase"] = "cancel_requested"
                record["error_code"] = "cancel_requested"
                self._append_activity(record, "Cancellation was requested. The worker has not stopped yet.")
                self.store.save_analysis(record)
                self._emit(session, "status", record["activity"][-1]["message"], False)
                self._signal_locked(session, "cancelling")
                view = copy.deepcopy(session.record)
        self._dispatch()
        return view

    def shutdown(self, grace: float = 2.0) -> None:
        """Stop child processes on service shutdown without calling them cancelled."""
        processes = []
        with self._lock:
            self._closing = True
            for session in self._sessions.values():
                if session.record["status"] in TERMINAL:
                    continue
                if session.process is not None and session.process.is_alive():
                    session.stop_reason = session.stop_reason or "shutdown"
                    session.process.terminate()
                    processes.append(session)
        deadline = utcnow()
        for session in processes:
            session.process.join(grace)
        with self._lock:
            for session in processes:
                process = session.process
                if process is None or process.is_alive() or session.record["status"] in TERMINAL:
                    continue
                self._close_locked(
                    session,
                    status="interrupted",
                    phase="interrupted",
                    code="interrupted",
                    message=(
                        "The dashboard stopped this worker during shutdown. "
                        "It was not cancelled. (ref "
                        f"{session.record['id']})"
                    ),
                )
            _ = deadline

    def get(self, analysis_id: str) -> dict | None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is not None:
                return copy.deepcopy(session.record)
        return self.store.get_analysis(analysis_id)

    def set_trade_plan(self, analysis_id: str, plan: dict, market: dict) -> dict | None:
        """Save a plan without replacing the research market snapshot.

        `market` is retained for callers that still pass a quote. It is not written
        over `data_sources.market` or `data_sources.research_market`.
        """
        del market
        with self._lock:
            session = self._sessions.get(analysis_id)
            record = session.record if session is not None else self.store.get_analysis(analysis_id)
            if record is None:
                return None
            record["trade_plan"] = plan
            self.store.save_analysis(record)
            if session is not None:
                session.record = record
            return copy.deepcopy(plan)

    def remember_trade_plan(self, analysis_id: str, plan: dict) -> None:
        """Update a live session after the store has already committed the plan."""
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is not None:
                session.record["trade_plan"] = copy.deepcopy(plan)

    def subscribe(self, analysis_id: str) -> queue.Queue:
        mailbox: queue.Queue = queue.Queue()
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None:
                record = self.store.get_analysis(analysis_id)
                if record is None:
                    raise KeyError(analysis_id)
                mailbox.put(_snapshot_event(record))
                mailbox.put(None)
                return mailbox
            for event in session.events:
                mailbox.put(event)
            if session.record["status"] in TERMINAL:
                mailbox.put(None)
            else:
                session.subscribers.append(mailbox)
        return mailbox

    def unsubscribe(self, analysis_id: str, mailbox: queue.Queue) -> None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session and mailbox in session.subscribers:
                session.subscribers.remove(mailbox)

    def should_stop(self, analysis_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None:
                return True
            if session.stop_reason in {"cancel", "timeout", "shutdown"}:
                return True
            return session.record["status"] in TERMINAL or session.record["status"] in {
                "cancel_requested",
                "cancelling",
            }

    def update(self, analysis_id: str, **kwargs) -> None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None:
                return
            record = session.record
            if record["status"] in TERMINAL:
                if kwargs.get("status") == "completed":
                    self._append_activity(
                        record,
                        "The analysis worker finished after this run was already closed.",
                    )
                    self.store.save_analysis(record)
                return
            if record["status"] in {"cancel_requested", "cancelling"} or session.stop_reason:
                kwargs.pop("status", None)
                if kwargs.get("phase") in TERMINAL:
                    kwargs.pop("phase", None)

            before = (
                record["status"],
                record["phase"],
                copy.deepcopy(record.get("agent_status")),
                copy.deepcopy(record.get("reports")),
                record.get("rating"),
                record.get("html_report_path"),
                record.get("markdown_report_path"),
            )
            reports_changed = _apply_update(record, kwargs)
            after = (
                record["status"],
                record["phase"],
                record.get("agent_status"),
                record.get("reports"),
                record.get("rating"),
                record.get("html_report_path"),
                record.get("markdown_report_path"),
            )
            message = kwargs.get("message")
            message_is_new = bool(message) and (
                not record.get("activity") or record["activity"][-1].get("message") != message
            )
            trade_plan_changed = kwargs.get("trade_plan") is not None
            if (
                after == before
                and not message_is_new
                and not kwargs.get("data_sources")
                and not trade_plan_changed
            ):
                return
            if message_is_new and message:
                self._append_activity(record, message)
            self.store.save_analysis(record)
            event_type = record["status"] if record["status"] in TERMINAL else "status"
            self._emit(session, event_type, message, reports_changed)
            if record["status"] in TERMINAL:
                self._release(record)

    def mark_timeout(self, analysis_id: str) -> None:
        window = _timeout_label(self.timeout_seconds)
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None or session.record["status"] in TERMINAL:
                return
            if session.process is not None:
                session.stop_reason = session.stop_reason or "timeout"
                if session.stop_event is not None:
                    session.stop_event.set()
                if session.process.is_alive():
                    session.process.terminate()
                record = session.record
                record["phase"] = "stopping"
                record["error_code"] = "timeout"
                record["error"] = (
                    f"The analysis exceeded {window}. The worker is being stopped. "
                    "This is a timeout, not a cancellation."
                )
                self._append_activity(record, record["error"])
                self.store.save_analysis(record)
                self._emit(session, "status", record["error"], False)
                return
            message = (
                f"The analysis exceeded {window} and was closed. "
                "Later results from this run are ignored. (ref {analysis_id})"
            )
            self._close_locked(session, status="timed_out", phase="timed_out", code="timeout", message=message)

    def fail_exception(self, analysis_id: str, exc: BaseException) -> None:
        code, message = classify_exception(exc, ref=analysis_id)
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None or session.record["status"] in TERMINAL:
                return
            if session.stop_reason == "cancel":
                return
            self._close_locked(session, status="failed", phase="failed", code=code, message=message)

    def ensure_closed(self, analysis_id: str) -> None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None or session.record["status"] in TERMINAL:
                return
            if session.stop_reason == "cancel" or session.record["status"] in {"cancel_requested", "cancelling"}:
                self._close_locked(
                    session,
                    status="stopped",
                    phase="stopped",
                    code="stopped",
                    message=f"The analysis stopped. Partial reports were kept. (ref {analysis_id})",
                )
                return
            if session.stop_reason == "timeout":
                self._close_locked(
                    session,
                    status="timed_out",
                    phase="timed_out",
                    code="timeout",
                    message=f"The analysis timed out and the worker exited. (ref {analysis_id})",
                )
                return
            self._close_locked(
                session,
                status="failed",
                phase="failed",
                code="incomplete",
                message=f"The analysis worker exited without a final status. (ref {analysis_id})",
            )

    def _reject_if_full_locked(self) -> None:
        running = queued = 0
        for session in self._sessions.values():
            status = session.record["status"]
            if status == "queued":
                queued += 1
            elif status in ACTIVE_STATUSES:
                running += 1
        if running >= self.max_running and queued >= self.max_queued:
            raise DashboardError(
                "The research queue is full. Wait for a run to finish or cancel one.",
                status=429,
                code="queue_full",
            )

    def _dispatch(self) -> None:
        with self._lock:
            if self._closing:
                return
            running = sum(
                1
                for session in self._sessions.values()
                if session.record["status"] in ACTIVE_STATUSES and session.record["status"] != "queued"
            )
            if running >= self.max_running:
                return
            queued = [
                session
                for session in self._sessions.values()
                if session.record["status"] == "queued" and session.process is None and session.reader is None
            ]
            if not queued:
                return
            session = sorted(queued, key=lambda item: item.record["created_at"])[0]
            self._mark_started_locked(session)
            if self._isolate:
                self._start_process(session)
            else:
                thread = threading.Thread(
                    target=self._thread,
                    args=(session.record["id"],),
                    name=f"analysis-{session.record['id'][:8]}",
                    daemon=True,
                )
                session.reader = thread
                thread.start()

    def _mark_started_locked(self, session: _Session) -> None:
        record = session.record
        record["status"] = "running"
        record["phase"] = "starting"
        record["started_at"] = record.get("started_at") or utcnow()
        self.store.save_analysis(record)
        self._emit(session, "status", "Analysis started", False)

    def _start_process(self, session: _Session) -> None:
        from backend.services.worker_process import main

        analysis_id = session.record["id"]
        parent, child = self._mp.Pipe(duplex=False)
        stop_event = self._mp.Event()
        session.stop_event = stop_event
        process = self._mp.Process(
            target=main,
            args=(
                analysis_id,
                self._jobs[analysis_id].settings,
                self.store.get_preferences(),
                child,
                stop_event,
                worker_ref_for(self._worker),
            ),
            name=f"analysis-{analysis_id[:8]}",
            daemon=True,
        )
        session.process = process
        process.start()
        child.close()
        reader = threading.Thread(
            target=self._read_process,
            args=(analysis_id, parent, process),
            name=f"analysis-read-{analysis_id[:8]}",
            daemon=True,
        )
        session.reader = reader
        reader.start()
        timer = threading.Timer(self.timeout_seconds, self.mark_timeout, args=(analysis_id,))
        timer.daemon = True
        timer.start()

    def _read_process(self, analysis_id: str, parent, process) -> None:
        try:
            while True:
                try:
                    message = parent.recv()
                except EOFError:
                    break
                except OSError:
                    break
                if not isinstance(message, dict):
                    continue
                op = message.get("op")
                if op == "update":
                    self.update(analysis_id, **(message.get("fields") or {}))
                elif op == "fail":
                    self._fail_message(analysis_id, message.get("code") or "error", message.get("message") or "The analysis failed.")
                elif op == "ensure_closed":
                    self.ensure_closed(analysis_id)
        finally:
            process.join(timeout=5)
            self._finish_process(analysis_id, process.exitcode)
            with contextlib.suppress(OSError):
                parent.close()
            self._dispatch()

    def _finish_process(self, analysis_id: str, exitcode: int | None) -> None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None or session.record["status"] in TERMINAL:
                if session is not None:
                    self._release(session.record)
                return
            reason = session.stop_reason
            if reason == "cancel" or session.record["status"] in {"cancel_requested", "cancelling"}:
                self._close_locked(
                    session,
                    status="stopped",
                    phase="stopped",
                    code="stopped",
                    message=f"The analysis process has stopped. Partial reports were kept. (ref {analysis_id})",
                )
            elif reason == "timeout":
                self._close_locked(
                    session,
                    status="timed_out",
                    phase="timed_out",
                    code="timeout",
                    message=f"The analysis timed out and the worker process exited. (ref {analysis_id})",
                )
            elif reason == "shutdown":
                self._close_locked(
                    session,
                    status="interrupted",
                    phase="interrupted",
                    code="interrupted",
                    message=f"The dashboard stopped during shutdown. The run was not cancelled. (ref {analysis_id})",
                )
            elif exitcode not in (0, None):
                self._close_locked(
                    session,
                    status="failed",
                    phase="failed",
                    code="worker_exit",
                    message=f"The analysis process exited before it finished. (ref {analysis_id})",
                )
            else:
                self._close_locked(
                    session,
                    status="failed",
                    phase="failed",
                    code="incomplete",
                    message=f"The analysis worker exited without a final status. (ref {analysis_id})",
                )

    def _fail_message(self, analysis_id: str, code: str, message: str) -> None:
        with self._lock:
            session = self._sessions.get(analysis_id)
            if session is None or session.record["status"] in TERMINAL or session.stop_reason == "cancel":
                return
            self._close_locked(session, status="failed", phase="failed", code=code, message=message)

    def _signal_locked(self, session: _Session, phase: str) -> None:
        record = session.record
        record["status"] = phase if phase != "cancelling" else "cancelling"
        record["phase"] = phase
        if session.stop_event is not None:
            session.stop_event.set()
        process = session.process
        if process is not None and process.is_alive():
            process.terminate()
        self._append_activity(record, "The worker was signalled and is stopping.")
        self.store.save_analysis(record)
        self._emit(session, "status", record["activity"][-1]["message"], False)

    def _close_locked(self, session: _Session, *, status: str, phase: str, code: str, message: str) -> None:
        record = session.record
        if record["status"] in TERMINAL:
            return
        record["status"] = status
        record["phase"] = phase
        record["error"] = message
        record["error_code"] = code
        record["finished_at"] = utcnow()
        _settle_open_agents(record)
        self._append_activity(record, message)
        self.store.save_analysis(record)
        self._emit(session, status, message, False)
        self._release(record)

    def _thread(self, analysis_id: str) -> None:
        handle = RunHandle(self, analysis_id)
        timer = threading.Timer(self.timeout_seconds, handle.mark_timeout)
        timer.daemon = True
        timer.start()
        try:
            self._worker(self._jobs[analysis_id], handle)
            handle.ensure_closed()
        except Exception as exc:
            handle.fail_exception(exc)
        finally:
            timer.cancel()
            self._dispatch()

    def _emit(self, session: _Session, event_type: str, message: str | None, reports_changed: bool) -> None:
        event = {
            "type": event_type,
            "at": utcnow(),
            "id": session.record["id"],
            "status": session.record["status"],
            "phase": session.record["phase"],
            "message": message,
            "agent_status": dict(session.record.get("agent_status") or {}),
            "reports_changed": reports_changed,
            "error": session.record.get("error"),
            "error_code": session.record.get("error_code"),
        }
        session.events.append(event)
        if len(session.events) > 500:
            session.events = session.events[-500:]
        for subscriber in list(session.subscribers):
            subscriber.put(event)
        if session.record["status"] in TERMINAL:
            for subscriber in list(session.subscribers):
                subscriber.put(None)
            session.subscribers.clear()

    def _release(self, record: dict) -> None:
        fingerprint = record.get("fingerprint")
        if fingerprint and self._active.get(fingerprint) == record["id"]:
            self._active.pop(fingerprint, None)

    @staticmethod
    def _append_activity(record: dict, message: str) -> None:
        activity = list(record.get("activity") or [])
        if activity and activity[-1].get("message") == message:
            return
        activity.append({"at": utcnow(), "message": message})
        record["activity"] = activity[-80:]


def _settle_open_agents(record: dict) -> None:
    """A finished run cannot leave a node looking active."""
    status = dict(record.get("agent_status") or {})
    for name, value in status.items():
        if value == "in_progress":
            status[name] = "not_completed"
    record["agent_status"] = status


def _apply_update(record: dict, changes: dict) -> bool:
    reports_changed = False
    status = changes.get("status")
    if status and status != record["status"]:
        record["status"] = status
        if status == "running" and not record.get("started_at"):
            record["started_at"] = utcnow()
        if status in TERMINAL:
            record["finished_at"] = utcnow()
            _settle_open_agents(record)
    phase = changes.get("phase")
    if phase:
        record["phase"] = phase
    if changes.get("agent_status") is not None:
        record["agent_status"] = dict(changes["agent_status"])
    if changes.get("reports"):
        merged = dict(record.get("reports") or {})
        before = dict(merged)
        for key, value in changes["reports"].items():
            if isinstance(value, str) and value.strip():
                merged[key] = value.strip()
        record["reports"] = merged
        reports_changed = merged != before
    if changes.get("rating") is not None:
        record["rating"] = changes["rating"]
    if changes.get("trade_plan") is not None:
        record["trade_plan"] = changes["trade_plan"]
    if changes.get("error") is not None:
        record["error"] = changes["error"]
    if changes.get("error_code") is not None:
        record["error_code"] = changes["error_code"]
    if changes.get("data_sources"):
        sources = dict(record.get("data_sources") or {})
        sources.update(changes["data_sources"])
        record["data_sources"] = sources
    if changes.get("html_report_path"):
        record["html_report_path"] = changes["html_report_path"]
    if changes.get("markdown_report_path"):
        record["markdown_report_path"] = changes["markdown_report_path"]
    return reports_changed


def _snapshot_event(record: dict) -> dict:
    status = record["status"]
    return {
        "type": status if status in TERMINAL else "status",
        "at": record.get("updated_at"),
        "id": record["id"],
        "status": status,
        "phase": record.get("phase"),
        "message": record.get("error") or record.get("phase"),
        "agent_status": dict(record.get("agent_status") or {}),
        "reports_changed": False,
        "error": record.get("error"),
        "error_code": record.get("error_code"),
    }


def _timeout_label(seconds: float) -> str:
    if seconds >= 60:
        return f"{round(seconds / 60)} minutes"
    return f"{seconds:g} seconds"
