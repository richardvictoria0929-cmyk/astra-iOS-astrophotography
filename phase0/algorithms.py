"""Reconstruction-side algorithms. This module must never import generator/evaluator."""

import numpy as np
from .types import ObservationSequence, Alignment, ReconstructionResult
from .quality import score_frames
from .config import ALIGNMENT_VERSION, RECONSTRUCTION_VERSION


def _parabolic(left: float, center: float, right: float) -> float:
    denom = left - 2.0 * center + right
    return 0.0 if abs(denom) < 1e-12 else float(0.5 * (left - right) / denom)


def _phase_translation_fourier(reference: np.ndarray, moving: np.ndarray) -> tuple[float, float, float, float]:
    """Fast FFT estimate used to center local spatial-domain subpixel search."""
    ref = reference.astype(np.float64)
    mov = moving.astype(np.float64)
    h, w = ref.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    fr = np.fft.fft2((ref - ref.mean()) * window)
    fm = np.fft.fft2((mov - mov.mean()) * window)
    cross = fr * np.conj(fm)
    cross /= np.maximum(np.abs(cross), 1e-12)
    corr = np.abs(np.fft.ifft2(cross))
    py, px = np.unravel_index(np.argmax(corr), corr.shape)
    peak = float(corr[py, px])
    # The phase-correlation peak is the content shift needed to align moving to reference.
    ox = _parabolic(corr[py, (px - 1) % w], corr[py, px], corr[py, (px + 1) % w])
    oy = _parabolic(corr[(py - 1) % h, px], corr[py, px], corr[(py + 1) % h, px])
    sx = float(px if px <= w // 2 else px - w) + ox
    sy = float(py if py <= h // 2 else py - h) + oy
    confidence = peak / max(float(np.mean(corr)), 1e-12)
    return sx, sy, confidence, peak


def _correlation_after_shift(reference, moving, dx, dy):
    aligned = warp(moving, dx, dy, 0)
    margin = max(4, min(reference.shape) // 16)
    r = reference[margin:-margin, margin:-margin].astype(np.float64)
    q = aligned[margin:-margin, margin:-margin].astype(np.float64)
    r -= np.mean(r)
    q -= np.mean(q)
    return float(np.sum(r * q) / max(np.sqrt(np.sum(r * r) * np.sum(q * q)), 1e-12))


def phase_translation(reference: np.ndarray, moving: np.ndarray) -> tuple[float, float, float, float]:
    """Return subpixel content shift to apply, estimated by local normalized correlation.

    FFT gives a coarse starting point; a deterministic spatial-domain grid avoids
    relying on a biased three-point parabola for fractionally sampled images.
    """
    coarse_x, coarse_y, confidence, peak = _phase_translation_fourier(reference, moving)
    center_x, center_y = round(coarse_x), round(coarse_y)
    candidates = np.arange(-1.5, 1.51, 0.25)
    best = (-np.inf, float(center_x), float(center_y))
    for oy in candidates:
        for ox in candidates:
            dx, dy = center_x + ox, center_y + oy
            score = _correlation_after_shift(reference, moving, dx, dy)
            if score > best[0]:
                best = (score, dx, dy)
    _, bx, by = best
    fine = np.arange(-0.20, 0.201, 0.05)
    for oy in fine:
        for ox in fine:
            dx, dy = bx + ox, by + oy
            score = _correlation_after_shift(reference, moving, dx, dy)
            if score > best[0]:
                best = (score, dx, dy)
    return best[1], best[2], confidence, peak


def warp(image: np.ndarray, dx: float, dy: float, rotation_deg: float = 0.0) -> np.ndarray:
    """Translate/rotate image content by (dx,dy,angle), with reflected edge fill."""
    h, w = image.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    a = np.deg2rad(rotation_deg)
    # inverse map: output coordinate -> source coordinate
    xo, yo = xx - cx - dx, yy - cy - dy
    xs = np.cos(a) * xo + np.sin(a) * yo + cx
    ys = -np.sin(a) * xo + np.cos(a) * yo + cy
    return _bilinear_reflect(image, xs, ys)


def _bilinear_reflect(im: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    h, w = im.shape
    x = np.mod(x, 2 * (w - 1))
    y = np.mod(y, 2 * (h - 1))
    x = np.where(x > w - 1, 2 * (w - 1) - x, x)
    y = np.where(y > h - 1, 2 * (h - 1) - y, y)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    ax, ay = x - x0, y - y0
    return ((1 - ay) * ((1 - ax) * im[y0, x0] + ax * im[y0, x1]) +
            ay * ((1 - ax) * im[y1, x0] + ax * im[y1, x1])).astype(np.float32)


def align_pair(reference: np.ndarray, moving: np.ndarray, frame_id: str, reference_id: str,
               max_rotation_deg: float = 2.0) -> tuple[np.ndarray, Alignment]:
    dx, dy, angle, corr, residual = _lucas_kanade_rigid(reference, moving, max_rotation_deg)
    aligned = warp(moving, dx, dy, angle)
    residual = float(np.sqrt(np.mean((reference - aligned) ** 2)))
    status = "high_confidence" if corr > 0.82 and residual < 0.22 else "low_confidence"
    record = Alignment(frame_id, reference_id, dx, dy, angle, float(np.clip(corr, 0, 1)), residual, status)
    return aligned, record


def _lucas_kanade_rigid(reference, moving, max_rotation_deg):
    """Iterative robust translation+small-rotation fit using observed pixels only."""
    h, w = reference.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    rlo = float(np.quantile(reference, 0.02))
    rhi = float(np.quantile(reference, 0.995))
    mlo = float(np.quantile(moving, 0.02))
    mhi = float(np.quantile(moving, 0.995))
    ref = np.clip((reference - rlo) / max(rhi - rlo, 1e-8), 0, 1)
    mov = np.clip((moving - mlo) / max(mhi - mlo, 1e-8), 0, 1)
    mask = ref > 0.07
    if np.count_nonzero(mask) < 100:
        mask = np.ones_like(ref, dtype=bool)
    dx = dy = theta = 0.0
    for _ in range(24):
        aligned = warp(mov, dx, dy, theta)
        gy, gx = np.gradient(aligned)
        xo, yo = xx - cx - dx, yy - cy - dy
        jx, jy = -gx, -gy
        jt = (gx * yo - gy * xo) * np.pi / 180.0
        jac = np.stack((jx[mask], jy[mask], jt[mask]), axis=1)
        residual = (ref - aligned)[mask]
        weights = 1.0 / np.maximum(1.0, np.abs(residual) / 0.12)
        hessian = jac.T @ (weights[:, None] * jac)
        gradient = jac.T @ (weights * residual)
        try:
            delta = np.linalg.solve(hessian + np.eye(3) * 1e-7, gradient)
        except np.linalg.LinAlgError:
            break
        dx += float(np.clip(delta[0], -1.0, 1.0))
        dy += float(np.clip(delta[1], -1.0, 1.0))
        theta += float(np.clip(delta[2], -0.25, 0.25))
        theta = float(np.clip(theta, -max_rotation_deg, max_rotation_deg))
        if np.linalg.norm(delta[:2]) < 0.002 and abs(delta[2]) < 0.002:
            break
    aligned = warp(mov, dx, dy, theta)
    r, q = ref[mask], aligned[mask]
    r, q = r - np.mean(r), q - np.mean(q)
    corr = float(np.sum(r * q) / max(np.sqrt(np.sum(r * r) * np.sum(q * q)), 1e-12))
    rmse = float(np.sqrt(np.mean((ref[mask] - aligned[mask]) ** 2)))
    return dx, dy, theta, corr, rmse


def _sigma_clip_stack(stack: np.ndarray, sigma: float = 2.8) -> np.ndarray:
    med = np.median(stack, axis=0)
    mad = np.median(np.abs(stack - med), axis=0) * 1.4826
    keep = np.abs(stack - med) <= sigma * np.maximum(mad, 0.004)
    weights = keep.astype(np.float32)
    return np.sum(stack * weights, axis=0) / np.maximum(np.sum(weights, axis=0), 1)


def _soft_denoise(image: np.ndarray, amount: float = 0.12) -> np.ndarray:
    p = np.pad(image, 1, mode="reflect")
    low = (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:] + p[1:-1, :-2] +
           4 * p[1:-1, 1:-1] + p[1:-1, 2:] + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 12
    return (image * (1 - amount) + low * amount).astype(np.float32)


def wiener_deconvolution(image: np.ndarray, psf_sigma_px: float, regularization: float) -> np.ndarray:
    """Experimental Gaussian-PSF Wiener filter. Never enabled in default run."""
    if psf_sigma_px <= 0 or regularization <= 0:
        raise ValueError("PSF sigma and regularization must be positive")
    h, w = image.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    transfer = np.exp(-2 * np.pi**2 * psf_sigma_px**2 * (fx * fx + fy * fy))
    f = np.fft.fft2(image)
    restored = np.fft.ifft2(f * np.conj(transfer) / (transfer * transfer + regularization)).real
    return restored.astype(np.float32)


def reconstruct(observations: ObservationSequence, *, run_deconvolution: bool = False) -> ReconstructionResult:
    frames = observations.frames
    assessments = score_frames(frames, observations.frame_ids)
    accepted = [i for i, a in enumerate(assessments) if a.decision == "accepted"]
    rejected = [i for i, a in enumerate(assessments) if a.decision == "rejected"]
    if not accepted:
        raise ValueError("no frames accepted by quality rules")
    # Choose sharpest non-clipped candidate as reference; no oracle access.
    ref_idx = max(accepted, key=lambda i: assessments[i].components["edge_sharpness"])
    ref = frames[ref_idx]
    aligned_frames, alignments = [], []
    for i in accepted:
        if i == ref_idx:
            aligned_frames.append(ref.copy())
            alignments.append(Alignment(observations.frame_ids[i], observations.frame_ids[ref_idx],
                                        0, 0, 0, 1, 0, "high_confidence"))
            continue
        aligned, record = align_pair(ref, frames[i], observations.frame_ids[i], observations.frame_ids[ref_idx])
        alignments.append(record)
        if record.status == "high_confidence":
            aligned_frames.append(aligned)
        else:
            rejected.append(i)
            assessments[i] = type(assessments[i])(assessments[i].frame_id, assessments[i].components,
                                                   "rejected", ("alignment_low_confidence",),
                                                   assessments[i].score_version)
    if not aligned_frames:
        raise ValueError("all frame alignments failed")
    stack = np.stack(aligned_frames)
    half = max(1, len(stack) // 2)
    half_a = np.mean(stack[:half], axis=0).astype(np.float32)
    half_b = np.mean(stack[half:], axis=0).astype(np.float32) if len(stack) - half else half_a.copy()
    mean = np.mean(stack, axis=0).astype(np.float32)
    weighted = np.average(stack, axis=0, weights=np.ones(len(stack), dtype=np.float32)).astype(np.float32)
    median = np.median(stack, axis=0).astype(np.float32)
    robust = _sigma_clip_stack(stack)
    denoised = _soft_denoise(robust)
    baselines = {"ordinary_single": frames[0].copy(), "best_single": ref.copy(),
                 "registered_mean": mean, "weighted_mean": weighted, "median": median,
                 "sigma_clipped": robust, "sigma_clipped_denoised": denoised,
                 "half_stack_a": half_a, "half_stack_b": half_b}
    if run_deconvolution:
        baselines["experimental_wiener"] = wiener_deconvolution(denoised, 0.8, 0.025)
    ops = [{"type": "score", "version": assessments[0].score_version, "thresholds": {"highlight_clip": 0.02, "relative_limb_sharpness": 0.68, "relative_noise": 1.35}},
           {"type": "align", "version": ALIGNMENT_VERSION, "reference": observations.frame_ids[ref_idx], "method": "robust-Lucas-Kanade-rigid"},
           {"type": "stack", "version": RECONSTRUCTION_VERSION, "methods": ["mean", "weighted_mean", "median", "sigma_clipped"]},
           {"type": "denoise", "version": RECONSTRUCTION_VERSION, "method": "12-percent-local-low-pass-mix"}]
    if run_deconvolution:
        ops.append({"type": "deconvolution", "version": RECONSTRUCTION_VERSION, "psf": "Gaussian sigma=0.8px", "regularization": 0.025, "experimental": True})
    return ReconstructionResult(observations.fixture_id, observations.frame_ids[ref_idx],
                                [observations.frame_ids[i] for i in accepted if i not in rejected],
                                [observations.frame_ids[i] for i in sorted(set(rejected))],
                                assessments, alignments, baselines, ops,
                                warnings=["sub-pixel aligned outputs are not a super-resolution claim",
                                          "deconvolution is experimental and disabled by default"])
