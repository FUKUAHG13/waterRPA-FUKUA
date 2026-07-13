import unittest

from fukua_rpa.performance import PerformanceMetrics, concise_performance_summary


class PerformanceMetricsTests(unittest.TestCase):
    def test_timings_keep_bounded_samples_and_full_totals(self):
        metrics = PerformanceMetrics(sample_limit=16)
        for value in range(1, 101):
            metrics.observe_ns("match.opencv", value * 1_000_000)

        report = metrics.snapshot()
        timing = report["timings"]["match.opencv"]
        self.assertEqual(timing["count"], 100)
        self.assertEqual(timing["sampled_count"], 16)
        self.assertEqual(timing["total_ms"], 5050.0)
        self.assertEqual(timing["p50_ms"], 92.0)
        self.assertEqual(timing["p95_ms"], 100.0)

    def test_reset_clears_run_data(self):
        metrics = PerformanceMetrics()
        metrics.observe_ns("screenshot.total", 2_000_000)
        metrics.increment("screenshot.fallbacks")
        metrics.set_gauge("template.cache_bytes", 1024)
        metrics.reset()

        report = metrics.snapshot()
        self.assertEqual(report["timings"], {})
        self.assertEqual(report["counters"], {})
        self.assertEqual(report["gauges"], {})

    def test_summary_uses_only_available_high_signal_metrics(self):
        metrics = PerformanceMetrics()
        metrics.observe_ns("screenshot.total", 3_000_000)
        metrics.increment("screenshot.fallbacks", 2)
        summary = concise_performance_summary(metrics.snapshot())
        self.assertIn("截图 P50/P95 3.0/3.0ms", summary)
        self.assertIn("截图回退 2 次", summary)


if __name__ == "__main__":
    unittest.main()
