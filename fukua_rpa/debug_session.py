"""Thread-safe breakpoint and step-over coordination for one engine run."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable


@dataclass(frozen=True)
class DebugSnapshot:
    active: bool
    paused: bool
    pause_requested: bool
    pause_before_next: bool
    step: int
    loop: int
    command: str
    reason: str
    detail: str


class DebugSession:
    def __init__(self):
        self._condition = threading.Condition(threading.RLock())
        self._active = False
        self._paused = False
        self._pause_requested = False
        self._pause_before_next = False
        self._cancelled = False
        self._step = 0
        self._loop = 0
        self._command = ""
        self._reason = ""
        self._detail = ""

    def reset(self) -> None:
        with self._condition:
            self._active = True
            self._paused = False
            self._pause_requested = False
            self._pause_before_next = False
            self._cancelled = False
            self._step = 0
            self._loop = 0
            self._command = ""
            self._reason = ""
            self._detail = ""
            self._condition.notify_all()

    def finish(self) -> None:
        with self._condition:
            self._active = False
            self._paused = False
            self._pause_requested = False
            self._pause_before_next = False
            self._condition.notify_all()

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._active = False
            self._paused = False
            self._condition.notify_all()

    def request_pause(self) -> bool:
        with self._condition:
            if not self._active or self._cancelled or self._paused:
                return False
            self._pause_requested = True
            return True

    def continue_run(self) -> bool:
        with self._condition:
            if not self._active or not self._paused:
                return False
            self._pause_before_next = False
            self._paused = False
            self._condition.notify_all()
            return True

    def step_over(self) -> bool:
        with self._condition:
            if not self._active or not self._paused:
                return False
            self._pause_before_next = True
            self._paused = False
            self._condition.notify_all()
            return True

    def before_step(
        self,
        *,
        step: int,
        loop: int,
        command: str,
        breakpoint: bool,
        breakpoint_reason: str = "breakpoint",
        breakpoint_detail: str = "",
        stop_requested: Callable[[], bool] | None = None,
        callback: Callable[[dict], None] | None = None,
    ) -> tuple[bool, float]:
        with self._condition:
            if not self._active or self._cancelled:
                return not self._cancelled, 0.0
            reason = ""
            if self._pause_requested:
                reason = "pause_requested"
                self._pause_requested = False
            elif self._pause_before_next:
                reason = "step_over"
                self._pause_before_next = False
            elif breakpoint:
                reason = str(breakpoint_reason or "breakpoint")
            if not reason:
                return True, 0.0
            self._paused = True
            self._step = max(0, int(step))
            self._loop = max(0, int(loop))
            self._command = str(command or "")
            self._reason = reason
            self._detail = str(breakpoint_detail or "")[:500]
            paused_event = {
                "state": "paused",
                "step": self._step,
                "loop": self._loop,
                "command": self._command,
                "reason": reason,
                "detail": self._detail,
            }

        self._emit(callback, paused_event)
        started = time.monotonic()
        with self._condition:
            while self._paused and self._active and not self._cancelled:
                if stop_requested and stop_requested():
                    self._cancelled = True
                    self._active = False
                    self._paused = False
                    break
                self._condition.wait(0.1)
            allowed = self._active and not self._cancelled
            duration = max(0.0, time.monotonic() - started)
            resumed_event = {
                "state": "resumed" if allowed else "cancelled",
                "step": self._step,
                "loop": self._loop,
                "command": self._command,
                "reason": self._reason,
                "detail": self._detail,
                "paused_ms": duration * 1000.0,
            }
            if not self._paused:
                self._reason = ""
                self._detail = ""
        self._emit(callback, resumed_event)
        return allowed, duration

    def snapshot(self) -> DebugSnapshot:
        with self._condition:
            return DebugSnapshot(
                active=self._active,
                paused=self._paused,
                pause_requested=self._pause_requested,
                pause_before_next=self._pause_before_next,
                step=self._step,
                loop=self._loop,
                command=self._command,
                reason=self._reason,
                detail=self._detail,
            )

    def as_dict(self) -> dict:
        return asdict(self.snapshot())

    @staticmethod
    def _emit(callback: Callable[[dict], None] | None, payload: dict) -> None:
        if not callback:
            return
        try:
            callback(dict(payload))
        except Exception:
            pass
