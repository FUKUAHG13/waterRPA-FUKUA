"""Convert low-level hook events into compact, replayable workflow tasks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class RecordedEvent:
    started: float
    kind: str
    value: Any
    ended: float


def _event(value) -> RecordedEvent:
    if isinstance(value, RecordedEvent):
        return value
    if len(value) >= 4:
        started, kind, payload, ended = value[:4]
    else:
        started, kind, payload = value[:3]
        ended = started
    started = float(started)
    ended = max(started, float(ended))
    return RecordedEvent(started, str(kind), payload, ended)


def _near(first, second, tolerance=5) -> bool:
    try:
        return (
            abs(int(first[0]) - int(second[0])) <= tolerance
            and abs(int(first[1]) - int(second[1])) <= tolerance
        )
    except (TypeError, ValueError, IndexError):
        return False


def _scroll_steps(raw_delta) -> int:
    try:
        value = int(raw_delta)
    except (TypeError, ValueError):
        return 0
    if value == 0:
        return 0
    return int(math.copysign(max(1, round(abs(value) / 120)), value))


def aggregate_recorded_events(
    events: Iterable,
    *,
    double_click_seconds: float = 0.5,
    scroll_merge_seconds: float = 0.25,
) -> list[RecordedEvent]:
    ordered = sorted((_event(item) for item in events), key=lambda item: item.started)
    result: list[RecordedEvent] = []
    index = 0
    while index < len(ordered):
        current = ordered[index]
        if current.kind == "left" and index + 1 < len(ordered):
            following = ordered[index + 1]
            if (
                following.kind == "left"
                and following.started - current.ended <= double_click_seconds
                and _near(current.value, following.value)
            ):
                result.append(
                    RecordedEvent(
                        current.started,
                        "left_double",
                        following.value,
                        following.ended,
                    )
                )
                index += 2
                continue
        if current.kind == "scroll":
            total = _scroll_steps(current.value)
            ended = current.ended
            cursor = index + 1
            while cursor < len(ordered):
                following = ordered[cursor]
                if (
                    following.kind != "scroll"
                    or following.started - ended > scroll_merge_seconds
                ):
                    break
                total += _scroll_steps(following.value)
                ended = following.ended
                cursor += 1
            if total:
                result.append(RecordedEvent(current.started, "scroll", total, ended))
            index = cursor
            continue
        result.append(current)
        index += 1
    return result


def recorded_events_to_tasks(
    events: Iterable,
    *,
    wait_threshold: float = 0.15,
    double_click_seconds: float = 0.5,
    scroll_merge_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    previous_end: float | None = None
    aggregated = aggregate_recorded_events(
        events,
        double_click_seconds=double_click_seconds,
        scroll_merge_seconds=scroll_merge_seconds,
    )
    for event in aggregated:
        if previous_end is not None:
            delay = max(0.0, event.started - previous_end)
            if delay > wait_threshold:
                tasks.append({"type": 5.0, "value": f"{delay:.2f}"})
        previous_end = event.ended

        if event.kind == "left":
            tasks.append({"type": 1.0, "value": f"{event.value[0]},{event.value[1]}"})
        elif event.kind == "left_double":
            tasks.append({"type": 2.0, "value": f"{event.value[0]},{event.value[1]}"})
        elif event.kind == "right":
            tasks.append({"type": 3.0, "value": f"{event.value[0]},{event.value[1]}"})
        elif event.kind in ("left_drag", "right_drag"):
            command = 10.0 if event.kind == "left_drag" else 11.0
            tasks.append(
                {
                    "type": command,
                    "value": (
                        f"{event.value[0]},{event.value[1]} -> "
                        f"{event.value[2]},{event.value[3]}"
                    ),
                    "recorded_duration": round(
                        max(0.05, event.ended - event.started), 3
                    ),
                }
            )
        elif event.kind == "scroll":
            tasks.append({"type": 6.0, "value": str(int(event.value))})
        elif event.kind in ("key", "hotkey") and str(event.value).strip():
            tasks.append({"type": 7.0, "value": str(event.value).strip()})
    return tasks
