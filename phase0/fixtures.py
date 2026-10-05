"""Read-only fixture loading. Oracle loader is evaluator-side only."""

import json
import hashlib
from pathlib import Path
import numpy as np
from .types import ObservationSequence
from .generator import EvaluationOracle
from .config import METRIC_VERSION, RECONSTRUCTION_VERSION


def load_fixture_protocol(root, fixture_id):
    root = Path(root) / fixture_id
    protocol = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    return root, protocol


def load_observations(root, fixture_id):
    root, protocol = load_fixture_protocol(root, fixture_id)
    with np.load(root / protocol["observation_file"], allow_pickle=False) as data:
        obs = ObservationSequence(
            fixture_id,
            data["frames"].astype(np.float32),
            tuple(str(x) for x in data["frame_ids"].tolist()),
            tuple(json.loads(str(data["public_metadata_json"].item()))),
            {"width": int(data["frames"].shape[2]), "height": int(data["frames"].shape[1])},
        )
    return obs, protocol


def load_evaluation_oracle(root, fixture_id):
    root, protocol = load_fixture_protocol(root, fixture_id)
    # Call only after the reconstruction worker has returned.
    with np.load(root / protocol["oracle_file_evaluator_only"], allow_pickle=False) as data:
        oracle = EvaluationOracle(
            clean_reference=data["clean_reference"].astype(np.float32),
            clean_source_frames=data["clean_source_frames"].astype(np.float32),
            high_resolution_scene=data["high_resolution_scene"].astype(np.float32),
            true_transforms=data["true_transforms"].astype(np.float32),
            bad_frame_kinds=tuple(str(x) for x in data["bad_frame_kinds"].tolist()),
            expected_bad_indices=tuple(int(x) for x in data["expected_bad_indices"].tolist()),
            generation_parameters=json.loads(str(data["generation_parameters_json"].item())),
            seed=int(data["seed"].item()),
            disk_center_xy=tuple(float(x) for x in data["disk_center_xy"].tolist()),
            disk_radius_px=float(data["disk_radius_px"].item()),
        )
    return oracle


def persist_golden_fixture(root, fixture_id, images, result, *, algorithm_versions, python_version):
    """Write immutable reconstruction reference outputs and declared comparison ranges."""
    root = Path(root) / fixture_id
    golden_dir = root / f"golden-{RECONSTRUCTION_VERSION}-{METRIC_VERSION}"
    golden_dir.mkdir(exist_ok=True)
    npz_path = golden_dir / "reference-outputs.npz"
    metrics_path = golden_dir / "reference-metrics.json"
    if npz_path.exists() or metrics_path.exists():
        if not (npz_path.exists() and metrics_path.exists()):
            raise RuntimeError(f"partial golden fixture exists for {fixture_id}; inspect manually")
        existing = json.loads(metrics_path.read_text(encoding="utf-8"))
        reference = {"outputs": f"golden-{RECONSTRUCTION_VERSION}-{METRIC_VERSION}/reference-outputs.npz",
                     "metrics": f"golden-{RECONSTRUCTION_VERSION}-{METRIC_VERSION}/reference-metrics.json",
                     "sha256_outputs": existing["sha256_reference_outputs"],
                     "algorithm_versions": existing["algorithm_versions"]}
        fixture_path = root / "fixture.json"
        protocol = json.loads(fixture_path.read_text(encoding="utf-8"))
        refs = protocol.get("golden_references", [])
        if reference not in refs:
            refs.append(reference)
        protocol["golden_references"] = refs
        protocol["golden_reference"] = reference
        protocol["metric_version"] = METRIC_VERSION
        fixture_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
        return existing
    np.savez_compressed(npz_path, **images)
    expected = {}
    for name, item in result["image_metrics"].items():
        expected[name] = {
            "rmse_range": [max(0.0, item["reconstruction_error"]["rmse"] - max(0.0002, 0.01 * item["reconstruction_error"]["rmse"])),
                           item["reconstruction_error"]["rmse"] + max(0.0002, 0.01 * item["reconstruction_error"]["rmse"])],
            "snr_proxy_range": [max(0.0, item["snr_proxy"] * 0.98), item["snr_proxy"] * 1.02],
            "mtf50_proxy_range_cycles_per_pixel": [max(0.0, item["mtf50_proxy_cycles_per_pixel"] - 0.015),
                                                      item["mtf50_proxy_cycles_per_pixel"] + 0.015],
            "clipping_fraction_tolerance": 0.001,
        }
    record = {
        "fixture_id": fixture_id,
        "algorithm_versions": algorithm_versions,
        "metric_version": METRIC_VERSION,
        "python_version": python_version,
        "accepted_ids": result["reconstruction_record"]["accepted_ids"],
        "rejected_ids": result["reconstruction_record"]["rejected_ids"],
        "alignment_reference_id": result["reconstruction_record"]["reference_id"],
        "expected_metric_ranges": expected,
        "numerical_output_tolerances": {
            "normalized_pixel_absolute_error_max": 0.001,
            "registration_translation_abs_px": 0.10,
            "metric_ranges_are_regression_checks_not_scientific_gate_replacements": True,
        },
        "output_names": list(images),
        "sha256_reference_outputs": hashlib.sha256(npz_path.read_bytes()).hexdigest(),
    }
    metrics_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    fixture_path = root / "fixture.json"
    protocol = json.loads(fixture_path.read_text(encoding="utf-8"))
    protocol["metric_version"] = METRIC_VERSION
    reference = {
        "outputs": f"golden-{RECONSTRUCTION_VERSION}-{METRIC_VERSION}/reference-outputs.npz",
        "metrics": f"golden-{RECONSTRUCTION_VERSION}-{METRIC_VERSION}/reference-metrics.json",
        "sha256_outputs": record["sha256_reference_outputs"],
        "algorithm_versions": algorithm_versions,
    }
    refs = protocol.get("golden_references", [])
    if reference not in refs:
        refs.append(reference)
    protocol["golden_references"] = refs
    fixture_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return record
