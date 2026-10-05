"""Run one preregistered split without modifying the historical Phase 0 runs."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import numpy as np

from .remediation_protocol import (GATES, QUALITY_VERSION, ALIGNMENT_VERSION,
                                   RECONSTRUCTION_VERSION, METRIC_VERSION)
from .remediation_generator import load_remediation_observations, load_remediation_oracle
from .remediation_runner import run_remediation_isolated
from .remediation_evaluator import evaluate_remediation
from .remediation_quality import FROZEN_THRESHOLDS


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _integrity_audit(obs, record, images):
    ids = set(record["accepted_ids"]) | set(record["rejected_ids"])
    decisions = {x["frame_id"]: x["decision"] for x in record["assessments"]}
    outputs_ok = (set(record["output_hashes_sha256"]) == set(images) and
                  all(hashlib.sha256(images[k].tobytes()).hexdigest() == v
                      for k, v in record["output_hashes_sha256"].items()))
    lineage_ok = (len(record["lineage_edges"]) == len(images) and
                  {x["child_artifact_id"] for x in record["lineage_edges"]} == set(images) and
                  all(x["child_hash_sha256"] == record["output_hashes_sha256"][x["child_artifact_id"]]
                      and bool(x["parent_source_ids"])
                      and all(fid in record["source_hashes_sha256"] for fid in x["parent_source_ids"])
                      for x in record["lineage_edges"]))
    return {
        "pass": (ids == set(obs.frame_ids) and len(decisions) == len(obs.frame_ids) and
                 all(decisions.get(fid) == "accepted" for fid in record["accepted_ids"]) and
                 all(decisions.get(fid) == "rejected" for fid in record["rejected_ids"]) and
                 len(record["source_hashes_sha256"]) == len(obs.frame_ids) and
                 all(len(v) == 64 for v in record["source_hashes_sha256"].values()) and
                 outputs_ok and lineage_ok and record["deconvolution"] == "disabled"),
        "source_count": len(obs.frame_ids), "decision_count": len(decisions),
        "source_hash_count": len(record["source_hashes_sha256"]),
        "output_hashes_match": outputs_ok, "lineage_edges_complete": lineage_ok,
        "deconvolution": record["deconvolution"],
    }


def _selected_thresholds(results_root, split):
    profile_path = results_root / "selected-profile.json"
    if split == "development" and not profile_path.exists():
        return dict(FROZEN_THRESHOLDS)
    if not profile_path.exists():
        raise FileNotFoundError("freeze selected-profile.json after development, before validation")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    return profile["thresholds"]


def _run_one(root, spec, output_dir, thresholds):
    obs, protocol = load_remediation_observations(root / "fixtures", spec["fixture_id"])
    obs_path = root / "fixtures" / spec["fixture_id"] / protocol["observation_file"]
    if _sha(obs_path) != protocol["sha256_observations"]:
        raise ValueError(f"observation hash mismatch: {spec['fixture_id']}")
    record, images, runtime = run_remediation_isolated(obs, thresholds=thresholds)
    output_dir.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(output_dir / "images.npz", **images)
    (output_dir / "reconstruction.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    integrity = _integrity_audit(obs, record, images)
    record_sha = _sha(output_dir / "reconstruction.json")
    image_file_sha = _sha(output_dir / "images.npz")
    entry = {"fixture_id": spec["fixture_id"], "split": spec["split"],
             "purpose": spec["purpose"], "runtime_seconds": runtime,
             "reconstruction_json_sha256": record_sha, "images_npz_sha256": image_file_sha,
             "integrity": integrity}
    return obs, protocol, record, images, entry


def run_split(split: str, *, root: str | Path | None = None, run_id="remediation-001"):
    root = Path(root or Path(__file__).resolve().parent)
    result_root = root / "results" / run_id
    prereg_path = result_root / "preregistration.json"
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    specs = [x for x in prereg["fixtures"] if x["split"] == split]
    if not specs:
        raise ValueError(f"unknown or empty split: {split}")
    thresholds = _selected_thresholds(result_root, split)
    if split == "holdout":
        release_path = result_root / "release-card.json"
        if not release_path.exists():
            raise FileNotFoundError("holdout is sealed until release-card.json is frozen")
        release = json.loads(release_path.read_text(encoding="utf-8"))
        if release["thresholds"] != thresholds:
            raise ValueError("holdout thresholds do not match frozen release card")

    split_root = result_root / split
    split_root.mkdir(parents=True, exist_ok=False)
    staged = []
    for spec in specs:
        out = split_root / spec["fixture_id"]
        staged.append(_run_one(root, spec, out, thresholds))

    # Freeze every final holdout reconstruction and output hash before loading
    # any holdout oracle or producing a truth-referenced metric.
    if split == "holdout":
        worker_freeze = {
            "split": split,
            "threshold_profile_id": release["threshold_profile_id"],
            "fixture_outputs": [entry for _, _, _, _, entry in staged],
            "versions": release["versions"],
        }
        (split_root / "worker-output-freeze.json").write_text(json.dumps(worker_freeze, indent=2), encoding="utf-8")

    evaluated = []
    for obs, protocol, record, images, entry in staged:
        oracle_path = root / "fixtures" / entry["fixture_id"] / protocol["oracle_file_evaluator_only"]
        if _sha(oracle_path) != protocol["sha256_oracle"]:
            raise ValueError(f"oracle hash mismatch: {entry['fixture_id']}")
        oracle = load_remediation_oracle(root / "fixtures", entry["fixture_id"])
        metrics = evaluate_remediation(obs, oracle, record, images)
        metrics["runtime_seconds"] = entry["runtime_seconds"]
        metrics["integrity_audit"] = entry["integrity"]
        metrics["fixture_protocol"] = protocol
        metrics["reconstruction_json_sha256"] = entry["reconstruction_json_sha256"]
        metrics["images_npz_sha256"] = entry["images_npz_sha256"]
        path = split_root / entry["fixture_id"] / "metrics.json"
        path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        evaluated.append(metrics)
    summary = {"split": split, "metric_version": METRIC_VERSION,
               "quality_version": QUALITY_VERSION, "alignment_version": ALIGNMENT_VERSION,
               "reconstruction_version": RECONSTRUCTION_VERSION,
               "threshold_profile_id": ("initial-preregistered" if split == "development" and
                                         not (result_root / "selected-profile.json").exists()
                                         else json.loads((result_root / "selected-profile.json").read_text(encoding="utf-8"))["threshold_profile_id"]),
               "thresholds": thresholds,
               "fixtures": [{"fixture_id": x["fixture_id"], "accepted": x["accepted_count"],
                             "rejected": x["rejected_count"], "runtime_seconds": x["runtime_seconds"],
                             "registration_rms_px": x["registration"]["rms_translation_px"],
                             "registration_coverage": x["registration"]["valid_coverage_fraction"],
                             "snr_gain": x["snr_proxy_gain_sigma_vs_best"],
                             "mtf_retention": x["mtf50_retention_denoised_vs_best"],
                             "integrity_pass": x["integrity_audit"]["pass"],
                             "failure_classes": x["frame_rejection_by_class"]}
                            for x in evaluated],
               "system": {"python": sys.version, "platform": platform.platform()}}
    summary_path = split_root / "split-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def freeze_selected_profile(root: str | Path, thresholds: dict, *, profile_id="rejection-profile-0.1",
                            run_id="remediation-001"):
    root = Path(root)
    result_root = root / "results" / run_id
    path = result_root / "selected-profile.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite selected profile: {path}")
    dev_path = result_root / "development" / "split-summary.json"
    if not dev_path.exists():
        raise FileNotFoundError("development split must finish before selecting a profile")
    profile = {"threshold_profile_id": profile_id, "thresholds": thresholds,
               "selected_from_split": "development", "development_summary_sha256": _sha(dev_path),
               "metric_version": METRIC_VERSION, "quality_version": QUALITY_VERSION,
               "alignment_version": ALIGNMENT_VERSION, "reconstruction_version": RECONSTRUCTION_VERSION}
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def freeze_release_card(root: str | Path, *, run_id="remediation-001"):
    root = Path(root)
    result_root = root / "results" / run_id
    path = result_root / "release-card.json"
    if path.exists():
        raise FileExistsError(f"refusing to overwrite release card: {path}")
    profile_path = result_root / "selected-profile.json"
    val_path = result_root / "validation" / "split-summary.json"
    if not profile_path.exists() or not val_path.exists():
        raise FileNotFoundError("freeze release only after selected profile and validation results exist")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    validation = json.loads(val_path.read_text(encoding="utf-8"))
    val_ok = all(x["integrity_pass"] and
                 (x["registration_rms_px"] is None or x["registration_rms_px"] <= GATES["registration_rms_px_max"]) and
                 x["registration_coverage"] >= GATES["registration_coverage_min"]
                 for x in validation["fixtures"])
    outlier = next(x for x in validation["fixtures"] if "outlier" in x["fixture_id"])
    recall_ok = all(outlier["failure_classes"][x]["recall"] >= GATES["failure_class_recall_min"]
                    for x in ("strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed"))
    clean = next(x for x in validation["fixtures"] if "clean16" in x["fixture_id"])
    edge_ok = clean["mtf_retention"] >= GATES["mtf50_retention_min"]
    val_ok = val_ok and recall_ok and edge_ok and clean["snr_gain"] >= GATES["snr_proxy_gain_16_min"]
    if not val_ok:
        raise ValueError("validation did not pass the preregistered release gates; holdout stays sealed")
    release = {
        "status": "frozen-for-final-holdout",
        "threshold_profile_id": profile["threshold_profile_id"],
        "thresholds": profile["thresholds"],
        "versions": {"metric": METRIC_VERSION, "quality": QUALITY_VERSION,
                     "alignment": ALIGNMENT_VERSION, "reconstruction": RECONSTRUCTION_VERSION},
        "gate_thresholds": GATES,
        "gate_scope": {"registration": "all validation and holdout fixtures",
                       "snr_and_mtf50": "primary clean 16-frame fixture; other fixture measurements remain diagnostic",
                       "failure_class_recall": "class-balanced outlier fixture; confusion statistics reported one-vs-rest"},
        "validation_summary_sha256": _sha(val_path),
        "selected_profile_sha256": _sha(profile_path),
        "preregistration_sha256": _sha(result_root / "preregistration.json"),
        "gate_scope_addendum_sha256": (_sha(result_root / "gate-scope-addendum.json")
                                       if (result_root / "gate-scope-addendum.json").exists() else None),
        "holdout_frozen_before_evaluation": True,
        "deconvolution": "disabled",
    }
    path.write_text(json.dumps(release, indent=2), encoding="utf-8")
    return release


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("development", "validation", "holdout"), required=True)
    parser.add_argument("--run-id", default="remediation-001")
    args = parser.parse_args(argv)
    print(json.dumps(run_split(args.split, run_id=args.run_id), indent=2))


if __name__ == "__main__":
    main()
