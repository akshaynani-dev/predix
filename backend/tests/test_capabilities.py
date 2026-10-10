import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fastapi.testclient import TestClient

from app.main import app
from app.cv.config import cv_settings
from app.cv.runtime import loaded_model_class_names
from database_test_support import IsolatedDatabaseTestCase


class CapabilityTests(IsolatedDatabaseTestCase):
    def test_runtime_class_names_are_read_from_loaded_model_only(self):
        with patch("app.cv.runtime._detector", None):
            self.assertIsNone(loaded_model_class_names())

        detector = SimpleNamespace(_model=SimpleNamespace(names={0: "person", 1: "knife"}))
        with patch("app.cv.runtime._detector", detector):
            self.assertEqual(loaded_model_class_names(), ["person", "knife"])

    def test_unvalidated_security_detection_is_explicitly_unavailable(self):
        with TestClient(app) as client:
            result = client.get("/api/capabilities").json()
        self.assertEqual(result["suspicious_object_detection"]["status"], "unavailable")
        self.assertEqual(result["security_alerts"]["status"], "unavailable")
        self.assertEqual(result["zone_occupancy_forecast"]["horizons_seconds"], [60, 300, 600])
        self.assertEqual(result["live_zone_occupancy_forecast"]["minimum_observation_spans_seconds"]["60"], 360)
        self.assertIn("aggregate_session_summaries_in_sqlite", result["live_zone_occupancy"]["persistence"])
        self.assertEqual(result["live_occupancy_deviation"]["status"], "available_after_seven_consecutive_zone_observations")
        activity = result["detector_activity_deviation"]
        self.assertEqual(activity["default_configuration"], {"bucket_seconds": 15, "baseline_buckets": 6, "mad_multiplier": 3.0, "minimum_increase": 1.0})
        self.assertIn("no imputation", activity["missing_bucket_policy"])
        self.assertIn("not occupancy", activity["interpretation"])
        self.assertEqual(result["early_warning"]["status"], "available_when_configured_capacity_and_occupancy_deviation_cooccur")
        self.assertTrue(result["live_occupancy_signal_alerts"]["not_a_security_or_incident_alert"])
        self.assertEqual(result["risk_classification"]["status"], "unavailable")
        self.assertEqual(result["security_recommendations"]["status"], "zone_review_advisory_when_capacity_is_configured")
        self.assertIn("available_via_live_websocket", result["rtsp_source_adapter"]["session_gateway"])
        self.assertEqual(result["rtsp_source_adapter"]["frontend"], "available_in_live_camera_view")
        self.assertEqual(result["hls_source_adapter"]["status"], "available_when_browser_supports_native_hls")
        self.assertFalse(result["hls_source_adapter"]["backend_fetches_playlist"])
        self.assertTrue(result["human_review_required"])
        detector = result["general_object_detection"]
        self.assertEqual(detector["model"], cv_settings.MODEL_NAME)
        self.assertEqual(detector["configuration"]["confidence_threshold"], cv_settings.DEFAULT_CONF_THRESHOLD)
        self.assertEqual(detector["configuration"]["image_size"], cv_settings.DEFAULT_IMAGE_SIZE)
        self.assertEqual(detector["configuration"]["frame_stride"], cv_settings.FRAME_STRIDE)
        self.assertEqual(detector["configuration"]["device"], cv_settings.DEVICE)
        tracking = result["anonymous_live_tracking"]["configuration"]
        self.assertEqual(tracking["iou_threshold"], cv_settings.TRACK_IOU_THRESHOLD)
        self.assertEqual(tracking["max_missed_frames"], cv_settings.TRACK_MAX_MISSED_FRAMES)
        self.assertIn("every inferred frame", tracking["update_cadence"])

    def test_capabilities_expose_model_labels_only_when_loaded(self):
        with patch("app.api.capabilities.loaded_model_class_names", return_value=None):
            with TestClient(app) as client:
                unloaded = client.get("/api/capabilities").json()
        vocabulary = unloaded["general_object_detection"]["class_vocabulary"]
        self.assertEqual(vocabulary["status"], "not_loaded")
        self.assertIsNone(vocabulary["classes"])

        with patch("app.api.capabilities.loaded_model_class_names", return_value=["person", "knife", "car"]):
            with TestClient(app) as client:
                loaded = client.get("/api/capabilities").json()
        vocabulary = loaded["general_object_detection"]["class_vocabulary"]
        self.assertEqual(vocabulary["status"], "available")
        self.assertEqual(vocabulary["classes"], ["person", "knife", "car"])
        self.assertEqual(vocabulary["potentially_sensitive_label_matches"], ["knife"])
        self.assertEqual(loaded["suspicious_object_detection"]["status"], "unavailable")
