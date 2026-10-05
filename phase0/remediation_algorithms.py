"""Versioned remediation reconstruction. Observation-only; no truth imports."""

import numpy as np

from .types import Alignment, FrameAssessment
from .algorithms import _lucas_kanade_rigid, warp as warp_bilinear
from .remediation_quality import FROZEN_THRESHOLDS, QUALITY_VERSION, score_frames


ALIGNMENT_VERSION = "align-0.4"
RECONSTRUCTION_VERSION = "reconstruct-0.5"


def _reflect_index(i, n):
    if n <= 1:
        return np.zeros_like(i)
    q = np.mod(i, 2 * (n - 1))
    return np.where(q > n - 1, 2 * (n - 1) - q, q).astype(int)


def _cubic_weight(x):
    a = -0.5
    x = np.abs(x)
    return np.where(x < 1,
                    (a + 2) * x**3 - (a + 3) * x**2 + 1,
                    np.where(x < 2, a*x**3 - 5*a*x**2 + 8*a*x - 4*a, 0.0))


def _bicubic_reflect(image, x, y):
    """Catmull-Rom interpolation with reflected support; one final resample."""
    h, w = image.shape
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    out = np.zeros(x.shape, dtype=np.float64)
    for oy in (-1, 0, 1, 2):
        yy = _reflect_index(iy + oy, h)
        wy = _cubic_weight(y - (iy + oy))
        for ox in (-1, 0, 1, 2):
            xx = _reflect_index(ix + ox, w)
            wx = _cubic_weight(x - (ix + ox))
            out += image[yy, xx] * wy * wx
    return out.astype(np.float32)


def warp_bicubic(image, dx, dy, rotation_deg=0.0):
    h, w = image.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    angle = np.deg2rad(rotation_deg)
    xo, yo = xx - cx - dx, yy - cy - dy
    xs = np.cos(angle) * xo + np.sin(angle) * yo + cx
    ys = -np.sin(angle) * xo + np.cos(angle) * yo + cy
    return _bicubic_reflect(image, xs, ys)


def _fourier_translate_reflect(image, dx, dy, pad=16):
    """Subpixel translation through a padded Fourier phase ramp."""
    padded = np.pad(image, pad, mode="reflect").astype(np.float64)
    h, w = padded.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    phase = np.exp(-2j * np.pi * (fy * dy + fx * dx))
    shifted = np.fft.ifft2(np.fft.fft2(padded) * phase).real
    return shifted[pad:pad + image.shape[0], pad:pad + image.shape[1]].astype(np.float32)


def warp_fourier_translation(image, dx, dy, rotation_deg=0.0):
    # Match the rigid map's operation order: rotate about center, then translate.
    rotated = warp_bicubic(image, 0.0, 0.0, rotation_deg)
    return _fourier_translate_reflect(rotated, dx, dy)


def _sigma_clip(stack, sigma=2.8):
    med = np.median(stack, axis=0)
    mad = np.median(np.abs(stack - med), axis=0) * 1.4826
    keep = np.abs(stack - med) <= sigma * np.maximum(mad, 0.004)
    return np.sum(stack * keep, axis=0) / np.maximum(np.sum(keep, axis=0), 1)


def _local_lowpass(image):
    p = np.pad(image, 1, mode="reflect")
    return (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] +
            p[1:-1, :-2] + 4*p[1:-1, 1:-1] + p[1:-1, 2:] +
            p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 12


def _edge_aware_denoise(image, amount=0.12):
    """Apply the legacy 12% low-pass mix only below a scene-gradient cutoff."""
    gx = np.diff(image, axis=1, prepend=image[:, :1])
    gy = np.diff(image, axis=0, prepend=image[:1, :])
    grad = np.hypot(gx, gy)
    h, w = image.shape
    yy, xx = np.mgrid[0:h, 0:w]
    disk = ((xx - (w - 1)/2)**2 + (yy - (h - 1)/2)**2) < (0.40 * min(h, w))**2
    threshold = float(np.quantile(grad[disk], 0.70)) if np.any(disk) else float(np.quantile(grad, .70))
    strength = np.where(grad <= threshold, amount, 0.0)
    low = _local_lowpass(image)
    return (image * (1 - strength) + low * strength).astype(np.float32)


def _assessment_with_reason(item, reason):
    reasons = tuple(dict.fromkeys((*item.reasons, reason)))
    return FrameAssessment(item.frame_id, item.components, "rejected", reasons, item.score_version)


