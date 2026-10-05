"""Isolated reconstruction worker. It accepts observations only."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import numpy as np

from .types import ObservationSequence
from .algorithms import reconstruct
from .config import ALIGNMENT_VERSION, RECONSTRUCTION_VERSION


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--deconvolution", action="store_true")
    args = parser.parse_args(argv)
    src, dest = Path(args.input), Path(args.output)
    dest.mkdir(parents=True, exist_ok=True)
    with np.load(src, allow_pickle=False) as data:
        frames = data["frames"].astype(np.float32)
        frame_ids = tuple(str(x) for x in data["frame_ids"].tolist())
        metadata = tuple(json.loads(str(data["public_metadata_json"].item())))
        fixture_id = str(data["fixture_id"].item())
        public_config = json.loads(str(data["public_config_json"].item()))
    obs = ObservationSequence(fixture_id, frames, frame_ids, metadata, public_config)
    result = reconstruct(obs, run_deconvolution=args.deconvolution)
    np.savez_compressed(dest / "images.npz", **result.baselines)
    record = {
        "fixture_id": result.fixture_id,
        "reference_id": result.reference_id,
        "accepted_ids": result.accepted_ids,
        "rejected_ids": result.rejected_ids,
        "assessments": [asdict(v) for v in result.assessments],
        "alignments": [asdict(v) for v in result.alignments],
        "operations": result.operations,
        "algorithm_version": RECONSTRUCTION_VERSION,
        "warnings": result.warnings,
        "baseline_source_ids": {"ordinary_single": frame_ids[0], "best_single": result.reference_id,
                                "registered_mean": result.reference_id, "weighted_mean": result.reference_id,
                                "median": result.reference_id, "sigma_clipped": result.reference_id,
                                "sigma_clipped_denoised": result.reference_id,
                                "half_stack_a": result.reference_id, "half_stack_b": result.reference_id},
        "source_hashes_sha256": {fid: hashlib.sha256(frames[i].tobytes()).hexdigest()
                                 for i, fid in enumerate(frame_ids)},
        "output_hashes_sha256": {key: hashlib.sha256(value.tobytes()).hexdigest()
                                 for key, value in result.baselines.items()},
        "lineage_edges": [],
    }
    if "experimental_wiener" in result.baselines:
        record["baseline_source_ids"]["experimental_wiener"] = result.reference_id
    sources = record["source_hashes_sha256"]
    outputs = record["output_hashes_sha256"]
    for artifact_name, parents in record["baseline_source_ids"].items():
        parent_ids = result.accepted_ids if artifact_name not in ("ordinary_single", "best_single", "half_stack_a", "half_stack_b") else (
            [obs.frame_ids[0]] if artifact_name == "ordinary_single" else
            ([result.reference_id] if artifact_name == "best_single" else
             (result.accepted_ids[:max(1, len(result.accepted_ids)//2)] if artifact_name == "half_stack_a" else
              result.accepted_ids[max(1, len(result.accepted_ids)//2):])))
        record["lineage_edges"].append({"operation": artifact_name, "operation_version":
                                        ALIGNMENT_VERSION if artifact_name.startswith("half_stack") or artifact_name in ("registered_mean", "weighted_mean", "median", "sigma_clipped", "sigma_clipped_denoised") else RECONSTRUCTION_VERSION,
                                        "parent_source_ids": parent_ids,
                                        "parent_hashes_sha256": {fid: sources[fid] for fid in parent_ids},
                                        "child_artifact_id": artifact_name,
                                        "child_hash_sha256": outputs[artifact_name]})
    (dest / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
