"""Metric definitions and post-reconstruction measurements."""

import numpy as np


def _gradient(image):
    gx = np.diff(image, axis=1, prepend=image[:, :1])
    gy = np.diff(image, axis=0, prepend=image[:1, :])
    return np.hypot(gx, gy)


def _flat_roi(reference):
    grad = _gradient(reference)
    disk = reference > max(float(np.max(reference)) * 0.12, 0.05)
    threshold = np.quantile(grad[disk], 0.40) if np.any(disk) else 0
    roi = disk & (grad <= threshold)
    return roi if np.count_nonzero(roi) >= 20 else disk


def snr_proxy(image, clean_reference):
    """Mean signal / RMSE from noiseless reference in truth-defined low-gradient lunar ROI.

    Higher is better. This is an evaluator-only, truth-referenced proxy; it is not
    an estimator available to reconstruction code and is not sensor SNR calibration.
    """
    roi = _flat_roi(clean_reference)
    signal = float(np.mean(clean_reference[roi]))
    error_sigma = float(np.sqrt(np.mean((image[roi] - clean_reference[roi]) ** 2)))
    return signal / max(error_sigma, 1e-12)


def edge_sharpness(image, clean_reference):
    """Truth-selected lunar limb-band mean gradient; higher usually means sharper,
    but noise can also raise it. Always interpret with noise/error metrics.
    """
    g = _gradient(clean_reference)
    band = g >= np.quantile(g, 0.94)
    return float(np.mean(_gradient(image)[band])) if np.any(band) else 0.0


def mtf50_proxy(image, clean_reference, *, center_xy=None, radius_px=None):
    """Estimate MTF50 from azimuthally averaged limb edge-spread function.

    Approximate procedure: estimate disk center from intensity centroid, radial-bin
    mean intensity, differentiate the edge profile to a line-spread function, then
    find the first normalized Fourier magnitude crossing 0.5. Units: cycles/pixel.
    This is a synthetic limb proxy; phase/illumination asymmetry limits validity.
    """
    h, w = image.shape
    yy, xx = np.mgrid[0:h, 0:w]
    mask = clean_reference > max(float(np.max(clean_reference)) * 0.12, 0.05)
    if not np.any(mask):
        return 0.0
    if center_xy is None:
        weights = np.clip(clean_reference - np.percentile(clean_reference, 20), 0, None)
        total = max(float(np.sum(weights)), 1e-12)
        cx, cy = float(np.sum(xx * weights) / total), float(np.sum(yy * weights) / total)
    else:
        cx, cy = center_xy
    radius = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    edge_radius = float(radius_px) if radius_px is not None else float(np.quantile(radius[mask], 0.99))
    band = (radius > edge_radius - 8) & (radius < edge_radius + 5)
    bins = np.arange(max(0, int(edge_radius - 8)), int(edge_radius + 6))
    profile = []
    for b in bins:
        ring = band & (radius >= b) & (radius < b + 1)
        if np.any(ring):
            profile.append(float(np.mean(image[ring])))
    if len(profile) < 8:
        return 0.0
    lsf = np.abs(np.diff(np.asarray(profile, dtype=np.float64)))
    if np.max(lsf) <= 0:
        return 0.0
    spec = np.abs(np.fft.rfft(lsf * np.hanning(len(lsf)), n=128))
    spec /= max(float(spec[0]), 1e-12)
    crossed = np.flatnonzero(spec <= 0.5)
    return float(crossed[0] / 128) if len(crossed) else 0.0


