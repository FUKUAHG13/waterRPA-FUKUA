import unittest

from scripts.compare_performance import compare_reports


class PerformanceComparisonTests(unittest.TestCase):
    def baseline(self):
        return {
            "metrics": [
                {
                    "section": "core",
                    "path": "migration.median_ms",
                    "baseline": 10,
                    "max_ratio": 1.5,
                    "slack": 2,
                }
            ]
        }

    def test_relative_regression_passes_inside_threshold(self):
        result = compare_reports(
            self.baseline(), {"core": {"migration": {"median_ms": 14}}}
        )
        self.assertTrue(result["ok"])

    def test_relative_regression_reports_exceeded_metric(self):
        result = compare_reports(
            self.baseline(), {"core": {"migration": {"median_ms": 16}}}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["metric"], "core.migration.median_ms")


if __name__ == "__main__":
    unittest.main()
