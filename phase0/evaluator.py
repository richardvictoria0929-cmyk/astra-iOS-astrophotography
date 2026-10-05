"""Post-reconstruction evaluation. This is the only layer that accepts hidden truth."""

import numpy as np
from .config import METRIC_VERSION
from .metrics import (snr_proxy, edge_sharpness, mtf50_proxy, frc_resolution_proxy,
                      clipping_fraction, ringing_halo, seam_interpolation_proxy,
                      false_detail_indicators, reconstruction_error, registration_error)


def evaluate(observations, oracle, record, images):
    index = {fid: i for i, fid in enumerate(observations.frame_ids)}
    ref_i = index[record["reference_id"]]
    image_metrics = {}
    for name, image in images.items():
        if name.startswith("half_stack"):
            continue
        source_id = record.get("baseline_source_ids", {}).get(name, record["reference_id"])
        source_i = index[source_id]
        clean = oracle.clean_source_frames[source_i]
        center = (oracle.disk_center_xy[0] + float(oracle.true_transforms[source_i, 0]),
                  oracle.disk_center_xy[1] + float(oracle.true_transforms[source_i, 1]))
        image_metrics[name] = {
            "snr_proxy": snr_proxy(image, clean),
            "edge_sharpness": edge_sharpness(image, clean),
            "mtf50_proxy_cycles_per_pixel": mtf50_proxy(image, clean, center_xy=center,
                                                        radius_px=oracle.disk_radius_px),
            "clipping_fraction": clipping_fraction(image),
            "ringing_halo_peak": ringing_halo(image, clean),
            "seam_interpolation_proxy": seam_interpolation_proxy(image, clean),
            "reconstruction_error": reconstruction_error(image, clean),
            "false_detail": false_detail_indicators(image, clean),
        }
    best = image_metrics.get("best_single", {})
    stacked = image_metrics.get("sigma_clipped", {})
    denoised = image_metrics.get("sigma_clipped_denoised", {})
    snr_gain = stacked.get("snr_proxy", 0) / max(best.get("snr_proxy", 0), 1e-12)
    edge_ratio = denoised.get("mtf50_proxy_cycles_per_pixel", 0) / max(best.get("mtf50_proxy_cycles_per_pixel", 0), 1e-12)

    ref_id = record["reference_id"]
    index = {fid: i for i, fid in enumerate(observations.frame_ids)}
    ref_i = index[ref_id]
    estimated, expected, reg_records = [], [], []
    for item in record["alignments"]:
        if item["status"] != "high_confidence" or item["frame_id"] == ref_id:
            continue
        i = index[item["frame_id"]]
        # Ground-truth transform from frame i into the selected reference frame.
        truth = oracle.true_transforms[ref_i] - oracle.true_transforms[i]
        estimate = [item["dx"], item["dy"], item["rotation_deg"]]
        estimated.append(estimate)
        expected.append(truth.tolist())
        reg_records.append({"frame_id": item["frame_id"], "estimate": estimate, "truth_eval_only": truth.tolist(),
                            "residual": item["residual"], "confidence": item["confidence"]})
    if estimated:
        reg = registration_error(estimated, expected)
        # Correct RMS over both coordinate errors.
        delta = np.asarray(estimated)[:, :2] - np.asarray(expected)[:, :2]
        reg["rms_translation_px"] = float(np.sqrt(np.mean(delta * delta)))
    else:
        reg = {"rms_translation_px": None, "rotation_error_deg": None}

    expected_bad = set(oracle.expected_bad_indices)
    rejected = {index[fid] for fid in record["rejected_ids"]}
    tp = len(expected_bad & rejected)
    fn = len(expected_bad - rejected)
    fp = len(rejected - expected_bad)
    tn = len(observations.frame_ids) - len(expected_bad) - fp - fn
    rejection = {"true_positive": tp, "false_negative": fn, "false_positive": fp, "true_negative": tn,
                 "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1),
                 "false_rejection_rate_good": fp / max(len(observations.frame_ids) - len(expected_bad), 1),
                 "expected_bad_kinds_eval_only": {str(i): oracle.bad_frame_kinds[i] for i in sorted(expected_bad)}}
    required_bad = {i for i in expected_bad if oracle.bad_frame_kinds[i] in ("strong_blur", "highlight_clipped")}
    required_tp = len(required_bad & rejected)
    rejection["required_blur_or_clipping_recall"] = required_tp / max(len(required_bad), 1)
    rejection["required_blur_or_clipping_count"] = len(required_bad)
    rejection["abnormal_noise_recall"] = (sum(1 for i in expected_bad if oracle.bad_frame_kinds[i] == "abnormal_noise" and i in rejected) /
                                            max(sum(1 for i in expected_bad if oracle.bad_frame_kinds[i] == "abnormal_noise"), 1))
    rejection["recall_by_kind"] = {
        kind: (sum(1 for i in expected_bad if oracle.bad_frame_kinds[i] == kind and i in rejected) /
               max(sum(1 for i in expected_bad if oracle.bad_frame_kinds[i] == kind), 1))
        for kind in sorted(set(oracle.bad_frame_kinds)) if kind != "good"
    }
    frc = frc_resolution_proxy(images["half_stack_a"], images["half_stack_b"])
    truth_reference = oracle.clean_source_frames[ref_i]
    truth_ordinary = oracle.clean_source_frames[0]
    return {
        "fixture_id": observations.fixture_id,
        "metric_version": METRIC_VERSION,
        "algorithm_version": record["algorithm_version"],
        "source_count": len(observations.frame_ids),
        "accepted_count": len(record["accepted_ids"]),
        "rejected_count": len(record["rejected_ids"]),
        "runtime_seconds": None,
        "registration": {**reg, "evaluated_frame_count": len(estimated), "records": reg_records},
        "snr_proxy_improvement_vs_best_single": snr_gain,
        "mtf50_proxy_retention_vs_best_single": edge_ratio,
        "frc_resolution_proxy_cycles_per_pixel": frc,
        "frame_rejection": rejection,
        "image_metrics": image_metrics,
        "baseline_comparisons": {"ordinary_single": reconstruction_error(images["ordinary_single"], truth_ordinary),
                                  "best_single": reconstruction_error(images["best_single"], truth_reference),
                                  "registered_stack": reconstruction_error(images["sigma_clipped"], truth_reference),
                                  "stack_denoised": reconstruction_error(images["sigma_clipped_denoised"], truth_reference),
                                  "deconvolution_tested": "experimental_wiener" in images},
    }


