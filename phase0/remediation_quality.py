"""Interpretable versioned scorer for the bounded remediation experiment."""

import numpy as np
from .types import FrameAssessment


QUALITY_VERSION = "quality-0.5"
FROZEN_THRESHOLDS = {
    "disk_clip_fraction": 0.004,
    "largest_clip_component_pixels": 12,
    "relative_laplacian_energy_min": 0.55,
    "relative_limb_gradient_min": 0.62,
    "relative_noise_mad_max": 2.5,
    "relative_background_noise_mad_max": 2.5,
    "relative_exposure_deviation_max": 0.35,
    "relative_registration_translation_z_max": 3.0,
    "maximum_registration_rotation_deg": 1.50,
    "maximum_registration_residual": 0.28,
}


def _reflect_indices(i, n):
    if n <= 1:
        return np.zeros_like(i)
    q = np.mod(i, 2 * (n - 1))
    return np.where(q > n - 1, 2 * (n - 1) - q, q).astype(int)


def _largest_component(mask):
    """Largest 8-connected true component; avoids a dependency on SciPy."""
    ys, xs = np.nonzero(mask)
    seen = np.zeros(mask.shape, dtype=bool)
    largest = 0
    h, w = mask.shape
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        area = 0
        while stack:
            y, x = stack.pop()
            area += 1
            for yy in range(max(0, y - 1), min(h, y + 2)):
                for xx in range(max(0, x - 1), min(w, x + 2)):
                    if mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
        largest = max(largest, area)
    return largest


def _disk_roi(frame):
    h, w = frame.shape
    yy, xx = np.mgrid[0:h, 0:w]
    # Estimate the limb geometry from a low threshold mask and robust spatial
    # bounds. Intensity weighting is avoided because phase illumination biases
    # the lunar centroid well away from the physical disk center.
    threshold = max(0.02, float(np.quantile(frame, 0.985)) * 0.035)
    candidate = frame > threshold
    ys, xs = np.nonzero(candidate)
    if len(xs) >= 100:
        xlo, xhi = np.quantile(xs, (0.005, 0.995))
        ylo, yhi = np.quantile(ys, (0.005, 0.995))
        cx = float((xlo + xhi) / 2)
        cy = float((ylo + yhi) / 2)
    else:
        cx, cy = (w - 1) / 2, (h - 1) / 2
    # A robust lunar-disk proxy centered on the measured bright-field centroid.
    radius = 0.435 * min(h, w)
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return rr <= radius, rr, (cx, cy), radius


def _components(frame):
    f = frame.astype(np.float32)
    roi, rr, (cx, cy), radius = _disk_roi(f)
    gx = np.diff(f, axis=1, prepend=f[:, :1])
    gy = np.diff(f, axis=0, prepend=f[:1, :])
    grad = np.hypot(gx, gy)
    lap = 4 * f - np.roll(f, 1, 0) - np.roll(f, -1, 0) - np.roll(f, 1, 1) - np.roll(f, -1, 1)
    disk_values = f[roi]
    contrast = max(float(np.quantile(disk_values, .95) - np.quantile(disk_values, .10)), 1e-6)
    radial = (rr > radius * 0.78) & (rr < radius * 1.08)
    sectors = []
    theta = np.arctan2(np.mgrid[0:f.shape[0], 0:f.shape[1]][0] - cy,
                       np.mgrid[0:f.shape[0], 0:f.shape[1]][1] - cx)
    for sector in range(8):
        angle = (theta >= -np.pi + sector * np.pi / 4) & (theta < -np.pi + (sector + 1) * np.pi / 4)
        use = radial & angle
        sectors.append(float(np.mean(grad[use])) if np.any(use) else 0.0)
    clipped = (f >= 0.995) & roi
    disk_n = max(int(np.count_nonzero(roi)), 1)
    disk_gradient = grad[roi]
    padded = np.pad(f, 1, mode="reflect")
    low = (padded[:-2, 1:-1] + padded[2:, 1:-1] + padded[1:-1, :-2] +
           padded[1:-1, 2:] + 4 * padded[1:-1, 1:-1]) / 8
    highpass = (f - low)[roi]
    highpass_median = float(np.median(highpass))
    sky_highpass = (f - low)[~roi]
    sky_highpass_median = float(np.median(sky_highpass)) if len(sky_highpass) else 0.0
    return {
        "disk_clip_fraction": float(np.count_nonzero(clipped) / disk_n),
        "largest_clip_component_pixels": float(_largest_component(clipped)),
        "whole_frame_clip_fraction": float(np.mean(f >= 0.995)),
        "disk_laplacian_energy": float(np.median(np.abs(lap[roi])) / contrast),
        "disk_limb_gradient": float(np.median(sectors)),
        "limb_sector_min_to_median": float(min(sectors) / max(float(np.median(sectors)), 1e-8)),
        "disk_gradient_mean": float(np.mean(disk_gradient)),
        "noise_mad_sigma": float(1.4826 * np.median(np.abs(highpass - highpass_median))),
        "background_noise_mad_sigma": float(1.4826 * np.median(np.abs(sky_highpass - sky_highpass_median)))
                                       if len(sky_highpass) else 0.0,
        "exposure_median": float(np.median(disk_values)),
        "disk_contrast": contrast,
        "estimated_disk_center_x": cx,
        "estimated_disk_center_y": cy,
    }


