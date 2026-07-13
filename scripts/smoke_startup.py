"""Launch fukuaRPA once and validate staged-startup timing markers."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def validate_report(report, *, assert_limits=False):
    if not report.get("ok"):
        raise RuntimeError(f"Startup smoke failed: {report}")
    timing_names = (
        "python_to_shell_first_paint_ms",
        "workspace_import_ms",
        "workspace_visible_ms",
        "runtime_ready_ms",
        "runtime_backend_ms",
    )
    timings = {}
    for name in timing_names:
        try:
            value = float(report[name])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Startup smoke has no valid {name}: {report}") from error
        if value < 0.0:
            raise RuntimeError(f"Startup smoke has a negative {name}: {report}")
        timings[name] = value
    if timings["workspace_visible_ms"] < timings["python_to_shell_first_paint_ms"]:
        raise RuntimeError(f"Workspace appeared before the startup shell: {report}")
    if timings["runtime_ready_ms"] < timings["workspace_visible_ms"]:
        raise RuntimeError(f"Runtime initialized before the workspace handoff: {report}")
    if assert_limits:
        limits = {
            "python_to_shell_first_paint_ms": 5_000.0,
            "workspace_visible_ms": 15_000.0,
            "runtime_ready_ms": 30_000.0,
        }
        exceeded = {
            name: (timings[name], limit)
            for name, limit in limits.items()
            if timings[name] > limit
        }
        if exceeded:
            raise RuntimeError(f"Startup timing limit exceeded: {exceeded}")
    return timings


def run_startup_smoke(executable=None, *, timeout=60, assert_limits=False):
    env = os.environ.copy()
    if executable:
        command = [str(Path(executable).resolve())]
        cwd = Path(executable).resolve().parent
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
        command = [sys.executable, str(ROOT / "fukuaRPA.py")]
        cwd = ROOT
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "startup-smoke.json"
        runtime_dir = Path(temp_dir) / "runtime"
        subprocess.run(
            [
                *command,
                "--startup-smoke-file",
                str(report_path),
                "--startup-runtime-dir",
                str(runtime_dir),
            ],
            cwd=cwd,
            env=env,
            check=True,
            timeout=max(5, int(timeout)),
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_report(report, assert_limits=assert_limits)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--assert-limits", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_startup_smoke(
        args.executable,
        timeout=args.timeout,
        assert_limits=args.assert_limits,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
