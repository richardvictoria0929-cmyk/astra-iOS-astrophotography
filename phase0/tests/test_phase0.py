import unittest
import inspect
import numpy as np
from pathlib import Path
import tempfile

from phase0.generator import generate_sequence
from phase0.algorithms import phase_translation, warp, wiener_deconvolution
from phase0.runner import run_reconstruction_isolated
from phase0.evaluator import evaluate
from phase0 import algorithms, quality, worker
from phase0.generator import freeze_fixture
from phase0.fixtures import load_observations, load_evaluation_oracle


class Phase0Tests(unittest.TestCase):
    def test_generator_is_deterministic_and_oracle_is_not_observation_metadata(self):
        cfg = {"width": 48, "height": 48, "supersample": 3, "frame_count": 6, "seed": 22,
               "shot_scale": 0.01, "read_noise_sigma": 0.003,
               "exposure_jitter": 0.01, "optical_psf_sigma_px": 0.5,
               "rotation_span_deg": 0.2, "translation_span_px": 0.8}
        a, truth_a = generate_sequence(cfg, fixture_id="determinism", inject_outliers=False)
        b, truth_b = generate_sequence(cfg, fixture_id="determinism", inject_outliers=False)
        np.testing.assert_array_equal(a.frames, b.frames)
        np.testing.assert_array_equal(truth_a.true_transforms, truth_b.true_transforms)
        self.assertFalse(any("truth" in str(v).lower() or "shift" in str(v).lower()
                             for record in a.public_metadata for v in record))

    def test_phase_correlation_subpixel_translation(self):
        rng = np.random.default_rng(8)
        ref = rng.normal(size=(96, 96)).astype(np.float32)
        ref = (ref + 0.5 * warp(ref, 1.3, -0.7)).astype(np.float32)
        moving = warp(ref, 0.38, -0.61)
        dx, dy, confidence, _ = phase_translation(ref, moving)
        self.assertAlmostEqual(dx, -0.38, delta=0.18)
        self.assertAlmostEqual(dy, 0.61, delta=0.18)
        self.assertGreater(confidence, 1.0)

    def test_reconstruction_modules_have_no_hidden_truth_imports(self):
        for module in (algorithms, quality, worker):
            source = inspect.getsource(module).lower()
            self.assertNotIn("from .generator", source)
            self.assertNotIn("from .evaluator", source)
            self.assertNotIn("true_transforms", source)
            self.assertNotIn("clean_reference", source)

    def test_experimental_wiener_is_finite_and_parameterized(self):
        image = np.zeros((32, 32), dtype=np.float32)
        image[8:24, 8:24] = 0.7
        result = wiener_deconvolution(image, 0.8, 0.025)
        self.assertEqual(result.shape, image.shape)
        self.assertTrue(np.all(np.isfinite(result)))
        with self.assertRaises(ValueError):
            wiener_deconvolution(image, 0, 0.02)

    def test_isolated_reconstruction_returns_traceable_result(self):
        cfg = {"width": 56, "height": 56, "supersample": 3, "frame_count": 8, "seed": 71,
               "shot_scale": 0.02, "read_noise_sigma": 0.003,
               "exposure_jitter": 0.015, "optical_psf_sigma_px": 0.6,
               "rotation_span_deg": 0.15, "translation_span_px": 0.6}
        scratch = Path(__file__).resolve().parent.parent / ".tmp"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="worker-test-", dir=scratch) as td:
            fixture_root = Path(td)
            freeze_fixture(fixture_root, {**cfg, "inject_outliers": False}, fixture_id="worker-test")
            obs, _ = load_observations(fixture_root, "worker-test")
            record, images, elapsed = run_reconstruction_isolated(obs)
            oracle = load_evaluation_oracle(fixture_root, "worker-test")
            scored = evaluate(obs, oracle, record, images)
        self.assertTrue(record["operations"])
        self.assertIn("sigma_clipped", images)
        self.assertEqual(scored["source_count"], 8)
        self.assertGreater(elapsed, 0)
        self.assertEqual(len(record["accepted_ids"] + record["rejected_ids"]), 8)
        decision_map = {item["frame_id"]: item["decision"] for item in record["assessments"]}
        self.assertTrue(all(decision_map[fid] == "accepted" for fid in record["accepted_ids"]))
        self.assertTrue(all(decision_map[fid] == "rejected" for fid in record["rejected_ids"]))


if __name__ == "__main__":
    unittest.main()