def score_frames(frames: np.ndarray, frame_ids: tuple[str, ...], *,
                 thresholds: dict | None = None) -> list[FrameAssessment]:
    rules = dict(FROZEN_THRESHOLDS)
    if thresholds:
        rules.update(thresholds)
    raw = [_components(frame) for frame in frames]
    # Median/MAD reference is burst-relative, but absolute clipping and later
    # registration checks ensure a minority failure cannot vanish in the median.
    med_lap = max(float(np.median([m["disk_laplacian_energy"] for m in raw])), 1e-9)
    med_limb = max(float(np.median([m["disk_limb_gradient"] for m in raw])), 1e-9)
    med_noise = max(float(np.median([m["noise_mad_sigma"] for m in raw])), 1e-9)
    med_background_noise = max(float(np.median([m["background_noise_mad_sigma"] for m in raw])), 1e-9)
    med_exposure = max(float(np.median([m["exposure_median"] for m in raw])), 1e-9)
    assessments = []
    for frame_id, components in zip(frame_ids, raw):
        c = dict(components)
        c["relative_laplacian_energy"] = c["disk_laplacian_energy"] / med_lap
        c["relative_limb_gradient"] = c["disk_limb_gradient"] / med_limb
        c["relative_noise_mad"] = c["noise_mad_sigma"] / med_noise
        c["relative_background_noise_mad"] = c["background_noise_mad_sigma"] / med_background_noise
        c["relative_exposure_deviation"] = abs(c["exposure_median"] / med_exposure - 1.0)
        reasons = []
        if (c["disk_clip_fraction"] > rules["disk_clip_fraction"] or
                c["largest_clip_component_pixels"] > rules["largest_clip_component_pixels"]):
            reasons.append("lunar_disk_highlight_clipping")
        if c["relative_laplacian_energy"] < rules["relative_laplacian_energy_min"]:
            reasons.append("relative_disk_laplacian_energy_below_threshold")
        if c["relative_limb_gradient"] < rules["relative_limb_gradient_min"]:
            reasons.append("relative_limb_gradient_below_threshold")
        if c["relative_noise_mad"] > rules["relative_noise_mad_max"]:
            reasons.append("relative_noise_mad_above_threshold")
        if c["relative_background_noise_mad"] > rules.get("relative_background_noise_mad_max", 2.5):
            reasons.append("relative_background_noise_mad_above_threshold")
        if c["relative_exposure_deviation"] > rules["relative_exposure_deviation_max"]:
            reasons.append("exposure_deviation_above_threshold")
        assessments.append(FrameAssessment(frame_id, c, "rejected" if reasons else "accepted",
                                           tuple(reasons), QUALITY_VERSION))
    return assessments