def reconstruct(observations, *, thresholds=None):
    frames = observations.frames
    rules = dict(FROZEN_THRESHOLDS)
    if thresholds is None:
        thresholds = observations.algorithm_config.get("remediation_thresholds")
    if thresholds:
        rules.update(thresholds)
    assessments = score_frames(frames, observations.frame_ids, thresholds=rules)
    initially_good = [i for i, a in enumerate(assessments) if a.decision == "accepted"]
    if not initially_good:
        raise ValueError("no frames passed observable quality checks")

    # Pick a central target position as reference, reducing the chance that an
    # isolated translated frame shifts the coordinate system for every good frame.
    centers = np.asarray([[assessments[i].components["estimated_disk_center_x"],
                           assessments[i].components["estimated_disk_center_y"]]
                          for i in initially_good])
    center_med = np.median(centers, axis=0)
    ref_idx = min(initially_good, key=lambda i: (
        float(np.linalg.norm(np.asarray([assessments[i].components["estimated_disk_center_x"],
                                         assessments[i].components["estimated_disk_center_y"]]) - center_med)),
        -assessments[i].components["disk_limb_gradient"]))
    reference = frames[ref_idx]
    aligned, aligned_bilinear, aligned_fourier, alignments, accepted = [], [], [], [], []
    for i in initially_good:
        if i == ref_idx:
            warped = reference.copy()
            warped_bilinear = reference.copy()
            warped_fourier = reference.copy()
            record = Alignment(observations.frame_ids[i], observations.frame_ids[ref_idx],
                               0.0, 0.0, 0.0, 1.0, 0.0, "high_confidence", ALIGNMENT_VERSION)
        else:
            dx, dy, angle, corr, _ = _lucas_kanade_rigid(reference, frames[i], 2.0)
            warped = warp_bicubic(frames[i], dx, dy, angle)
            warped_bilinear = warp_bilinear(frames[i], dx, dy, angle)
            warped_fourier = warp_fourier_translation(frames[i], dx, dy, angle)
            residual = float(np.sqrt(np.mean((reference - warped) ** 2)))
            status = "high_confidence" if corr > 0.82 and residual < rules["maximum_registration_residual"] else "low_confidence"
            record = Alignment(observations.frame_ids[i], observations.frame_ids[ref_idx],
                               float(dx), float(dy), float(angle), float(np.clip(corr, 0, 1)),
                               residual, status, ALIGNMENT_VERSION)
        alignments.append(record)
        magnitude = float(np.hypot(record.dx, record.dy))
        if magnitude > rules["maximum_registration_translation_px"]:
            assessments[i] = _assessment_with_reason(assessments[i], "registration_translation_outlier")
            continue
        if abs(record.rotation_deg) > rules["maximum_registration_rotation_deg"]:
            assessments[i] = _assessment_with_reason(assessments[i], "registration_rotation_outlier")
            continue
        if record.status != "high_confidence":
            assessments[i] = _assessment_with_reason(assessments[i], "alignment_low_confidence")
            continue
        accepted.append(i)
        aligned.append(warped)
        aligned_bilinear.append(warped_bilinear)
        aligned_fourier.append(warped_fourier)

    if not aligned:
        raise ValueError("all frame alignments failed")
    stack = np.stack(aligned).astype(np.float32)
    bilinear_stack = np.stack(aligned_bilinear).astype(np.float32)
    fourier_stack = np.stack(aligned_fourier).astype(np.float32)
    mean = np.mean(stack, axis=0).astype(np.float32)
    med_noise = max(float(np.median([assessments[i].components["noise_mad_sigma"] for i in accepted])), 1e-6)
    weights = np.asarray([np.clip((med_noise / max(assessments[i].components["noise_mad_sigma"], 1e-6))**2,
                                  0.35, 2.5) for i in accepted], dtype=np.float32)
    weighted = np.average(stack, axis=0, weights=weights).astype(np.float32)
    median = np.median(stack, axis=0).astype(np.float32)
    robust = _sigma_clip(stack)
    denoised = _edge_aware_denoise(robust)
    fourier_mean = np.mean(fourier_stack, axis=0).astype(np.float32)
    fourier_weighted = np.average(fourier_stack, axis=0, weights=weights).astype(np.float32)
    fourier_median = np.median(fourier_stack, axis=0).astype(np.float32)
    fourier_sigma = _sigma_clip(fourier_stack).astype(np.float32)
    fourier_denoised = _edge_aware_denoise(fourier_sigma)
    half = max(1, len(stack) // 2)
    half_a = np.mean(stack[:half], axis=0).astype(np.float32)
    half_b = np.mean(stack[half:], axis=0).astype(np.float32) if len(stack) > half else half_a.copy()
    baselines = {
        "ordinary_single": frames[0].copy(),
        "best_single": frames[ref_idx].copy(),
        "stage_aligned_stack": stack,
        "candidate_bilinear_aligned_stack": bilinear_stack,
        "candidate_fourier_aligned_stack": fourier_stack,
        "registered_mean": mean,
        "weighted_mean": weighted,
        "median": median,
        "sigma_clipped": robust.astype(np.float32),
        "sigma_clipped_denoised": denoised,
        "fourier_mean": fourier_mean,
        "fourier_weighted_mean": fourier_weighted,
        "fourier_median": fourier_median,
        "fourier_sigma_clipped": fourier_sigma,
        "fourier_sigma_clipped_denoised": fourier_denoised,
        "half_stack_a": half_a,
        "half_stack_b": half_b,
    }
    operations = [
        {"type": "score", "version": QUALITY_VERSION, "thresholds": rules,
         "features": ["lunar-disk-clipping", "connected-clip-area", "normalized-laplacian-energy",
                      "limb-sector-gradient", "high-pass-noise", "exposure-deviation"]},
        {"type": "align", "version": ALIGNMENT_VERSION, "reference": observations.frame_ids[ref_idx],
         "estimator": "robust-Lucas-Kanade-rigid",
         "resampling_candidates": ["bilinear-reflect", "Catmull-Rom-bicubic-reflect",
                                   "bicubic-rotation-plus-padded-Fourier-translation"]},
        {"type": "stack", "version": RECONSTRUCTION_VERSION,
         "methods": ["mean", "inverse-noise-variance-weighted", "median", "sigma-clipped-2.8"]},
        {"type": "denoise", "version": RECONSTRUCTION_VERSION,
         "method": "12-percent-low-pass-only-below-gradient-quantile-0.70"},
    ]
    rejected = [i for i, a in enumerate(assessments) if a.decision == "rejected"]
    return {
        "reference_id": observations.frame_ids[ref_idx],
        "accepted_ids": [observations.frame_ids[i] for i in accepted],
        "rejected_ids": [observations.frame_ids[i] for i in rejected],
        "assessments": assessments,
        "alignments": alignments,
        "baselines": baselines,
        "operations": operations,
        "accepted_indices": accepted,
        "algorithm_version": RECONSTRUCTION_VERSION,
    }
