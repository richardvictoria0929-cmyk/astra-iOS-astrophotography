"""New, versioned Phase 0 remediation fixture generator.

This module is fixture/evaluator-side only. Failure tags and transforms are never
written to observed metadata or passed to the reconstruction worker.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np

from . import generator as base
from .types import ObservationSequence


GENERATOR_VERSION = "lunar-remediation-0.1"


@dataclass(frozen=True)
class RemediationOracle:
    clean_reference: np.ndarray
    clean_source_frames: np.ndarray
    high_resolution_scene: np.ndarray
    true_transforms: np.ndarray
    failure_tags: tuple[tuple[str, ...], ...]
    seed: int
    disk_center_xy: tuple[float, float]
    disk_radius_px: float
    parameters: dict


def generate_remediation_sequence(config: dict, fixture_id: str,
                                  label_plan: dict[int, tuple[str, ...]]):
    cfg = dict(config)
    cfg["frame_count"] = int(cfg.get("frame_count", 16))
    observations, initial = base.generate_sequence(cfg, fixture_id=fixture_id,
                                                    inject_outliers=False)
    frames = observations.frames.copy()
    clean_sources = initial.clean_source_frames.copy()
    transforms = initial.true_transforms.copy()
    tag_rows = [set() for _ in observations.frame_ids]
    w, h = frames.shape[2], frames.shape[1]
    scale = int(cfg["supersample"])
    exposure = float(np.exp(0.0))

    for index, raw_tags in label_plan.items():
        tags = tuple(raw_tags)
        if index < 0 or index >= len(frames):
            raise ValueError(f"failure index {index} is outside {fixture_id}")
        if "mixed" in tags:
            tags = tuple(sorted(set(tags) | {"strong_blur", "clipping", "large_motion"}))
        allowed = {"strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed"}
        if not set(tags) <= allowed:
            raise ValueError(f"unknown remediation failure tags: {tags}")
        tag_rows[index].update(tags)

        frame = frames[index].copy()
        if "large_motion" in tags:
            # Deterministic, deliberately beyond the good-frame shift envelope.
            sign = -1.0 if index % 2 else 1.0
            dx, dy, rotation = (float(x) for x in transforms[index])
            dx += sign * 5.2
            dy -= sign * 4.6
            transforms[index] = (dx, dy, rotation)
            exposure = float(observations.public_metadata[index]["nominal_exposure_relative"])
            clean_sources[index] = base._render(initial.high_resolution_scene, w, h, scale,
                                                dx, dy, rotation,
                                                float(cfg["optical_psf_sigma_px"])) * exposure
            frame = base._render(initial.high_resolution_scene, w, h, scale, dx, dy,
                                 rotation, float(cfg["optical_psf_sigma_px"])) * exposure
            rng = np.random.default_rng(int(cfg["seed"]) + 900_000 + index)
            shot_scale = float(cfg["shot_scale"])
            if shot_scale > 0:
                frame = rng.poisson(np.maximum(frame, 0) / shot_scale).astype(np.float32) * shot_scale
            frame += rng.normal(0, float(cfg["read_noise_sigma"]), frame.shape).astype(np.float32)

        if "strong_blur" in tags:
            frame = base._gaussian_blur(frame, 2.0)
        if "clipping" in tags:
            frame = np.clip(frame * 2.15, 0.0, 1.0)
        if "abnormal_noise" in tags:
            rng = np.random.default_rng(int(cfg["seed"]) + 1_100_000 + index)
            frame += rng.normal(0, float(cfg["read_noise_sigma"]) * 7.0,
                                frame.shape).astype(np.float32)
        frames[index] = np.clip(frame, 0.0, 1.0)

    obs = ObservationSequence(fixture_id, frames.astype(np.float32), observations.frame_ids,
                              observations.public_metadata,
                              {"width": w, "height": h, "generator_version": GENERATOR_VERSION})
    oracle = RemediationOracle(initial.clean_reference, clean_sources.astype(np.float32),
                               initial.high_resolution_scene, transforms,
                               tuple(tuple(sorted(tags)) for tags in tag_rows),
                               int(cfg["seed"]), initial.disk_center_xy,
                               initial.disk_radius_px, cfg)
    return obs, oracle


def freeze_remediation_fixture(root: str | Path, config: dict, *, fixture_id: str,
                               label_plan: dict[int, tuple[str, ...]]) -> dict:
    """Write a new immutable fixture; existing paths are never overwritten."""
    root = Path(root) / fixture_id
    if root.exists():
        raise FileExistsError(f"refusing to overwrite frozen remediation fixture: {root}")
    obs, oracle = generate_remediation_sequence(config, fixture_id, label_plan)
    obs_dir, private_dir = root / "observed", root / "evaluator-private"
    obs_dir.mkdir(parents=True)
    private_dir.mkdir()
    obs_path = obs_dir / "frames.npz"
    oracle_path = private_dir / "oracle.npz"
    labels_json = json.dumps([list(row) for row in oracle.failure_tags], separators=(",", ":"))
    np.savez_compressed(obs_path, frames=obs.frames,
                        frame_ids=np.asarray(obs.frame_ids),
                        public_metadata_json=np.asarray(json.dumps(obs.public_metadata)),
                        public_config_json=np.asarray(json.dumps(obs.algorithm_config)))
    np.savez_compressed(oracle_path,
                        clean_reference=oracle.clean_reference,
                        clean_source_frames=oracle.clean_source_frames,
                        high_resolution_scene=oracle.high_resolution_scene,
                        true_transforms=oracle.true_transforms,
                        failure_tags_json=np.asarray(labels_json),
                        generation_parameters_json=np.asarray(json.dumps(oracle.parameters)),
                        seed=np.asarray(oracle.seed),
                        disk_center_xy=np.asarray(oracle.disk_center_xy),
                        disk_radius_px=np.asarray(oracle.disk_radius_px))
    commitment = hashlib.sha256(labels_json.encode("utf-8")).hexdigest()
    protocol = {
        "fixture_id": fixture_id,
        "generator_version": GENERATOR_VERSION,
        "seed": oracle.seed,
        "parameters": oracle.parameters,
        "frame_count": len(obs.frame_ids),
        "observation_file": "observed/frames.npz",
        "oracle_file_evaluator_only": "evaluator-private/oracle.npz",
        "sha256_observations": hashlib.sha256(obs_path.read_bytes()).hexdigest(),
        "sha256_oracle": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
        "sha256_failure_labels_commitment": commitment,
        "class_counts_committed": {
            tag: sum(tag in row for row in oracle.failure_tags)
            for tag in ("strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed")
        },
    }
    (root / "fixture.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return protocol


def load_remediation_observations(root: str | Path, fixture_id: str):
    root = Path(root) / fixture_id
    protocol = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    with np.load(root / protocol["observation_file"], allow_pickle=False) as data:
        obs = ObservationSequence(
            fixture_id, data["frames"].astype(np.float32),
            tuple(str(x) for x in data["frame_ids"].tolist()),
            tuple(json.loads(str(data["public_metadata_json"].item()))),
            json.loads(str(data["public_config_json"].item())))
    return obs, protocol


def load_remediation_oracle(root: str | Path, fixture_id: str):
    """Evaluator-only loader; call only after the isolated worker has returned."""
    root = Path(root) / fixture_id
    protocol = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
    with np.load(root / protocol["oracle_file_evaluator_only"], allow_pickle=False) as data:
        labels_json = str(data["failure_tags_json"].item())
        if hashlib.sha256(labels_json.encode("utf-8")).hexdigest() != protocol["sha256_failure_labels_commitment"]:
            raise ValueError("failure-label commitment mismatch")
        return RemediationOracle(
            data["clean_reference"].astype(np.float32),
            data["clean_source_frames"].astype(np.float32),
            data["high_resolution_scene"].astype(np.float32),
            data["true_transforms"].astype(np.float32),
            tuple(tuple(str(y) for y in x) for x in json.loads(labels_json)),
            int(data["seed"].item()),
            tuple(float(x) for x in data["disk_center_xy"].tolist()),
            float(data["disk_radius_px"].item()),
            json.loads(str(data["generation_parameters_json"].item())))
