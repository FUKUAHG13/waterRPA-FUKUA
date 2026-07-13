"""Low-overhead bounded runtime timing and counter collection."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


DEFAULT_SAMPLE_LIMIT = 256


def _percentile(sorted_values, percentile):
    if not sorted_values:
        return 0
    rank = max(0, math.ceil((float(percentile) / 100.0) * len(sorted_values)) - 1)
    return sorted_values[min(rank, len(sorted_values) - 1)]


@dataclass
class _TimingSeries:
    sample_limit: int
    count: int = 0
    total_ns: int = 0
    max_ns: int = 0
    samples_ns: deque = field(init=False)

    def __post_init__(self):
        self.samples_ns = deque(maxlen=self.sample_limit)

    def observe(self, elapsed_ns):
        value = max(0, int(elapsed_ns))
        self.count += 1
        self.total_ns += value
        self.max_ns = max(self.max_ns, value)
        self.samples_ns.append(value)

    def snapshot(self):
        samples = sorted(self.samples_ns)
        sampled_count = len(samples)
        return {
            "count": self.count,
            "sampled_count": sampled_count,
            "total_ms": round(self.total_ns / 1_000_000.0, 3),
            "mean_ms": round(
                (self.total_ns / self.count) / 1_000_000.0 if self.count else 0.0,
                3,
            ),
            "p50_ms": round(_percentile(samples, 50) / 1_000_000.0, 3),
            "p95_ms": round(_percentile(samples, 95) / 1_000_000.0, 3),
            "max_ms": round(self.max_ns / 1_000_000.0, 3),
        }


class PerformanceMetrics:
    """Collect bounded timings plus unbounded integer counters and gauges.

    Timings retain only a small rolling sample for percentiles while totals keep
    the full-run count. This keeps memory stable during indefinite automation.
    """

    def __init__(self, sample_limit=DEFAULT_SAMPLE_LIMIT):
        self.sample_limit = max(16, int(sample_limit))
        self._lock = threading.RLock()
        self.reset()

    def reset(self):
        with self._lock:
            self._started_ns = time.perf_counter_ns()
            self._timings = {}
            self._counters = defaultdict(int)
            self._gauges = {}

    def observe_ns(self, name, elapsed_ns):
        key = str(name)
        with self._lock:
            series = self._timings.get(key)
            if series is None:
                series = _TimingSeries(self.sample_limit)
                self._timings[key] = series
            series.observe(elapsed_ns)

    def observe_since(self, name, started_ns):
        self.observe_ns(name, time.perf_counter_ns() - int(started_ns))

    def increment(self, name, amount=1):
        with self._lock:
            self._counters[str(name)] += int(amount)

    def set_gauge(self, name, value):
        with self._lock:
            self._gauges[str(name)] = value

    def snapshot(self):
        with self._lock:
            elapsed_ns = max(0, time.perf_counter_ns() - self._started_ns)
            return {
                "elapsed_seconds": round(elapsed_ns / 1_000_000_000.0, 3),
                "sample_limit": self.sample_limit,
                "timings": {
                    name: series.snapshot()
                    for name, series in sorted(self._timings.items())
                },
                "counters": dict(sorted(self._counters.items())),
                "gauges": dict(sorted(self._gauges.items())),
            }


def merge_performance_snapshots(*snapshots):
    """Return named snapshots unchanged while filtering absent values."""
    return {
        str(name): report
        for name, report in snapshots
        if isinstance(report, dict) and report
    }


def concise_performance_summary(report):
    """Format high-signal run metrics without exposing task content or paths."""
    if not isinstance(report, dict):
        return "暂无性能数据"
    timings = report.get("timings", {})
    counters = report.get("counters", {})
    parts = [f"运行 {float(report.get('elapsed_seconds', 0.0)):.1f}s"]
    for key, label in (
        ("vision.search", "识别"),
        ("screenshot.total", "截图"),
        ("match.native", "DLL匹配"),
        ("match.opencv", "OpenCV匹配"),
        ("action.total", "步骤执行"),
        ("ui.log_append", "日志刷新"),
    ):
        metric = timings.get(key)
        if metric and metric.get("count", 0):
            parts.append(
                f"{label} P50/P95 {metric['p50_ms']:.1f}/{metric['p95_ms']:.1f}ms"
            )
    fallback_count = int(counters.get("screenshot.fallbacks", 0))
    if fallback_count:
        parts.append(f"截图回退 {fallback_count} 次")
    return "；".join(parts)
