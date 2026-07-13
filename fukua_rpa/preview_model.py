"""Pure coordinate preview planning for clicks, paths, hovers and drags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .task_model import (
    build_coord_step_positions,
    config_bool,
    parse_coord_step_manual_points,
    parse_coordinate_sequence,
    parse_coordinate_text,
    parse_float_text,
)


@dataclass(frozen=True)
class PreviewPlan:
    points: tuple[tuple[float, float], ...]
    labels: tuple[str, ...]
    line_segments: tuple[dict[str, Any], ...]
    truncated: bool = False


def coordinate_preview_options(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "every": max(1, int(parse_float_text(task.get("coord_step_every", 1), 1))),
        "direction": str(task.get("coord_step_direction", "向下")),
        "distance": parse_float_text(task.get("coord_step_distance", 0), 0.0),
        "dx": parse_float_text(task.get("coord_step_dx", 0), 0.0),
        "dy": parse_float_text(task.get("coord_step_dy", 0), 0.0),
        "point": str(task.get("coord_step_point", "")).strip(),
        "max_steps": max(0, int(parse_float_text(task.get("coord_step_max_steps", 0), 0.0))),
        "max_distance": max(
            0.0, parse_float_text(task.get("coord_step_max_distance", 0), 0.0)
        ),
        "reset_after": max(
            0, int(parse_float_text(task.get("coord_step_reset_after", 0), 0.0))
        ),
        "manual_points": parse_coord_step_manual_points(
            task.get("coord_step_manual_points", "{}")
        ),
    }


def build_preview_line_segments(step_groups, internal_segments=None):
    groups = [group for group in step_groups if group.get("rep") is not None]
    segments = list(internal_segments or [])
    for index in range(len(groups) - 1):
        segments.append(
            {"from": groups[index]["rep"], "to": groups[index + 1]["rep"], "style": "solid"}
        )
    for index, group in enumerate(groups):
        extras = group.get("extras", [])
        if not extras:
            continue
        previous = groups[index - 1]["rep"] if index > 0 else group["rep"]
        following = groups[index + 1]["rep"] if index + 1 < len(groups) else group["rep"]
        for extra in extras:
            if previous != extra:
                segments.append({"from": previous, "to": extra, "style": "dash"})
            if following != extra and following != previous:
                segments.append({"from": extra, "to": following, "style": "dash"})
    return segments


def build_coordinate_preview(
    tasks: Sequence[Mapping[str, Any]], max_points: int = 800
) -> PreviewPlan:
    limit = max(1, int(max_points))
    points: list[tuple[float, float]] = []
    labels: list[str] = []
    step_groups: list[dict[str, Any]] = []
    internal_segments: list[dict[str, Any]] = []
    truncated = False

    def add_point(point, label):
        nonlocal truncated
        if truncated:
            return None
        points.append((float(point[0]), float(point[1])))
        labels.append(str(label))
        point_index = len(points) - 1
        if len(points) >= limit:
            truncated = True
        return point_index

    def add_step_group(representative, extras=None):
        if representative is not None:
            step_groups.append({"rep": representative, "extras": list(extras or [])})

    def finish():
        segments = build_preview_line_segments(step_groups, internal_segments)
        return PreviewPlan(tuple(points), tuple(labels), tuple(segments), truncated)

    for task_index, task in enumerate(tasks, 1):
        try:
            command = float(task.get("type", 0))
        except (TypeError, ValueError):
            continue
        coordinate = parse_coordinate_text(task.get("value", ""))
        if command in (1.0, 2.0, 3.0) and coordinate:
            if config_bool(task.get("coord_sequence_en", False)):
                indices = []
                for sequence_index, point in enumerate(
                    parse_coordinate_sequence(task.get("coord_sequence_points", "")), 1
                ):
                    point_index = add_point(point, f"{task_index}序{sequence_index}")
                    if point_index is not None:
                        indices.append(point_index)
                    if truncated:
                        add_step_group(indices[0] if indices else None, indices[1:])
                        return finish()
                add_step_group(indices[0] if indices else None, indices[1:])
                continue

            step_points = [coordinate]
            if config_bool(task.get("coord_step_en", False)):
                step_points = build_coord_step_positions(
                    coordinate[0],
                    coordinate[1],
                    coordinate_preview_options(task),
                    max_points=120,
                )
            indices = []
            for point_index, point in enumerate(step_points, 1):
                label = f"{task_index}" if len(step_points) == 1 else f"{task_index}-{point_index}"
                added = add_point(point, label)
                if added is not None:
                    indices.append(added)
                if truncated:
                    add_step_group(indices[0] if indices else None, indices[1:])
                    return finish()
            add_step_group(indices[0] if indices else None, indices[1:])
            continue

        if command == 8.0 and coordinate:
            added = add_point(coordinate, f"{task_index}悬")
            add_step_group(added)
            if truncated:
                return finish()
            continue

        if command in (10.0, 11.0):
            parts = str(task.get("value", "")).split("->")
            if len(parts) != 2:
                continue
            start = parse_coordinate_text(parts[0])
            end = parse_coordinate_text(parts[1])
            if not start or not end:
                continue
            prefix = f"{task_index}左拖" if command == 10.0 else f"{task_index}右拖"
            start_index = add_point(start, f"{prefix}起")
            if truncated:
                add_step_group(start_index)
                return finish()
            end_index = add_point(end, f"{prefix}终")
            if start_index is not None and end_index is not None:
                internal_segments.append(
                    {"from": start_index, "to": end_index, "style": "solid"}
                )
            add_step_group(start_index)
            if truncated:
                return finish()
    return finish()
