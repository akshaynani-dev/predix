"""Tests for best-effort measured process resource telemetry."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core import resource_metrics


class ProcessResourceMetricTests(unittest.TestCase):
    def setUp(self):
        self.previous_sample = resource_metrics._previous_sample
        resource_metrics._previous_sample = None

    def tearDown(self):
        resource_metrics._previous_sample = self.previous_sample

    def test_reports_peak_rss_and_samples_cpu_between_requests(self):
        usage = SimpleNamespace(ru_utime=2.0, ru_stime=1.0, ru_maxrss=100 * 1024 * 1024)
        fake_resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: usage)
        with patch.object(resource_metrics, "resource", fake_resource), \
             patch.object(resource_metrics.time, "monotonic", side_effect=[10.0, 12.0]), \
             patch.object(resource_metrics.sys, "platform", "darwin"):
            first = resource_metrics.process_resource_metrics(device="cpu")
            usage.ru_utime = 2.4
            second = resource_metrics.process_resource_metrics(device="cpu")

        self.assertIsNone(first["process_cpu_percent_of_one_core"])
        self.assertEqual(first["process_peak_rss_mb_since_start"], 100.0)
        self.assertEqual(second["process_cpu_percent_of_one_core"], 20.0)
        self.assertEqual(second["process_cpu_seconds_since_start"], 3.4)

    def test_reports_mps_allocated_memory_only_when_device_is_mps(self):
        fake_resource = SimpleNamespace(
            RUSAGE_SELF=0,
            getrusage=lambda _: SimpleNamespace(ru_utime=0.0, ru_stime=0.0, ru_maxrss=1024),
        )
        torch_module = SimpleNamespace(mps=SimpleNamespace(current_allocated_memory=lambda: 8 * 1024 * 1024))
        with patch.object(resource_metrics, "resource", fake_resource), \
             patch.object(resource_metrics.time, "monotonic", return_value=1.0), \
             patch.object(resource_metrics.sys, "platform", "linux"):
            metrics = resource_metrics.process_resource_metrics(device="mps", torch_module=torch_module)

        self.assertEqual(metrics["mps_allocated_mb"], 8.0)
        self.assertEqual(metrics["process_peak_rss_mb_since_start"], 1.0)
        self.assertIn("not total device memory", metrics["measurement_notes"]["mps_memory"])

    def test_unavailable_counters_are_reported_without_failing_health(self):
        fake_resource = SimpleNamespace(
            RUSAGE_SELF=0,
            getrusage=lambda _: (_ for _ in ()).throw(OSError("counter unavailable")),
        )
        with patch.object(resource_metrics, "resource", fake_resource), \
             patch.object(resource_metrics.time, "monotonic", return_value=1.0):
            metrics = resource_metrics.process_resource_metrics(device="cpu")

        self.assertEqual(metrics["status"], "unavailable")
        self.assertIsNone(metrics["process_cpu_percent_of_one_core"])
        self.assertIsNone(metrics["process_peak_rss_mb_since_start"])


if __name__ == "__main__":
    unittest.main()
