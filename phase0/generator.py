"""Fixture generation only. Never imported by reconstruction worker code."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import numpy as np

from .types import ObservationSequence
from .config import GENERATOR_VERSION, METRIC_VERSION, DEFAULT_CONFIG


@dataclass(frozen=True)
class EvaluationOracle:
    clean_reference: np.ndarray
    clean_source_frames: np.ndarray
    high_resolution_scene: np.ndarray
    true_transforms: np.ndarray  # N x (dx,dy,rotation degrees)
    bad_frame_kinds: tuple[str, ...]
    expected_bad_indices: tuple[int, ...]
    generation_parameters: dict
    seed: int
    disk_center_xy: tuple[float, float]
    disk_radius_px: float


def _gaussian_blur(image: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return image.astype(np.float32, copy=True)
    h, w = image.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    transfer = np.exp(-2.0 * np.pi**2 * sigma**2 * (fx * fx + fy * fy))
    result = np.fft.irfft2(np.fft.rfft2(image) * transfer, s=image.shape)
    return result.astype(np.float32)


def _sample_bilinear(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    h, w = image.shape
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    dx, dy = x - x0, y - y0
    x0c, x1c = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
    y0c, y1c = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    a = image[y0c, x0c] * (1 - dx) + image[y0c, x1c] * dx
    b = image[y1c, x0c] * (1 - dx) + image[y1c, x1c] * dx
    return (a * (1 - dy) + b * dy).astype(np.float32)


def _scene(width: int, height: int, scale: int, rng: np.random.Generator) -> np.ndarray:
    h, w = height * scale, width * scale
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    radius = min(w, h) * 0.425
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inside = r <= radius

    # Smooth broad maria-like fields plus band-limited stochastic terrain.
    coarse = rng.normal(0, 1, (max(8, h // 28), max(8, w // 28))).astype(np.float32)
    coarse = _gaussian_blur(coarse, 1.7)
    gy = np.linspace(0, coarse.shape[0] - 1, h)
    gx = np.linspace(0, coarse.shape[1] - 1, w)
    cyi, cxi = np.meshgrid(gy, gx, indexing="ij")
    field = _sample_bilinear(coarse, cxi, cyi)
    field = field / max(float(np.std(field)), 1e-6)
    broad = 0.53 + 0.055 * field + 0.025 * np.sin(xx / (scale * 5.3)) * np.cos(yy / (scale * 7.1))

    # Crater basins and rims: shape parameters and positions are ground truth.
    crater_field = np.zeros((h, w), dtype=np.float32)
    for _ in range(62):
        angle = rng.uniform(0, 2 * np.pi)
        radial = radius * np.sqrt(rng.uniform(0.02, 0.94))
        qx, qy = cx + radial * np.cos(angle), cy + radial * np.sin(angle)
        cr = rng.uniform(scale * 1.6, scale * 8.0)
        d = np.sqrt((xx - qx) ** 2 + (yy - qy) ** 2) / cr
        basin = -rng.uniform(0.035, 0.11) * np.exp(-0.5 * (d / 0.72) ** 2)
        rim = rng.uniform(0.018, 0.065) * np.exp(-0.5 * ((d - 0.92) / 0.12) ** 2)
        ejecta = 0.012 * np.exp(-0.5 * ((d - 1.22) / 0.32) ** 2)
        crater_field += basin + rim + ejecta

    fine = _gaussian_blur(rng.normal(0, 1, (h, w)).astype(np.float32), max(0.55, scale * 0.7))
    fine = fine / max(float(np.std(fine)), 1e-6)
    terrain = broad + crater_field + 0.010 * fine
    limb = np.clip((radius - r) / (scale * 1.4) + 0.5, 0, 1)
    # A crescent-like terminator gives a high-contrast edge and broad gradient.
    phase = np.clip((cx + radius * 0.42 - xx) / (radius * 0.32), 0, 1)
    illumination = 0.22 + 0.78 * phase
    moon = terrain * illumination * limb
    # Dark sky with a very faint deterministic background gradient.
    sky = 0.008 + 0.002 * (xx / max(w - 1, 1))
    return np.where(inside, moon, sky).astype(np.float32)


def _render(scene: np.ndarray, width: int, height: int, scale: int,
            dx: float, dy: float, rotation_deg: float, psf_sigma_px: float) -> np.ndarray:
    blurred = _gaussian_blur(scene, psf_sigma_px * scale)
    h, w = height * scale, width * scale
    center_x, center_y = (w - 1) / 2, (h - 1) / 2
    angle = np.deg2rad(rotation_deg)
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    # Integrate a supersampled detector pixel using a regular subpixel grid.
    accum = np.zeros((height, width), dtype=np.float32)
    sub = max(2, scale)
    ox = (np.arange(sub, dtype=np.float32) + 0.5) / sub - 0.5
    oy = (np.arange(sub, dtype=np.float32) + 0.5) / sub - 0.5
    py, px = np.mgrid[0:height, 0:width].astype(np.float32)
    for sy in oy:
        for sx in ox:
            out_x = (px + sx - (width - 1) / 2 - dx) * scale + center_x
            out_y = (py + sy - (height - 1) / 2 - dy) * scale + center_y
            in_x = cos_a * (out_x - center_x) + sin_a * (out_y - center_y) + center_x
            in_y = -sin_a * (out_x - center_x) + cos_a * (out_y - center_y) + center_y
            accum += _sample_bilinear(blurred, in_x, in_y)
    return accum / float(sub * sub)


def generate_sequence(config: dict | None = None, *, fixture_id: str = "sim-0001",
                      inject_outliers: bool = True) -> tuple[ObservationSequence, EvaluationOracle]:
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)
    rng = np.random.default_rng(int(cfg["seed"]))
    w, h, scale, count = (int(cfg[k]) for k in ("width", "height", "supersample", "frame_count"))
    scene = _scene(w, h, scale, rng)
    clean = _render(scene, w, h, scale, 0, 0, 0, float(cfg["optical_psf_sigma_px"]))
    frames, transforms, kinds, metadata, clean_sources = [], [], [], [], []
    for i in range(count):
        dx = float(rng.uniform(-cfg["translation_span_px"], cfg["translation_span_px"]))
        dy = float(rng.uniform(-cfg["translation_span_px"], cfg["translation_span_px"]))
        rotation = float(rng.uniform(-cfg["rotation_span_deg"], cfg["rotation_span_deg"]))
        kind = "good"
        if inject_outliers and i == count - 3:
            kind = "strong_blur"
        elif inject_outliers and i == count - 2:
            kind = "highlight_clipped"
        elif inject_outliers and i == count - 1:
            kind = "abnormal_noise"

        blur = float(cfg["optical_psf_sigma_px"])
        if kind == "strong_blur":
            blur += 2.3
        if kind == "highlight_clipped":
            dx *= 4.0
            dy *= 4.0
        exposure = float(np.exp(rng.normal(0, cfg["exposure_jitter"])))
        clean_src = _render(scene, w, h, scale, dx, dy, rotation,
                            float(cfg["optical_psf_sigma_px"])) * exposure
        clean_sources.append(clean_src)
        frame = _render(scene, w, h, scale, dx, dy, rotation, blur)
        frame *= exposure
        if kind == "highlight_clipped":
            frame *= 1.65
        shot_scale = float(cfg["shot_scale"])
        if shot_scale > 0:
            frame = rng.poisson(np.maximum(frame, 0) / shot_scale).astype(np.float32) * shot_scale
        read_sigma = float(cfg["read_noise_sigma"])
        if kind == "abnormal_noise":
            read_sigma *= 7.0
        frame += rng.normal(0, read_sigma, frame.shape).astype(np.float32)
        frame = np.clip(frame, 0, 1)
        frames.append(frame)
        transforms.append((dx, dy, rotation))
        kinds.append(kind)
        # Only observables belong here. No kind, transform, seed, or scene data.
        metadata.append({"sequence_index": i, "nominal_exposure_relative": exposure,
                         "sample_format": "float32_simulated_linear", "timestamp_s": i * 0.12})

    obs = ObservationSequence(fixture_id, np.stack(frames).astype(np.float32),
                              tuple(f"{fixture_id}-frame-{i:03d}" for i in range(count)),
                              tuple(metadata), {"width": w, "height": h})
    oracle = EvaluationOracle(clean, np.stack(clean_sources).astype(np.float32), scene,
                             np.asarray(transforms, dtype=np.float32),
                             tuple(kinds), tuple(i for i, k in enumerate(kinds) if k != "good"),
                             cfg, int(cfg["seed"]), ((w - 1) / 2, (h - 1) / 2), min(w, h) * 0.425)
    return obs, oracle


def freeze_fixture(root: str | Path, config: dict | None = None, *, fixture_id="sim-0001") -> dict:
    """Persist observations and evaluator-only truth in separate files/directories."""
    root = Path(root)
    obs_dir, private_dir = root / fixture_id / "observed", root / fixture_id / "evaluator-private"
    obs_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    obs, oracle = generate_sequence(config, fixture_id=fixture_id,
                                    inject_outliers=True if config is None else config.get("inject_outliers", True))
    obs_path = obs_dir / "frames.npz"
    truth_path = private_dir / "oracle.npz"
    np.savez_compressed(obs_path, frames=obs.frames,
                        frame_ids=np.asarray(obs.frame_ids),
                        public_metadata_json=np.asarray(json.dumps(obs.public_metadata)))
    np.savez_compressed(truth_path, clean_reference=oracle.clean_reference,
                        clean_source_frames=oracle.clean_source_frames,
                        high_resolution_scene=oracle.high_resolution_scene,
                        true_transforms=oracle.true_transforms,
                        bad_frame_kinds=np.asarray(oracle.bad_frame_kinds),
                        expected_bad_indices=np.asarray(oracle.expected_bad_indices),
                        generation_parameters_json=np.asarray(json.dumps(oracle.generation_parameters)),
                        seed=np.asarray(oracle.seed), disk_center_xy=np.asarray(oracle.disk_center_xy),
                        disk_radius_px=np.asarray(oracle.disk_radius_px))
    protocol = {"fixture_id": fixture_id, "generator_version": GENERATOR_VERSION,
                "metric_version": METRIC_VERSION, "seed": oracle.seed,
                "parameters": oracle.generation_parameters,
                "observation_file": "observed/frames.npz",
                "oracle_file_evaluator_only": "evaluator-private/oracle.npz",
                "sha256_observations": hashlib.sha256(obs_path.read_bytes()).hexdigest(),
                "sha256_oracle": hashlib.sha256(truth_path.read_bytes()).hexdigest(),
                "frame_count": len(obs.frame_ids), "expected_bad_indices": list(oracle.expected_bad_indices)}
    (root / fixture_id / "fixture.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    return protocol
