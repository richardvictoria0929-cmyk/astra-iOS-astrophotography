"""Versioned remediation reconstruction. Observation-only; no truth imports."""

import numpy as np

from .types import Alignment, FrameAssessment
from .algorithms import _lucas_kanade_rigid, warp as warp_bilinear
from .remediation_quality import FROZEN_THRESHOLDS, QUALITY_VERSION, score_frames


ALIGNMENT_VERSION = "align-0.7"
RECONSTRUCTION_VERSION = "reconstruct-0.9"


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


def _fourier_shear_x(image, coefficient, center_y, pad=16):
    padded = np.pad(image, ((0, 0), (pad, pad)), mode="reflect").astype(np.float64)
    rows, width = padded.shape
    shifts = coefficient * (np.arange(rows, dtype=np.float64) - center_y)
    freq = np.fft.fftfreq(width)[None, :]
    phase = np.exp(-2j * np.pi * shifts[:, None] * freq)
    moved = np.fft.ifft(np.fft.fft(padded, axis=1) * phase, axis=1).real
    return moved[:, pad:pad + image.shape[1]].astype(np.float32)


def _fourier_shear_y(image, coefficient, center_x, pad=16):
    padded = np.pad(image, ((pad, pad), (0, 0)), mode="reflect").astype(np.float64)
    height, cols = padded.shape
    shifts = coefficient * (np.arange(cols, dtype=np.float64) - center_x)
    freq = np.fft.fftfreq(height)[:, None]
    phase = np.exp(-2j * np.pi * freq * shifts[None, :])
    moved = np.fft.ifft(np.fft.fft(padded, axis=0) * phase, axis=0).real
    return moved[pad:pad + image.shape[0], :].astype(np.float32)


