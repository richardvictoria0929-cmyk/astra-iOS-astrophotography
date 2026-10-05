"""Preregister and freeze the separate Phase 0 remediation split."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .config import DEFAULT_CONFIG
from .remediation_generator import freeze_remediation_fixture
from .remediation_quality import FROZEN_THRESHOLDS


PROTOCOL_VERSION = "phase0-remediation-protocol-0.1"
METRIC_VERSION = "metrics-0.3"
QUALITY_VERSION = "quality-0.5"
ALIGNMENT_VERSION = "align-0.7"
RECONSTRUCTION_VERSION = "reconstruct-0.9"
EVALUATOR_VERSION = "remediation-evaluator-0.1"
GATES = {
    "registration_rms_px_max": 0.25,
    "registration_coverage_min": 0.90,
    "snr_proxy_gain_16_min": 2.5,
    "mtf50_retention_min": 0.95,
    "failure_class_recall_min": 0.90,
    "integrity_required": True,
    "deconvolution": "disabled",
}


def _class_plan(start, per_class):
    plan = {}
    names = ("strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed")
    index = start
    for name in names:
        for _ in range(per_class):
            plan[index] = (name,)
            index += 1
    return plan


def _fixture_specs():
    base = dict(DEFAULT_CONFIG)
    specs = []
    for split, seed_base, outlier_n, per_class, good_n in (
            ("development", 41400, 80, 8, 40),
            ("validation", 52400, 80, 8, 40),
            ("holdout", 63400, 150, 10, 100)):
        cfg_clean = {**base, "seed": seed_base + 1, "frame_count": 16}
        specs.append({"split": split, "purpose": "clean-primary-16-frame-stack",
                      "fixture_id": f"remed-001-{split}-clean16", "config": cfg_clean,
                      "label_plan": {}})
        cfg_outlier = {**base, "seed": seed_base + 2, "frame_count": outlier_n,
                       "shot_scale": 0.015, "read_noise_sigma": 0.005}
        specs.append({"split": split, "purpose": "class-balanced-observable-quality-stress",
                      "fixture_id": f"remed-001-{split}-outlier-{outlier_n}", "config": cfg_outlier,
                      "label_plan": _class_plan(good_n, per_class)})
        cfg_stress = {**base, "seed": seed_base + 3, "frame_count": 32,
                      "translation_span_px": 2.0, "rotation_span_deg": 0.65}
        specs.append({"split": split, "purpose": "clean-wider-shift-rotation-stress",
                      "fixture_id": f"remed-001-{split}-motion-stress32", "config": cfg_stress,
                      "label_plan": {}})
    return specs


def preregister_and_freeze(root: str | Path):
    root = Path(root)
    fixtures_root = root / "fixtures"
    results_root = root / "results" / "remediation-001"
    results_root.mkdir(parents=True, exist_ok=True)
    prereg_path = results_root / "preregistration.json"
    if prereg_path.exists():
        raise FileExistsError(f"refusing to overwrite remediation preregistration: {prereg_path}")
    specs = _fixture_specs()
    prereg = {
        "protocol_version": PROTOCOL_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "bounded Phase 0 remediation only: frame rejection and edge retention",
        "metric_version": METRIC_VERSION,
        "quality_version": QUALITY_VERSION,
        "alignment_version": ALIGNMENT_VERSION,
        "reconstruction_version": RECONSTRUCTION_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "initial_threshold_profile": FROZEN_THRESHOLDS,
        "gate_thresholds": GATES,
        "selection_rule": "Any threshold profile change must be selected from development results only, assigned a new profile identifier, then evaluated once on validation. Freeze the profile and all code/versions before opening any holdout oracle. No holdout-guided changes.",
        "evaluation_order": ["development", "validation", "freeze-release-card", "holdout-final-evaluation"],
        "holdout_oracle_access_rule": "Holdout observations may be processed only after the release card is written. Holdout private oracle may be opened only after all worker outputs exist and their hashes are frozen.",
        "failure_classes": ["strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed"],
        "classification_rule": "One-vs-rest per failure tag; mixed frames carry blur, clipping, large_motion, and mixed tags. Good-frame false rejection is also reported separately.",
        "fixtures": [{"split": x["split"], "purpose": x["purpose"], "fixture_id": x["fixture_id"],
                      "seed": x["config"]["seed"], "parameters": x["config"],
                      "frame_count": x["config"]["frame_count"],
                      "planned_class_counts": {name: sum(name in tags for tags in x["label_plan"].values())
                                                for name in ("strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed")}}
                     for x in specs],
    }
    prereg_path.write_text(json.dumps(prereg, indent=2), encoding="utf-8")
    frozen = []
    for spec in specs:
        protocol = freeze_remediation_fixture(fixtures_root, spec["config"],
                                              fixture_id=spec["fixture_id"],
                                              label_plan=spec["label_plan"])
        frozen.append({"split": spec["split"], "fixture_id": spec["fixture_id"],
                       "sha256_observations": protocol["sha256_observations"],
                       "sha256_oracle": protocol["sha256_oracle"],
                       "sha256_failure_labels_commitment": protocol["sha256_failure_labels_commitment"],
                       "class_counts_committed": protocol["class_counts_committed"]})
    prereg["frozen_fixture_hashes"] = frozen
    canonical = json.dumps(prereg, sort_keys=True, separators=(",", ":")).encode("utf-8")
    prereg["sha256_preregistration_content_without_final_hash"] = hashlib.sha256(canonical).hexdigest()
    prereg_path.write_text(json.dumps(prereg, indent=2), encoding="utf-8")
    return prereg


if __name__ == "__main__":
    print(json.dumps(preregister_and_freeze(Path(__file__).resolve().parent), indent=2))