def frc_resolution_proxy(image_a, image_b):
    """Fourier ring correlation half-map proxy; report crossing frequency in c/px.

    Values above the threshold are called consistent. A finite-field synthetic
    image and shared optics make this a relative reproducibility proxy, not an
    absolute optical resolution certificate.
    """
    a = image_a.astype(np.float64) - float(np.mean(image_a))
    b = image_b.astype(np.float64) - float(np.mean(image_b))
    fa, fb = np.fft.fftshift(np.fft.fft2(a)), np.fft.fftshift(np.fft.fft2(b))
    h, w = a.shape
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.sqrt((yy - h // 2) ** 2 + (xx - w // 2) ** 2)
    maxr = min(h, w) // 2
    frc = []
    for radius in range(1, maxr):
        shell = (rr >= radius) & (rr < radius + 1)
        cross = np.sum(fa[shell] * np.conj(fb[shell]))
        denom = np.sqrt(np.sum(np.abs(fa[shell]) ** 2) * np.sum(np.abs(fb[shell]) ** 2))
        frc.append(float(np.abs(cross) / max(denom, 1e-12)))
    below = [i for i, v in enumerate(frc, start=1) if v < 1 / 7]
    return float(below[0] / max(h, w)) if below else float((maxr - 1) / max(h, w))


def clipping_fraction(image, low=0.002, high=0.995):
    """Fraction of pixels at sensor floor/ceiling; lower is generally safer."""
    return float(np.mean((image <= low) | (image >= high)))


def ringing_halo(image, clean_reference):
    """Peak overshoot beyond local truth range in a narrow lunar-limb band; lower is better."""
    g = _gradient(clean_reference)
    band = g >= np.quantile(g, 0.94)
    p = np.pad(clean_reference, 2, mode="reflect")
    local_min = np.full_like(clean_reference, np.inf)
    local_max = np.full_like(clean_reference, -np.inf)
    for dy in range(5):
        for dx in range(5):
            v = p[dy:dy + image.shape[0], dx:dx + image.shape[1]]
            local_min = np.minimum(local_min, v)
            local_max = np.maximum(local_max, v)
    over = np.maximum(local_min - image, image - local_max)
    return float(max(0.0, np.max(over[band]))) if np.any(band) else 0.0


def seam_interpolation_proxy(image, clean_reference):
    """Excess gradient energy in outer 3px border versus interior; lower is better.

    Sensitive to scene content and not a general-purpose seam detector. Used only
    for controlled fixture comparisons with unchanged crop support.
    """
    g = _gradient(image)
    border = np.zeros(image.shape, dtype=bool)
    border[:3] = border[-3:] = True
    border[:, :3] = border[:, -3:] = True
    interior = ~border
    return float(np.mean(g[border]) / max(np.mean(g[interior]), 1e-12))


def false_detail_indicators(image, clean_reference):
    """High-frequency unsupported-energy ratio and high-band squared error.

    Evaluator-only truth comparison. Larger values warn that visible high-frequency
    output is weakly supported by the simulated captured scene.
    """
    def highpass(x):
        p = np.pad(x, 1, mode="reflect")
        low = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 4 * p[1:-1, 1:-1]) / 8
        return x - low
    hi, ht = highpass(image), highpass(clean_reference)
    unsupported = hi - ht
    denom = float(np.mean(ht * ht)) + 1e-12
    return {"unsupported_high_frequency_energy_ratio": float(np.mean(unsupported * unsupported) / denom),
            "high_frequency_error_rmse": float(np.sqrt(np.mean(unsupported * unsupported)))}


def reconstruction_error(image, clean_reference):
    """Truth-referenced RMSE and PSNR in normalized linear units; lower RMSE is better."""
    rmse = float(np.sqrt(np.mean((image - clean_reference) ** 2)))
    peak = max(float(np.max(clean_reference)), 1e-12)
    psnr = float(20 * np.log10(peak / max(rmse, 1e-12)))
    return {"rmse": rmse, "psnr_db": psnr}


def registration_error(estimated, expected):
    """RMS translation error in pixels and rotation error in degrees; evaluator only."""
    e = np.asarray(estimated, dtype=np.float64)
    t = np.asarray(expected, dtype=np.float64)
    d = e - t
    return {"translation_error_px": float(np.sqrt(np.mean(d[:, :2] ** 2))),
            "rotation_error_deg": float(np.sqrt(np.mean(d[:, 2] ** 2)))}
