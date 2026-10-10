"""Tests for grouped occupancy-signal alerts and their evidence."""

import unittest

from app.analytics.occupancy_alerts import build_occupancy_signal_alerts


class OccupancyAlertTests(unittest.TestCase):
    def test_combined_capacity_and_deviation_produce_one_evidence_linked_warning(self):
        zone = {
            "zone_id": "entry", "name": "Main Entrance",
            "current_estimate": 18, "configured_capacity": 20,
            "capacity_ratio": 0.9, "capacity_status": "HIGH",
            "occupancy_anomaly": {
                "status": "deviation_signal",
                "latest_signal": {
                    "evidence": "Observed occupancy exceeded the configured baseline.",
                    "baseline_median": 4, "observed_occupancy": 18,
                    "increase_over_baseline": 14,
                },
            },
            "early_warning": {"status": "elevated"},
            "security_attention": {"recommendation": "Human review recommended."},
        }
        alerts = build_occupancy_signal_alerts([zone], observed_at="2026-10-10T12:00:00+00:00")
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert["severity"], "WARNING")
        self.assertEqual(alert["timestamp"], "2026-10-10T12:00:00+00:00")
        self.assertEqual(alert["zone"], "Main Entrance")
        self.assertEqual(alert["status"], "active")
        self.assertEqual(len(alert["supporting_evidence"]), 2)
        self.assertIsNone(alert["confidence"])
        self.assertIn("not_incident_alert", alert["category"])

    def test_configured_critical_capacity_is_reported_without_incident_claim(self):
        alert = build_occupancy_signal_alerts([{
            "zone_id": "hall", "name": "Hall", "current_estimate": 20,
            "configured_capacity": 20, "capacity_ratio": 1.0,
            "capacity_status": "CRITICAL",
        }])[0]
        self.assertEqual(alert["severity"], "CRITICAL")
        self.assertIn("does not identify a threat", alert["limitations"])

    def test_deviation_without_capacity_is_watch_and_empty_signals_return_no_alert(self):
        deviation = {
            "zone_id": "quiet", "name": "Quiet Zone",
            "occupancy_anomaly": {
                "status": "deviation_signal",
                "latest_signal": {"evidence": "Measured deviation."},
            },
        }
        alerts = build_occupancy_signal_alerts([deviation, {"zone_id": "normal"}])
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "WATCH")
        self.assertEqual(alerts[0]["signal"], "recent_occupancy_deviation")


if __name__ == "__main__":
    unittest.main()
