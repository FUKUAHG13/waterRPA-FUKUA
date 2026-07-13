"""Repeatable micro-benchmark for pure scheduling, preview and migration paths."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fukua_rpa.config_schema import default_profile_config, migrate_profile_config
from fukua_rpa.preview_model import build_coordinate_preview
from fukua_rpa.scheduler import next_runnable_loop
from fukua_rpa.workflow_analysis import build_workflow_graph


def timed(callable_, rounds=7):
    values = []
    for _index in range(rounds):
        start = time.perf_counter()
        callable_()
        values.append((time.perf_counter() - start) * 1000)
    return {"median_ms": statistics.median(values), "max_ms": max(values), "samples_ms": values}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assert-limits", action="store_true")
    args = parser.parse_args()
    tasks = [
        {
            "type": 1.0,
            "value": f"{index},{index}",
            "coord_step_en": index % 10 == 0,
            "coord_step_direction": "移动到新点位",
            "coord_step_point": f"{index + 20},{index + 40}",
            "coord_step_max_steps": "8",
            "step_loop_start": str(index % 50 + 1),
        }
        for index in range(5000)
    ]
    profile = default_profile_config()
    profile["tasks"] = tasks
    report = {
        "migration_5000_steps": timed(lambda: migrate_profile_config(profile), args.rounds),
        "preview_5000_steps": timed(lambda: build_coordinate_preview(tasks, 800), args.rounds),
        "workflow_graph_5000_steps": timed(lambda: build_workflow_graph(tasks), args.rounds),
        "next_loop_5000_steps": timed(
            lambda: next_runnable_loop(
                tasks,
                1,
                start_step_index=0,
                loop_start_round=1,
                loop_end_round=0,
                loop_mode="无限",
                loop_value=1,
                exhausted=lambda _task, _step: False,
            ),
            args.rounds,
        ),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    if args.assert_limits:
        limits = {
            "migration_5000_steps": 250.0,
            "preview_5000_steps": 250.0,
            "workflow_graph_5000_steps": 250.0,
            "next_loop_5000_steps": 250.0,
        }
        failures = [
            name for name, limit in limits.items() if report[name]["median_ms"] > limit
        ]
        if failures:
            raise SystemExit(f"Benchmark limits exceeded: {failures}")


if __name__ == "__main__":
    main()
