"""Interpretable reconstruction-side frame scoring; no access to generator/oracle."""

import numpy as np
from .types import FrameAssessment
from .config import QUALITY_VERSION


def _blur(image: np.ndarray) -> np.ndarray:
    p = np.pad(image, 1, mode="reflect")
    return (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 4 * p[1:-1, 1:-1]) / 8.0


def _limb_edge_sharpness(image: np.ndarray) -> float:
    """Mean radial gradient near an automatically estimated bright-disk limb."""
    h, w = image.shape
    cy, cx = (h - 1) / 2, (w - 1) / 2
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    disk = image > max(float(np.max(image)) * 0.08, 0.04)
    radii = rr[disk]
    if len(radii) < 20:
        return 0.0
    radius = float(np.quantile(radii, 0.985))
    angles = np.linspace(0, 2 * np.pi, 128, endpoint=False)
    radial = np.arange(max(1, int(radius * 0.78)), int(radius * 1.14) + 1)
    samples = np.zeros((len(angles), len(radial)), dtype=np.float32)
    for j, angle in enumerate(angles):
        x = np.rint(cx + radial * np.cos(angle)).astype(int)
        y = np.rint(cy + radial * np.sin(angle)).astype(int)
        ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        samples[j, ok] = image[y[ok], x[ok]]
    grad = np.abs(np.diff(samples, axis=1))
    return float(np.mean(np.max(grad, axis=1)))


def score_frames(frames: np.ndarray, frame_ids: tuple[str, ...]) -> list[FrameAssessment]:
    raw = []
    for frame in frames:
        f = frame.astype(np.float32)
        gx = np.diff(f, axis=1, prepend=f[:, :1])
        gy = np.diff(f, axis=0, prepend=f[:1, :])
        gradient = np.hypot(gx, gy)
        highpass = f - _blur(f)
        noise = float(1.4826 * np.median(np.abs(highpass - np.median(highpass))))
        raw.append({
            "clipping_fraction": float(np.mean((f <= 0.002) | (f >= 0.995))),
            "highlight_clipping_fraction": float(np.mean(f >= 0.995)),
            "underexposed_fraction": float(np.mean(f <= 0.002)),
            "contrast_std": float(np.std(f)),
            "edge_sharpness": float(np.mean(gradient)),
            "limb_edge_sharpness": _limb_edge_sharpness(f),
            "laplacian_variance": float(np.var(4 * f - _blur(f) * 4)),
            "noise_mad_sigma": noise,
            "exposure_median": float(np.median(f)),
        })
    med_sharp = max(float(np.median([x["edge_sharpness"] for x in raw])), 1e-8)
    med_noise = max(float(np.median([x["noise_mad_sigma"] for x in raw])), 1e-8)
    med_limb = max(float(np.median([x["limb_edge_sharpness"] for x in raw])), 1e-8)
    assessments = []
    for frame_id, m in zip(frame_ids, raw):
        reasons = []
        if m["highlight_clipping_fraction"] > 0.02:
            reasons.append("highlight_clipping_fraction>0.02")
        if m["edge_sharpness"] < 0.55 * med_sharp:
            reasons.append("relative_edge_sharpness<0.55")
        if m["limb_edge_sharpness"] < 0.68 * med_limb:
            reasons.append("relative_limb_edge_sharpness<0.68")
        if m["noise_mad_sigma"] > 1.35 * med_noise:
            reasons.append("relative_noise>1.35")
        m["relative_sharpness"] = m["edge_sharpness"] / med_sharp
        m["relative_noise"] = m["noise_mad_sigma"] / med_noise
        m["relative_limb_edge_sharpness"] = m["limb_edge_sharpness"] / med_limb
        m["motion_alignment_confidence"] = 0.0  # assigned after registration, never a hidden transform
        decision = "rejected" if reasons else "accepted"
        assessments.append(FrameAssessment(frame_id, m, decision, tuple(reasons), QUALITY_VERSION))
    return assessments
