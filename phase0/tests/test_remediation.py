"""Deterministic regression checks for the isolated Phase 0 remediation path."""

import inspect
import json
from pathlib import Path
import unittest

from phase0.remediation_generator import (load_remediation_observations,
                                         load_remediation_oracle)
from phase0.remediation_quality import FROZEN_THRESHOLDS
from phase0.remediation_algorithms import reconstruct
from phase0.remediation_runner import run_remediation_isolated
from phase0.remediation_evaluator import evaluate_remediation
from phase0.remediation_experiment import _integrity_audit


ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = {**FROZEN_THRESHOLDS, "relative_background_noise_mad_max": 1.5}


class Phase0RemediationTests(unittest.TestCase):
    def test_remediation_algorithm_has_no_oracle_dependency(self):
        source = inspect.getsource(reconstruct).lower()
        self.assertNotIn("generator", source)
        self.assertNotIn("evaluator", source)
        self.assertNotIn("true_transforms", source)
        self.assertNotIn("clean_reference", source)

    def test_failure_classes_are_rejected_without_good_frame_loss(self):
        fixture_id = "remed-001-development-outlier-80"
        obs, _ = load_remediation_observations(ROOT / "fixtures", fixture_id)
        record, images, _ = run_remediation_isolated(obs, thresholds=THRESHOLDS)
        # Oracle loading occurs only after the isolated worker has returned.
        oracle = load_remediation_oracle(ROOT / "fixtures", fixture_id)
        measured = evaluate_remediation(obs, oracle, record, images)
        for class_name in ("strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed"):
            result = measured["frame_rejection_by_class"][class_name]
            self.assertGreaterEqual(result["recall"], 0.90, class_name)
        self.assertEqual(measured["good_frame_false_rejection_rate"], 0.0)
        self.assertTrue(_integrity_audit(obs, record, images)["pass"])
        self.assertEqual(record["deconvolution"], "disabled")

    def test_wider_motion_stress_keeps_clean_frames_and_registration(self):
        fixture_id = "remed-001-development-motion-stress32"
        obs, _ = load_remediation_observations(ROOT / "fixtures", fixture_id)
        record, images, _ = run_remediation_isolated(obs, thresholds=THRESHOLDS)
        oracle = load_remediation_oracle(ROOT / "fixtures", fixture_id)
        measured = evaluate_remediation(obs, oracle, record, images)
        self.assertEqual(measured["rejected_count"], 0)
        self.assertLessEqual(measured["registration"]["rms_translation_px"], 0.25)
        self.assertGreaterEqual(measured["registration"]["valid_coverage_fraction"], 0.90)
        self.assertTrue(_integrity_audit(obs, record, images)["pass"])


if __name__ == "__main__":
    unittest.main()
