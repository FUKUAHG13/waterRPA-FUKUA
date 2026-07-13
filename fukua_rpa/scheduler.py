"""Pure scheduling helpers shared by the execution engine and tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def positive_int(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return int(default)


def non_negative_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return int(default)


def task_active_in_loop(task: Mapping[str, Any] | None, loop_count: int) -> bool:
    if not task:
        return False
    start = positive_int(task.get("step_loop_start", 1), 1)
    end = non_negative_int(task.get("step_loop_end", 0), 0)
    return loop_count >= start and not (end > 0 and loop_count > end)


def loop_number_allowed(
    loop_count: int,
    *,
    loop_mode: str,
    loop_value: float,
    loop_end_round: int,
) -> bool:
    if loop_end_round > 0 and loop_count > loop_end_round:
        return False
    if loop_mode == "单次" and loop_count > 1:
        return False
    if loop_mode == "指定次数" and loop_count > loop_value:
        return False
    return True


def next_runnable_loop(
    tasks: Sequence[Mapping[str, Any]],
    after_loop: int,
    *,
    start_step_index: int,
    loop_start_round: int,
    loop_end_round: int,
    loop_mode: str,
    loop_value: float,
    exhausted: Callable[[Mapping[str, Any], int], bool],
) -> int | None:
    if loop_mode == "单次" or not tasks:
        return None
    start_index = min(max(int(start_step_index), 0), len(tasks) - 1)
    candidates: list[int] = []
    for index in range(start_index, len(tasks)):
        task = tasks[index]
        if exhausted(task, index + 1):
            continue
        step_start = positive_int(task.get("step_loop_start", 1), 1)
        step_end = non_negative_int(task.get("step_loop_end", 0), 0)
        candidate = max(int(after_loop) + 1, loop_start_round, step_start)
        if step_end > 0 and candidate > step_end:
            continue
        if loop_number_allowed(
            candidate,
            loop_mode=loop_mode,
            loop_value=loop_value,
            loop_end_round=loop_end_round,
        ):
            candidates.append(candidate)
    return min(candidates) if candidates else None


def is_wait_command(command: Any) -> bool:
    try:
        return float(command) == 5.0
    except (TypeError, ValueError):
        return False
