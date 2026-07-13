"""Thread-safe execution lifecycle with backwards-compatible engine semantics."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum


class RunState(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    RUNNING = "running"
    STOPPING = "stopping"


@dataclass(frozen=True)
class RunSnapshot:
    state: RunState
    active_run_id: int | None
    stop_requested: bool
    started_at: float | None
    last_run_id: int | None
    last_outcome: str
    last_error: str


class RunLifecycle:
    """Own run identity, cancellation and terminal metadata under one lock."""

    def __init__(self):
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._sequence = 0
        self._state = RunState.IDLE
        self._active_run_id: int | None = None
        self._started_at: float | None = None
        self._last_run_id: int | None = None
        self._last_outcome = ""
        self._last_error = ""

    def reserve(self) -> int | None:
        with self._lock:
            if self._state is not RunState.IDLE:
                return None
            self._sequence += 1
            self._active_run_id = self._sequence
            self._state = RunState.PREPARING
            self._started_at = time.monotonic()
            self._stop_event.clear()
            return self._active_run_id

    def mark_running(self, run_id: int) -> bool:
        with self._lock:
            if self._active_run_id != run_id or self._state is RunState.IDLE:
                return False
            if self._state is not RunState.STOPPING:
                self._state = RunState.RUNNING
            return True

    def matches(self, run_id: int | None) -> bool:
        with self._lock:
            return self._state is not RunState.IDLE and self._active_run_id == run_id

    def request_stop(self) -> bool:
        with self._lock:
            if self._state is RunState.IDLE:
                return False
            self._state = RunState.STOPPING
            self._stop_event.set()
            return True

    def finish(self, run_id: int, outcome: str = "finished", error: str = "") -> bool:
        with self._lock:
            if self._active_run_id != run_id:
                return False
            self._last_run_id = run_id
            self._last_outcome = str(outcome or "finished")
            self._last_error = str(error or "")
            self._active_run_id = None
            self._started_at = None
            self._state = RunState.IDLE
            self._stop_event.clear()
            return True

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._state is not RunState.IDLE

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    @property
    def state(self) -> RunState:
        with self._lock:
            return self._state

    def snapshot(self) -> RunSnapshot:
        with self._lock:
            return RunSnapshot(
                state=self._state,
                active_run_id=self._active_run_id,
                stop_requested=self._stop_event.is_set(),
                started_at=self._started_at,
                last_run_id=self._last_run_id,
                last_outcome=self._last_outcome,
                last_error=self._last_error,
            )