def metric_dictionary():
    return {
        "metric_version": METRIC_VERSION,
        "registration_error": {"definition": "RMS of estimated minus known relative dx/dy", "units": "pixels", "better": "lower", "limits": "Synthetic transforms only; excludes low-confidence records; this evaluator-only metric is not available to reconstruction."},
        "snr_proxy": {"definition": "Mean clean lunar signal in truth-defined low-gradient ROI divided by RMSE to clean reference", "units": "ratio", "better": "higher", "limits": "Truth-referenced simulation proxy, not sensor SNR calibration."},
        "edge_sharpness": {"definition": "Mean image gradient on truth-selected lunar limb band", "units": "normalized intensity/pixel", "better": "higher only when noise/artifact metrics do not rise", "limits": "Noise also raises gradient."},
        "mtf50_proxy": {"definition": "First 0.5 crossing of Fourier magnitude of differentiated radial lunar limb edge-spread profile", "units": "cycles/pixel", "better": "higher", "limits": "Synthetic limb proxy; phase/illumination asymmetry and center/radius estimation matter."},
        "frc": {"definition": "First radial Fourier ring where half-stack correlation falls below 1/7", "units": "cycles/pixel", "better": "higher", "limits": "Relative consistency proxy, not absolute optical resolution certificate."},
        "clipping_fraction": {"definition": "Fraction at normalized floor <=0.002 or ceiling >=0.995", "units": "fraction", "better": "lower", "limits": "Thresholds model normalized synthetic samples."},
        "ringing_halo": {"definition": "Peak output overshoot beyond 5x5 local range of clean reference in limb band", "units": "normalized intensity", "better": "lower", "limits": "Truth-referenced proxy; does not detect every perceptual halo."},
        "seam_interpolation_proxy": {"definition": "Mean gradient in outer 3-pixel border divided by interior mean gradient", "units": "ratio", "better": "lower if crop support is unchanged", "limits": "Sensitive to scene content; only controlled fixture comparisons."},
        "false_detail": {"definition": "High-frequency output minus clean-reference energy relative to clean high-frequency energy", "units": "ratio and normalized RMSE", "better": "lower", "limits": "Evaluator-only simulation measure; cannot certify real lunar truth."},
        "reconstruction_error": {"definition": "RMSE and PSNR against noiseless sampled reference", "units": "normalized linear units / dB", "better": "RMSE lower, PSNR higher", "limits": "Only available for synthetic fixtures."},
        "rejection_accuracy": {"definition": "TP/FN/FP/TN versus injected bad-frame labels", "units": "counts, precision, recall, false rejection rate", "better": "higher recall/precision, lower false rejection", "limits": "Generator bad labels are hidden from the scorer."},
    }