def warp_fourier_rigid(image, dx, dy, rotation_deg=0.0):
    """Apply an in-band Fourier shift and a three-shear Fourier rotation."""
    theta = np.deg2rad(rotation_deg)
    if abs(theta) < 1e-10:
        rotated = image.astype(np.float32, copy=True)
    else:
        a = -np.tan(theta / 2.0)
        b = np.sin(theta)
        cy, cx = (image.shape[0] - 1) / 2, (image.shape[1] - 1) / 2
        rotated = _fourier_shear_x(image, a, cy)
        rotated = _fourier_shear_y(rotated, b, cx)
        rotated = _fourier_shear_x(rotated, a, cy)
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

    # Restrict reference candidates to the robust target-position cluster, then
    # select the sharpest observable source after normalizing high-frequency
    # energy by background noise. This makes "best_single" an image-quality
    # choice rather than simply the geometrically central frame.
    centers = np.asarray([[assessments[i].components["estimated_disk_center_x"],
                           assessments[i].components["estimated_disk_center_y"]]
                          for i in initially_good])
    center_med = np.median(centers, axis=0)
    center_mad = 1.4826 * np.median(np.abs(centers - center_med), axis=0)
    center_scale = np.maximum(center_mad, 0.5)
    center_z = np.sqrt(np.sum(((centers - center_med) / center_scale) ** 2, axis=1))
    reference_pool = [i for i, z in zip(initially_good, center_z) if z <= 3.0]
    if not reference_pool:
        reference_pool = initially_good
    def reference_quality(i):
        c = assessments[i].components
        sharpness_to_sky_noise = c["disk_laplacian_energy"] / max(c["background_noise_mad_sigma"], 1e-5)
        center_distance = float(np.linalg.norm(np.asarray([c["estimated_disk_center_x"],
                                                           c["estimated_disk_center_y"]]) - center_med))
        return (sharpness_to_sky_noise, c["disk_limb_gradient"], -center_distance)
    ref_idx = max(reference_pool, key=reference_quality)
    reference = frames[ref_idx]
    candidate_rows = []
    for i in initially_good:
        if i == ref_idx:
            warped = reference.copy()
            warped_bilinear = reference.copy()
            warped_fourier = reference.copy()
            warped_fourier_rigid = reference.copy()
            record = Alignment(observations.frame_ids[i], observations.frame_ids[ref_idx],
                               0.0, 0.0, 0.0, 1.0, 0.0, "high_confidence", ALIGNMENT_VERSION)
        else:
            dx, dy, angle, corr, _ = _lucas_kanade_rigid(reference, frames[i], 2.0)
            warped = warp_bicubic(frames[i], dx, dy, angle)
            warped_bilinear = warp_bilinear(frames[i], dx, dy, angle)
            warped_fourier = warp_fourier_translation(frames[i], dx, dy, angle)
            warped_fourier_rigid = warp_fourier_rigid(frames[i], dx, dy, angle)
            residual = float(np.sqrt(np.mean((reference - warped) ** 2)))
            status = "high_confidence" if corr > 0.82 and residual < rules["maximum_registration_residual"] else "low_confidence"
            record = Alignment(observations.frame_ids[i], observations.frame_ids[ref_idx],
                               float(dx), float(dy), float(angle), float(np.clip(corr, 0, 1)),
                               residual, status, ALIGNMENT_VERSION)
        candidate_rows.append((i, warped, warped_bilinear, warped_fourier, warped_fourier_rigid, record))

    translation_vectors = np.asarray([[row[5].dx, row[5].dy] for row in candidate_rows], dtype=np.float64)
    translation_center = np.median(translation_vectors, axis=0)
    translation_mad = 1.4826 * np.median(np.abs(translation_vectors - translation_center), axis=0)
    translation_scale = np.maximum(translation_mad, 0.5)
    aligned, aligned_bilinear, aligned_fourier, aligned_fourier_rigid, alignments, accepted = [], [], [], [], [], []
    for i, warped, warped_bilinear, warped_fourier, warped_fourier_rigid, record in candidate_rows:
        alignments.append(record)
        deviation = (np.asarray([record.dx, record.dy]) - translation_center) / translation_scale
        robust_translation_z = float(np.sqrt(np.sum(deviation * deviation)))
        magnitude = float(np.hypot(record.dx, record.dy))
        assessments[i].components["registration_translation_magnitude_px"] = magnitude
        assessments[i].components["registration_translation_robust_z"] = robust_translation_z
        if robust_translation_z > rules["relative_registration_translation_z_max"]:
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
        aligned_fourier_rigid.append(warped_fourier_rigid)

    if not aligned:
        raise ValueError("all frame alignments failed")
    stack = np.stack(aligned).astype(np.float32)
    bilinear_stack = np.stack(aligned_bilinear).astype(np.float32)
    fourier_stack = np.stack(aligned_fourier).astype(np.float32)
    fourier_rigid_stack = np.stack(aligned_fourier_rigid).astype(np.float32)
    reference_exposure = float(observations.public_metadata[ref_idx].get("nominal_exposure_relative", 1.0))
    if not np.isfinite(reference_exposure) or reference_exposure <= 0:
        raise ValueError("reference exposure metadata must be finite and positive")
    exposure_factors = []
    for i in accepted:
        exposure = float(observations.public_metadata[i].get("nominal_exposure_relative", 1.0))
        if not np.isfinite(exposure) or exposure <= 0:
            raise ValueError(f"invalid exposure metadata for {observations.frame_ids[i]}")
        exposure_factors.append(reference_exposure / exposure)
    exposure_factors = np.asarray(exposure_factors, dtype=np.float32)
    normalized_stack = stack * exposure_factors[:, None, None]
    normalized_bilinear = bilinear_stack * exposure_factors[:, None, None]
    normalized_fourier = fourier_stack * exposure_factors[:, None, None]
    normalized_fourier_rigid = fourier_rigid_stack * exposure_factors[:, None, None]
    mean = np.mean(normalized_stack, axis=0).astype(np.float32)
    med_noise = max(float(np.median([assessments[i].components["background_noise_mad_sigma"] for i in accepted])), 1e-6)
    weights = np.asarray([np.clip((med_noise / max(assessments[i].components["noise_mad_sigma"], 1e-6))**2,
                                  0.35, 2.5) for i in accepted], dtype=np.float32)
    weighted = np.average(normalized_stack, axis=0, weights=weights).astype(np.float32)
    median = np.median(normalized_stack, axis=0).astype(np.float32)
    robust = _sigma_clip(normalized_stack)
    denoised = _edge_aware_denoise(robust)
    fourier_mean = np.mean(normalized_fourier, axis=0).astype(np.float32)
    fourier_weighted = np.average(normalized_fourier, axis=0, weights=weights).astype(np.float32)
    fourier_median = np.median(normalized_fourier, axis=0).astype(np.float32)
    fourier_sigma = _sigma_clip(normalized_fourier).astype(np.float32)
    fourier_denoised = _edge_aware_denoise(fourier_sigma)
    rigid_mean = np.mean(normalized_fourier_rigid, axis=0).astype(np.float32)
    rigid_weighted = np.average(normalized_fourier_rigid, axis=0, weights=weights).astype(np.float32)
    rigid_median = np.median(normalized_fourier_rigid, axis=0).astype(np.float32)
    rigid_sigma = _sigma_clip(normalized_fourier_rigid).astype(np.float32)
    rigid_denoised = _edge_aware_denoise(rigid_sigma)
    half = max(1, len(stack) // 2)
    half_a = np.mean(normalized_stack[:half], axis=0).astype(np.float32)
    half_b = np.mean(normalized_stack[half:], axis=0).astype(np.float32) if len(stack) > half else half_a.copy()
    baselines = {
        "ordinary_single": frames[0].copy(),
        "best_single": frames[ref_idx].copy(),
        "stage_aligned_stack": stack,
        "stage_exposure_normalized_stack": normalized_stack.astype(np.float32),
        "candidate_bilinear_aligned_stack": bilinear_stack,
        "candidate_fourier_aligned_stack": fourier_stack,
        "candidate_fourier_rigid_aligned_stack": fourier_rigid_stack,
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
        "fourier_rigid_mean": rigid_mean,
        "fourier_rigid_weighted_mean": rigid_weighted,
        "fourier_rigid_median": rigid_median,
        "fourier_rigid_sigma_clipped": rigid_sigma,
        "fourier_rigid_sigma_clipped_denoised": rigid_denoised,
        "half_stack_a": half_a,
        "half_stack_b": half_b,
    }
    operations = [
        {"type": "score", "version": QUALITY_VERSION, "thresholds": rules,
         "features": ["lunar-disk-clipping", "connected-clip-area", "normalized-laplacian-energy",
                      "limb-sector-gradient", "high-pass-noise", "exposure-deviation"]},
        {"type": "align", "version": ALIGNMENT_VERSION, "reference": observations.frame_ids[ref_idx],
         "estimator": "robust-Lucas-Kanade-rigid",
         "reference_selection": "robust-position-inliers-then-max-laplacian-over-background-noise",
         "resampling_candidates": ["bilinear-reflect", "Catmull-Rom-bicubic-reflect",
                                   "bicubic-rotation-plus-padded-Fourier-translation",
                                   "three-shear-Fourier-rotation-plus-Fourier-translation"]},
        {"type": "exposure_normalize", "version": RECONSTRUCTION_VERSION,
         "reference_exposure_relative": reference_exposure,
         "method": "scale-linear-source-to-reference-exposure-from-public-metadata"},
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
