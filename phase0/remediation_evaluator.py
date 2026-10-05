"""Post-worker evaluator; consumes oracle only after reconstruction completes."""

import numpy as np
from .metrics import (snr_proxy, mtf50_proxy, clipping_fraction, ringing_halo,
                      seam_interpolation_proxy, false_detail_indicators,
                      reconstruction_error, registration_error)


METRIC_VERSION = "metrics-0.3"  # unchanged definitions; only stage reporting is new
CLASS_NAMES = ("strong_blur", "clipping", "large_motion", "abnormal_noise", "mixed")


def _image_metrics(image, clean, center, radius):
    return {
        "snr_proxy": snr_proxy(image, clean),
        "mtf50_proxy_cycles_per_pixel": mtf50_proxy(image, clean, center_xy=center, radius_px=radius),
        "clipping_fraction": clipping_fraction(image),
        "ringing_halo_peak": ringing_halo(image, clean),
        "seam_interpolation_proxy": seam_interpolation_proxy(image, clean),
        "reconstruction_error": reconstruction_error(image, clean),
        "false_detail": false_detail_indicators(image, clean),
    }


def evaluate_remediation(observations, oracle, record, images):
    frame_index = {fid: i for i, fid in enumerate(observations.frame_ids)}
    ref_i = frame_index[record["reference_id"]]
    clean = oracle.clean_source_frames[ref_i]
    center = (oracle.disk_center_xy[0] + float(oracle.true_transforms[ref_i, 0]),
              oracle.disk_center_xy[1] + float(oracle.true_transforms[ref_i, 1]))
    per_image = {}
    metric_names = ("best_single", "registered_mean", "weighted_mean", "median",
                    "sigma_clipped", "sigma_clipped_denoised", "fourier_mean",
                    "fourier_weighted_mean", "fourier_median", "fourier_sigma_clipped",
                    "fourier_sigma_clipped_denoised", "fourier_rigid_mean",
                    "fourier_rigid_weighted_mean", "fourier_rigid_median",
                    "fourier_rigid_sigma_clipped", "fourier_rigid_sigma_clipped_denoised")
    for name in metric_names:
        per_image[name] = _image_metrics(images[name], clean, center, oracle.disk_radius_px)

    def aligned_stats(stack):
        vals = np.asarray([mtf50_proxy(x, clean, center_xy=center,
                                       radius_px=oracle.disk_radius_px) for x in stack])
        return {"count": int(len(vals)), "mean_cycles_per_pixel": float(np.mean(vals)),
                "median_cycles_per_pixel": float(np.median(vals)),
                "minimum_cycles_per_pixel": float(np.min(vals))}

    aligned_stats_by_method = {
        "bilinear": aligned_stats(images["candidate_bilinear_aligned_stack"]),
        "bicubic": aligned_stats(images["stage_aligned_stack"]),
        "fourier_translation": aligned_stats(images["candidate_fourier_aligned_stack"]),
        "fourier_rigid": aligned_stats(images["candidate_fourier_rigid_aligned_stack"]),
    }
    aligned_mtf = np.asarray([mtf50_proxy(x, clean, center_xy=center,
                                          radius_px=oracle.disk_radius_px) for x in images["stage_aligned_stack"]])
    fourier_aligned_mtf = np.asarray([mtf50_proxy(x, clean, center_xy=center,
                                                  radius_px=oracle.disk_radius_px)
                                      for x in images["candidate_fourier_aligned_stack"]])
    rigid_aligned_mtf = np.asarray([mtf50_proxy(x, clean, center_xy=center,
                                                radius_px=oracle.disk_radius_px)
                                    for x in images["candidate_fourier_rigid_aligned_stack"]])
    stage_mtf = {
        "A_best_source": per_image["best_single"]["mtf50_proxy_cycles_per_pixel"],
        "B_aligned_individual_sources": aligned_stats_by_method,
        "C_aligned_mean_stack": per_image["registered_mean"]["mtf50_proxy_cycles_per_pixel"],
        "D_quality_weighted_stack": per_image["weighted_mean"]["mtf50_proxy_cycles_per_pixel"],
        "E_median_stack": per_image["median"]["mtf50_proxy_cycles_per_pixel"],
        "F_sigma_clipped_stack": per_image["sigma_clipped"]["mtf50_proxy_cycles_per_pixel"],
        "G_denoised_stack": per_image["sigma_clipped_denoised"]["mtf50_proxy_cycles_per_pixel"],
    }
    best_mtf = max(stage_mtf["A_best_source"], 1e-12)
    for method, values in stage_mtf["B_aligned_individual_sources"].items():
        values["mean_retention_vs_best"] = values["mean_cycles_per_pixel"] / best_mtf
        values["median_retention_vs_best"] = values["median_cycles_per_pixel"] / best_mtf
        values["minimum_retention_vs_best"] = values["minimum_cycles_per_pixel"] / best_mtf
    for key, value in list(stage_mtf.items()):
        if key != "B_aligned_individual_sources":
            stage_mtf[key] = {"cycles_per_pixel": value, "retention_vs_best": value / best_mtf}
    stage_mtf["fourier_translation_pipeline"] = {
        "C_mean": {"cycles_per_pixel": per_image["fourier_mean"]["mtf50_proxy_cycles_per_pixel"],
                   "retention_vs_best": per_image["fourier_mean"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "D_weighted": {"cycles_per_pixel": per_image["fourier_weighted_mean"]["mtf50_proxy_cycles_per_pixel"],
                       "retention_vs_best": per_image["fourier_weighted_mean"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "E_median": {"cycles_per_pixel": per_image["fourier_median"]["mtf50_proxy_cycles_per_pixel"],
                     "retention_vs_best": per_image["fourier_median"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "F_sigma_clipped": {"cycles_per_pixel": per_image["fourier_sigma_clipped"]["mtf50_proxy_cycles_per_pixel"],
                             "retention_vs_best": per_image["fourier_sigma_clipped"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "G_denoised": {"cycles_per_pixel": per_image["fourier_sigma_clipped_denoised"]["mtf50_proxy_cycles_per_pixel"],
                       "retention_vs_best": per_image["fourier_sigma_clipped_denoised"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "B_aligned_individual_sources": {**aligned_stats_by_method["fourier_translation"],
                                          "mean_retention_vs_best": float(np.mean(fourier_aligned_mtf)) / best_mtf,
                                          "median_retention_vs_best": float(np.median(fourier_aligned_mtf)) / best_mtf,
                                          "minimum_retention_vs_best": float(np.min(fourier_aligned_mtf)) / best_mtf},
    }
    stage_mtf["fourier_rigid_pipeline"] = {
        "C_mean": {"cycles_per_pixel": per_image["fourier_rigid_mean"]["mtf50_proxy_cycles_per_pixel"],
                   "retention_vs_best": per_image["fourier_rigid_mean"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "D_weighted": {"cycles_per_pixel": per_image["fourier_rigid_weighted_mean"]["mtf50_proxy_cycles_per_pixel"],
                       "retention_vs_best": per_image["fourier_rigid_weighted_mean"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "E_median": {"cycles_per_pixel": per_image["fourier_rigid_median"]["mtf50_proxy_cycles_per_pixel"],
                     "retention_vs_best": per_image["fourier_rigid_median"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "F_sigma_clipped": {"cycles_per_pixel": per_image["fourier_rigid_sigma_clipped"]["mtf50_proxy_cycles_per_pixel"],
                             "retention_vs_best": per_image["fourier_rigid_sigma_clipped"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "G_denoised": {"cycles_per_pixel": per_image["fourier_rigid_sigma_clipped_denoised"]["mtf50_proxy_cycles_per_pixel"],
                       "retention_vs_best": per_image["fourier_rigid_sigma_clipped_denoised"]["mtf50_proxy_cycles_per_pixel"] / best_mtf},
        "B_aligned_individual_sources": {**aligned_stats_by_method["fourier_rigid"],
                                          "mean_retention_vs_best": float(np.mean(rigid_aligned_mtf)) / best_mtf,
                                          "median_retention_vs_best": float(np.median(rigid_aligned_mtf)) / best_mtf,
                                          "minimum_retention_vs_best": float(np.min(rigid_aligned_mtf)) / best_mtf},
    }

    accepted = set(record["accepted_ids"])
    rejected = set(record["rejected_ids"])
    class_results = {}
    for class_name in CLASS_NAMES:
        positive = {i for i, tags in enumerate(oracle.failure_tags) if class_name in tags}
        negative = set(range(len(oracle.failure_tags))) - positive
        tp = sum(observations.frame_ids[i] in rejected for i in positive)
        fn = len(positive) - tp
        fp = sum(observations.frame_ids[i] in rejected for i in negative)
        tn = len(negative) - fp
        clean_positive = {i for i, tags in enumerate(oracle.failure_tags) if not tags}
        good_false = sum(observations.frame_ids[i] in rejected for i in clean_positive)
        class_results[class_name] = {
            "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "recall": tp / max(tp + fn, 1),
            "precision": tp / max(tp + fp, 1),
            "false_rejection_rate_one_vs_rest": fp / max(fp + tn, 1),
            "good_frames_rejected": good_false,
            "good_frame_false_rejection_rate": good_false / max(len(clean_positive), 1),
            "positive_count": len(positive),
        }
    reasons = {}
    for item in record["assessments"]:
        for reason in item["reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1

    reg_est, reg_truth = [], []
    alignments = []
    for item in record["alignments"]:
        if item["frame_id"] not in accepted or item["frame_id"] == record["reference_id"]:
            continue
        i = frame_index[item["frame_id"]]
        truth = oracle.true_transforms[ref_i] - oracle.true_transforms[i]
        reg_est.append([item["dx"], item["dy"], item["rotation_deg"]])
        reg_truth.append(truth.tolist())
        alignments.append({"frame_id": item["frame_id"], "estimate": reg_est[-1],
                           "truth_eval_only": reg_truth[-1], "residual": item["residual"],
                           "confidence": item["confidence"]})
    if reg_est:
        reg = registration_error(reg_est, reg_truth)
        delta = np.asarray(reg_est)[:, :2] - np.asarray(reg_truth)[:, :2]
        reg["rms_translation_px"] = float(np.sqrt(np.mean(delta * delta)))
    else:
        reg = {"rms_translation_px": None, "rotation_error_deg": None}
    denominator = max(len(accepted) - 1, 1)
    reg["evaluated_frame_count"] = len(reg_est)
    reg["accepted_nonreference_count"] = denominator
    reg["valid_coverage_fraction"] = len(reg_est) / denominator
    clean_frames = [i for i, tags in enumerate(oracle.failure_tags) if not tags]
    all_rejected = [observations.frame_ids[i] for i in range(len(oracle.failure_tags))
                    if observations.frame_ids[i] in rejected]
    return {
        "fixture_id": observations.fixture_id,
        "metric_version": METRIC_VERSION,
        "quality_version": record["quality_version"],
        "alignment_version": record["alignment_version"],
        "reconstruction_version": record["algorithm_version"],
        "source_count": len(observations.frame_ids),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "runtime_seconds": None,
        "registration": {**reg, "records": alignments},
        "snr_proxy_gain_sigma_vs_best": per_image["sigma_clipped"]["snr_proxy"] /
                                        max(per_image["best_single"]["snr_proxy"], 1e-12),
        "mtf50_retention_denoised_vs_best": stage_mtf["G_denoised_stack"]["retention_vs_best"],
        "stage_by_stage_edge": stage_mtf,
        "image_metrics": per_image,
        "frame_rejection_by_class": class_results,
        "good_frame_false_rejection_rate": (sum(observations.frame_ids[i] in rejected for i in clean_frames) /
                                              max(len(clean_frames), 1)),
        "rejected_reason_counts": reasons,
        "rejected_frame_ids": all_rejected,
        "clean_frame_count": len(clean_frames),
    }
