"""Observation-only process entry point for remediation algorithms."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np

from .types import ObservationSequence
from .remediation_algorithms import reconstruct, ALIGNMENT_VERSION, RECONSTRUCTION_VERSION


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    src, dest = Path(args.input), Path(args.output)
    dest.mkdir(parents=True, exist_ok=True)
    with np.load(src, allow_pickle=False) as data:
        frames = data["frames"].astype(np.float32)
        frame_ids = tuple(str(x) for x in data["frame_ids"].tolist())
        metadata = tuple(json.loads(str(data["public_metadata_json"].item())))
        config = json.loads(str(data["public_config_json"].item()))
        fixture_id = str(data["fixture_id"].item())
    obs = ObservationSequence(fixture_id, frames, frame_ids, metadata, config)
    result = reconstruct(obs)
    images = result["baselines"]
    np.savez_compressed(dest / "images.npz", **images)
    source_hashes = {fid: hashlib.sha256(frames[i].tobytes()).hexdigest()
                     for i, fid in enumerate(frame_ids)}
    output_hashes = {key: hashlib.sha256(value.tobytes()).hexdigest()
                     for key, value in images.items()}
    accepted_set = set(result["accepted_ids"])
    baseline_sources = {
        "ordinary_single": frame_ids[0], "best_single": result["reference_id"],
        "stage_aligned_stack": result["accepted_ids"],
        "stage_exposure_normalized_stack": result["accepted_ids"],
        "candidate_bilinear_aligned_stack": result["accepted_ids"],
        "candidate_fourier_aligned_stack": result["accepted_ids"],
        "candidate_fourier_rigid_aligned_stack": result["accepted_ids"],
        "registered_mean": result["accepted_ids"], "weighted_mean": result["accepted_ids"],
        "median": result["accepted_ids"], "sigma_clipped": result["accepted_ids"],
        "sigma_clipped_denoised": result["accepted_ids"],
        "fourier_mean": result["accepted_ids"], "fourier_weighted_mean": result["accepted_ids"],
        "fourier_median": result["accepted_ids"], "fourier_sigma_clipped": result["accepted_ids"],
        "fourier_sigma_clipped_denoised": result["accepted_ids"],
        "fourier_rigid_mean": result["accepted_ids"], "fourier_rigid_weighted_mean": result["accepted_ids"],
        "fourier_rigid_median": result["accepted_ids"], "fourier_rigid_sigma_clipped": result["accepted_ids"],
        "fourier_rigid_sigma_clipped_denoised": result["accepted_ids"],
        "half_stack_a": result["accepted_ids"][:max(1, len(result["accepted_ids"]) // 2)],
        "half_stack_b": result["accepted_ids"][max(1, len(result["accepted_ids"]) // 2):] or result["accepted_ids"][:1],
    }
    operation_for = {
        "ordinary_single": RECONSTRUCTION_VERSION, "best_single": RECONSTRUCTION_VERSION,
        "stage_aligned_stack": ALIGNMENT_VERSION, "registered_mean": RECONSTRUCTION_VERSION,
        "stage_exposure_normalized_stack": RECONSTRUCTION_VERSION,
        "candidate_bilinear_aligned_stack": ALIGNMENT_VERSION,
        "candidate_fourier_aligned_stack": ALIGNMENT_VERSION,
        "candidate_fourier_rigid_aligned_stack": ALIGNMENT_VERSION,
        "weighted_mean": RECONSTRUCTION_VERSION, "median": RECONSTRUCTION_VERSION,
        "sigma_clipped": RECONSTRUCTION_VERSION, "sigma_clipped_denoised": RECONSTRUCTION_VERSION,
        "fourier_mean": RECONSTRUCTION_VERSION, "fourier_weighted_mean": RECONSTRUCTION_VERSION,
        "fourier_median": RECONSTRUCTION_VERSION, "fourier_sigma_clipped": RECONSTRUCTION_VERSION,
        "fourier_sigma_clipped_denoised": RECONSTRUCTION_VERSION,
        "fourier_rigid_mean": RECONSTRUCTION_VERSION,
        "fourier_rigid_weighted_mean": RECONSTRUCTION_VERSION,
        "fourier_rigid_median": RECONSTRUCTION_VERSION,
        "fourier_rigid_sigma_clipped": RECONSTRUCTION_VERSION,
        "fourier_rigid_sigma_clipped_denoised": RECONSTRUCTION_VERSION,
        "half_stack_a": ALIGNMENT_VERSION, "half_stack_b": ALIGNMENT_VERSION,
    }
    edges = []
    for artifact, parents in baseline_sources.items():
        if isinstance(parents, str):
            parents = [parents]
        edges.append({"operation": artifact, "operation_version": operation_for[artifact],
                      "parent_source_ids": parents,
                      "parent_hashes_sha256": {fid: source_hashes[fid] for fid in parents},
                      "child_artifact_id": artifact,
                      "child_hash_sha256": output_hashes[artifact]})
    record = {
        "fixture_id": fixture_id,
        "reference_id": result["reference_id"],
        "accepted_ids": result["accepted_ids"],
        "rejected_ids": result["rejected_ids"],
        "assessments": [asdict(x) for x in result["assessments"]],
        "alignments": [asdict(x) for x in result["alignments"]],
        "operations": result["operations"],
        "algorithm_version": RECONSTRUCTION_VERSION,
        "alignment_version": ALIGNMENT_VERSION,
        "quality_version": result["assessments"][0].score_version,
        "deconvolution": "disabled",
        "source_hashes_sha256": source_hashes,
        "output_hashes_sha256": output_hashes,
        "baseline_source_ids": baseline_sources,
        "lineage_edges": edges,
    }
    if len(accepted_set) != len(result["accepted_ids"]):
        raise ValueError("duplicate accepted source id")
    (dest / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
