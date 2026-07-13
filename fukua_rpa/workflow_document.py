"""Stable task identity and branch-reference operations for workflow editing."""

from __future__ import annotations

import copy
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


REFERENCE_FIELDS = (
    ("success_jump", "success_target_id", "成功后跳至"),
    ("fail_jump", "fail_target_id", "失败后跳至"),
    ("until_false_jump", "until_false_target_id", "未满足跳回"),
    ("until_true_jump", "until_true_target_id", "满足后跳至"),
)
_STEP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _reference_applies(task: Mapping[str, Any], jump_field: str) -> bool:
    if not jump_field.startswith("until_"):
        return True
    try:
        return float(task.get("type", 0)) == 15.0
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class TaskReference:
    source_index: int
    source_id: str
    field: str
    label: str


def new_step_id() -> str:
    return uuid.uuid4().hex


def valid_step_id(value: Any) -> bool:
    return bool(_STEP_ID_RE.fullmatch(str(value or "").strip()))


def _jump_number(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def normalize_workflow_tasks(
    tasks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return detached tasks with unique IDs and synchronized display jumps."""

    normalized = [copy.deepcopy(dict(task)) for task in tasks]
    seen: set[str] = set()
    for task in normalized:
        step_id = str(task.get("step_id", "")).strip()
        if not valid_step_id(step_id) or step_id in seen:
            step_id = new_step_id()
        task["step_id"] = step_id
        seen.add(step_id)

    index_by_id = {
        str(task["step_id"]): index for index, task in enumerate(normalized)
    }
    for task in normalized:
        for jump_field, target_field, _label in REFERENCE_FIELDS:
            if not _reference_applies(task, jump_field):
                task[target_field] = ""
                continue
            target_id = str(task.get(target_field, "") or "").strip()
            if target_id in index_by_id:
                task[target_field] = target_id
                task[jump_field] = str(index_by_id[target_id] + 1)
                continue
            jump = _jump_number(task.get(jump_field, 0))
            if 1 <= jump <= len(normalized):
                target_id = str(normalized[jump - 1]["step_id"])
                task[target_field] = target_id
                task[jump_field] = str(jump)
            else:
                task[target_field] = ""
                task[jump_field] = "0"
    return normalized


def apply_numeric_reference_edits(
    task: Mapping[str, Any], ordered_tasks: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Resolve branch numbers explicitly edited in a task dialog to stable IDs."""

    ordered = normalize_workflow_tasks(ordered_tasks)
    result = copy.deepcopy(dict(task))
    for jump_field, target_field, _label in REFERENCE_FIELDS:
        if not _reference_applies(result, jump_field):
            result[target_field] = ""
            continue
        jump = _jump_number(result.get(jump_field, 0))
        if 1 <= jump <= len(ordered):
            result[target_field] = str(ordered[jump - 1]["step_id"])
            result[jump_field] = str(jump)
        else:
            result[target_field] = ""
            result[jump_field] = "0"
    return result


def clone_task_for_insert(task: Mapping[str, Any]) -> dict[str, Any]:
    """Clone one task while preserving external references and rebasing self-jumps."""

    cloned = copy.deepcopy(dict(task))
    old_id = str(cloned.get("step_id", "") or "")
    cloned["step_id"] = new_step_id()
    for jump_field, target_field, _label in REFERENCE_FIELDS:
        if not _reference_applies(cloned, jump_field):
            cloned[target_field] = ""
            continue
        if old_id and str(cloned.get(target_field, "") or "") == old_id:
            cloned[target_field] = cloned["step_id"]
    return cloned


def references_to_step(
    tasks: Sequence[Mapping[str, Any]], target_id: str
) -> list[TaskReference]:
    target_id = str(target_id or "").strip()
    references: list[TaskReference] = []
    if not target_id:
        return references
    for index, task in enumerate(tasks):
        source_id = str(task.get("step_id", "") or "")
        for jump_field, target_field, label in REFERENCE_FIELDS:
            if not _reference_applies(task, jump_field):
                continue
            if str(task.get(target_field, "") or "") == target_id:
                references.append(
                    TaskReference(index + 1, source_id, target_field, label)
                )
    return references


def remove_task_and_clear_references(
    tasks: Sequence[Mapping[str, Any]], target_id: str
) -> list[dict[str, Any]]:
    """Remove a task and turn references to it into normal fall-through branches."""

    target_id = str(target_id or "").strip()
    remaining = [
        copy.deepcopy(dict(task))
        for task in tasks
        if str(task.get("step_id", "") or "") != target_id
    ]
    for task in remaining:
        for jump_field, target_field, _label in REFERENCE_FIELDS:
            if not _reference_applies(task, jump_field):
                task[target_field] = ""
                continue
            if str(task.get(target_field, "") or "") == target_id:
                task[target_field] = ""
                task[jump_field] = "0"
    return normalize_workflow_tasks(remaining)


def materialize_runtime_references(
    tasks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Produce a runtime snapshot whose numeric jumps match stable references."""

    return normalize_workflow_tasks(tasks)
