"""Frozen experiment protocol and provisional gate values."""

GENERATOR_VERSION = "lunar-sim-0.2"
METRIC_VERSION = "metrics-0.3"
QUALITY_VERSION = "quality-0.2"
ALIGNMENT_VERSION = "align-0.2"
RECONSTRUCTION_VERSION = "reconstruct-0.3"

PROVISIONAL_GATES = {
    "registration_rms_px": 0.25,
    "registration_valid_fraction": 0.90,
    "snr_proxy_improvement_16_frames": 2.5,
    "edge_metric_loss_fraction": 0.05,
    "bad_frame_recall": 0.90,
    "integrity_required": True,
}

DEFAULT_CONFIG = {
    "width": 96,
    "height": 96,
    "supersample": 4,
    "frame_count": 16,
    "seed": 1402,
    "shot_scale": 0.012,
    "read_noise_sigma": 0.004,
    "exposure_jitter": 0.025,
    "optical_psf_sigma_px": 0.55,
    "rotation_span_deg": 0.30,
    "translation_span_px": 1.25,
}
