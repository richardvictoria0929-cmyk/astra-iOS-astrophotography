"""Create frozen Phase 0 fixtures, run isolated reconstruction, evaluate, and report."""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from .config import DEFAULT_CONFIG, PROVISIONAL_GATES, GENERATOR_VERSION, METRIC_VERSION, QUALITY_VERSION, ALIGNMENT_VERSION, RECONSTRUCTION_VERSION
from .generator import freeze_fixture
from .fixtures import load_fixture_protocol, load_observations, load_evaluation_oracle, persist_golden_fixture
from .runner import run_reconstruction_isolated
from .evaluator import evaluate, metric_dictionary


SCENARIOS = [
    ("gate-noise-16-holdout", {**DEFAULT_CONFIG, "seed": 9613, "frame_count": 16, "inject_outliers": False}),
    ("outlier-stress-24-holdout", {**DEFAULT_CONFIG, "seed": 7381, "frame_count": 24, "inject_outliers": True,
                           "read_noise_sigma": 0.006, "shot_scale": 0.018}),
    ("rotation-stress-20-holdout", {**DEFAULT_CONFIG, "seed": 5287, "frame_count": 20, "inject_outliers": True,
                            "rotation_span_deg": 0.9, "translation_span_px": 1.8,
                            "optical_psf_sigma_px": 0.7, "read_noise_sigma": 0.005}),
]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="phase0/results/run-001")
    parser.add_argument("--deconvolution", action="store_true", help="run experimental Wiener branch separately")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    out = Path(args.output)
    if not out.is_absolute():
        out = Path.cwd() / out
    fixtures_root = root / "fixtures"
    reports_root = root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    results = []
    for fixture_id, cfg in SCENARIOS:
        # Fixture is deterministic; metadata plus checksums freeze the generator result.
        freeze_cfg = dict(cfg)
        inject = bool(freeze_cfg.pop("inject_outliers"))
        # Current frozen fixture generator's default includes outliers; explicitly remove
        # seeded bad labels in gate-noise fixture after generation via a separate test call.
        effective_cfg = {**freeze_cfg, "inject_outliers": inject}
        fixture_protocol_path = fixtures_root / fixture_id / "fixture.json"
        if fixture_protocol_path.exists():
            protocol = json.loads(fixture_protocol_path.read_text(encoding="utf-8"))
            if protocol["parameters"] != effective_cfg:
                raise ValueError(f"frozen fixture {fixture_id} parameters differ; use a new fixture ID")
        else:
            protocol = freeze_fixture(fixtures_root, effective_cfg, fixture_id=fixture_id)
        obs, protocol = load_observations(fixtures_root, fixture_id)
        record, images, runtime = run_reconstruction_isolated(obs, deconvolution=args.deconvolution)
        oracle = load_evaluation_oracle(fixtures_root, fixture_id)
        report = evaluate(obs, oracle, record, images)
        report["runtime_seconds"] = runtime
        report["reconstruction_record"] = record
        golden = persist_golden_fixture(fixtures_root, fixture_id, images, report,
                                        algorithm_versions={"quality": QUALITY_VERSION,
                                                            "alignment": ALIGNMENT_VERSION,
                                                            "reconstruction": RECONSTRUCTION_VERSION},
                                        python_version=platform.python_version())
        protocol = json.loads((fixtures_root / fixture_id / "fixture.json").read_text(encoding="utf-8"))
        report["fixture_protocol"] = protocol
        report["golden_reference"] = golden
        (out / f"{fixture_id}-metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        results.append(report)

    primary = next(r for r in results if r["fixture_id"] == "gate-noise-16-holdout")
    stress = next(r for r in results if r["fixture_id"] == "outlier-stress-24-holdout")
    registration_ok = all(r["registration"]["rms_translation_px"] is not None and
                          r["registration"]["rms_translation_px"] <= PROVISIONAL_GATES["registration_rms_px"]
                          for r in results)
    registration_valid = all(r["registration"]["evaluated_frame_count"] >=
                             PROVISIONAL_GATES["registration_valid_fraction"] * max(r["accepted_count"] - 1, 1)
                             for r in results)
    snr_ok = primary["snr_proxy_improvement_vs_best_single"] >= PROVISIONAL_GATES["snr_proxy_improvement_16_frames"]
    edge_ok = primary["mtf50_proxy_retention_vs_best_single"] >= 1 - PROVISIONAL_GATES["edge_metric_loss_fraction"]
    reject_ok = stress["frame_rejection"]["required_blur_or_clipping_recall"] >= PROVISIONAL_GATES["bad_frame_recall"]
    # Structural lineage audit: worker output lists IDs and all operations; output hashes are attached below.
    def integrity_valid(r):
        record = r["reconstruction_record"]
        ids = set(record["accepted_ids"] + record["rejected_ids"])
        decisions = {a["frame_id"]: a["decision"] for a in record["assessments"]}
        decisions_match = (all(decisions.get(fid) == "accepted" for fid in record["accepted_ids"]) and
                           all(decisions.get(fid) == "rejected" for fid in record["rejected_ids"]) and
                           len(decisions) == r["source_count"])
        return (bool(record["operations"]) and len(ids) == r["source_count"] and
                decisions_match and
                len(record["source_hashes_sha256"]) == r["source_count"] and
                all(len(x) == 64 for x in record["source_hashes_sha256"].values()) and
                all(len(x) == 64 for x in record["output_hashes_sha256"].values()) and
                len(record["lineage_edges"]) == len(record["output_hashes_sha256"]) and
                all(edge["parent_source_ids"] and len(edge["child_hash_sha256"]) == 64 for edge in record["lineage_edges"]) and
                all(op.get("version") and op.get("type") for op in record["operations"]))
    integrity_ok = all(integrity_valid(r) for r in results)
    gates = {
        "registration_rms_le_0.25px": {"pass": registration_ok, "value_by_fixture": {r["fixture_id"]: r["registration"]["rms_translation_px"] for r in results}},
        "registration_valid_fraction_ge_0.90": {"pass": registration_valid, "evaluated_fraction_by_fixture": {r["fixture_id"]: r["registration"]["evaluated_frame_count"] / max(r["accepted_count"] - 1, 1) for r in results}},
        "snr_proxy_gain_16_frames_ge_2.5": {"pass": snr_ok, "value": primary["snr_proxy_improvement_vs_best_single"]},
        "edge_proxy_loss_le_5_percent": {"pass": edge_ok, "retention": primary["mtf50_proxy_retention_vs_best_single"]},
        "seeded_blur_or_clipping_recall_ge_0.90": {"pass": reject_ok, "value": stress["frame_rejection"]["required_blur_or_clipping_recall"]},
        "integrity_records_present": {"pass": integrity_ok},
    }
    status = "PASS" if all(v["pass"] for v in gates.values()) else "FAIL"
    run = {"run_id": out.name, "created_utc": datetime.now(timezone.utc).isoformat(),
           "status": status, "python": sys.version, "platform": platform.platform(),
           "packages": {name: importlib.metadata.version(name) for name in ("numpy", "Pillow")},
           "generator_version": GENERATOR_VERSION, "metric_version": METRIC_VERSION,
           "quality_version": QUALITY_VERSION, "alignment_version": ALIGNMENT_VERSION,
           "reconstruction_version": RECONSTRUCTION_VERSION,
           "scenarios": [r["fixture_id"] for r in results], "gates": gates,
           "deconvolution_requested": args.deconvolution}
    (out / "run-summary.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (out / "metric-definitions.json").write_text(json.dumps(metric_dictionary(), indent=2), encoding="utf-8")
    report_path = out / "phase0-report.md"
    lines = ["# ASTRA Phase 0 Experiment Report", "", f"**Status:** {status}",
             f"**Run:** `{out.name}` · **UTC:** {run['created_utc']}",
             f"**Environment:** Python {platform.python_version()}, NumPy {run['packages']['numpy']}, Pillow {run['packages']['Pillow']}", "",
             "## A. Recovered workspace state", "", "Before this run the workspace contained only the approved architecture/roadmap. No Phase 0 code, fixtures, experiments, reports, or tests existed.", "",
             "## B. Files created / modified", "", "The Phase 0 package contains generator, observation/result contracts, reconstruction/quality modules, evaluator metrics, isolated worker/runner, tests, frozen fixtures, and this report. See `phase0/`.", "",
             "## C. Experiment design", "", "Synthetic lunar-like scenes contain a high-contrast limb, broad gradients, crater-like basins/rims, fine stochastic texture and smooth regions. Frames vary by translations, small rotations, exposure, Poisson-like shot noise and Gaussian read noise. Stress sequences include injected blur, clipping/motion and abnormal noise. Baselines include ordinary single, selected best single, registered mean/weighted mean/median/sigma-clipped stack, stack plus conservative denoising, and optional experimental Wiener output.", "",
             "## D. Ground-truth isolation", "", "Fixture observations and evaluator-private oracle are stored separately. Reconstruction runs in a fresh child process with a temporary observation-only NPZ, no oracle path/object/keys/environment, and no import of generator/evaluator modules. Hidden transforms and clean references are read by the parent evaluator only after the child returns. This is a code/data interface boundary, not an OS sandbox against intentionally hostile Python code.", "",
             "## E. Algorithms tested", "", "Frame score components: highlight clipping, shadow-floor fraction, contrast, gradient sharpness, estimated lunar-limb sharpness, Laplacian variance, MAD high-pass noise and exposure. Registration: robust iterative Lucas–Kanade translation plus small rotation; phase-correlation translation is separately unit-tested. Stacks: mean, equal weighted mean, median and sigma-clipped mean. Denoising: 12% local low-pass mix. Experimental Wiener deconvolution is off unless explicitly requested.", "",
             "## F. Metrics", "", "Machine-readable definitions are in `metric-definitions.json`. They cover registration error, truth-referenced SNR proxy, limb-gradient sharpness, MTF50 proxy, half-map FRC proxy, clipping, ringing/halo, border seam/interpolation proxy, unsupported high-frequency energy, reconstruction RMSE/PSNR and rejection accuracy. Several are synthetic-only proxies and are not sensor calibration or proof of lunar truth.", "",
             "## G. Quantitative results", "", "| Fixture | Sources | Accepted | Rejected | SNR gain vs best | MTF50 retention | Registration RMS px | FRC proxy c/px | Runtime s |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['fixture_id']} | {r['source_count']} | {r['accepted_count']} | {r['rejected_count']} | {r['snr_proxy_improvement_vs_best_single']:.3f} | {r['mtf50_proxy_retention_vs_best_single']:.3f} | {r['registration']['rms_translation_px'] if r['registration']['rms_translation_px'] is not None else 'n/a'} | {r['frc_resolution_proxy_cycles_per_pixel']:.3f} | {r['runtime_seconds']:.2f} |")
    lines += ["", "Detailed per-image metrics and all failed comparisons are in the fixture metrics JSON files.", "",
              "## H. Bad-frame rejection results", "", f"Outlier stress: TP={stress['frame_rejection']['true_positive']}, FN={stress['frame_rejection']['false_negative']}, FP={stress['frame_rejection']['false_positive']}, TN={stress['frame_rejection']['true_negative']}, overall injected-outlier recall={stress['frame_rejection']['recall']:.3f}, blur/clipping recall used for the provisional gate={stress['frame_rejection']['required_blur_or_clipping_recall']:.3f}, abnormal-noise recall={stress['frame_rejection']['abnormal_noise_recall']:.3f}, false rejection rate of good frames={stress['frame_rejection']['false_rejection_rate_good']:.3f}.", "",
              "## I. Artifact / false-detail findings", "", "See each fixture's ringing/halo, seam/interpolation and unsupported high-frequency metrics. The metrics are warning indicators, not a universal artifact detector. Deconvolution was not included unless requested; it remains experimental.", "",
              "## J. Optical information ceiling assessment", "", "The simulation's clean scene is an evaluator oracle, not captured astronomical evidence. Any lower error or higher SNR proxy establishes recovery only within the simulator's sampled bandwidth/PSF/noise model. No claim of exceeding optical/sensor sampling or of recovered real lunar craters follows. Upscaling and sharpness are not accepted as resolution evidence.", "",
              "## K. Golden fixtures created", "", "| Fixture ID | Use | Seed | Input/oracle hashes |", "|---|---|---:|---|"]
    for r in results:
        p = r["fixture_protocol"]
        lines.append(f"| {r['fixture_id']} | deterministic; see generation parameters in `phase0/fixtures/{r['fixture_id']}/fixture.json` | {p['seed']} | `{p['sha256_observations'][:12]}` / `{p['sha256_oracle'][:12]}` |")
    lines += ["", "## L. Provisional gate evaluation", "", "| Gate | Result | Evidence |", "|---|---|---|"]
    for name, value in gates.items():
        lines.append(f"| {name} | {'PASS' if value['pass'] else 'FAIL'} | `{json.dumps(value, separators=(',', ':'))}` |")
    lines += ["", "## M. Phase 0 status", "", f"**{status}**", "", "## N. Limitations", "", "Synthetic lunar morphology and Gaussian/Poisson-like noise are approximations. Registration and quality thresholds need broader parameter sweeps and independently reviewed fixtures. FRC/MTF and artifact proxies are limited by synthetic limb, masks, interpolation and finite image dimensions. There is no iPhone camera/RAW/thermal evidence in Phase 0. Ground-truth isolation is architectural/process-level, not a security sandbox.", "", "## O. Recommended next action", "", ("Recommend Phase 1 review only; do not begin Phase 1 automatically." if status == "PASS" else "Do not proceed to Phase 1. Review failed gates and evidence below; decide whether to improve definitions, algorithm or fixture coverage. Thresholds were not changed."), ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "report": str(report_path), "summary": str(out / "run-summary.json"), "gates": gates}, indent=2))


if __name__ == "__main__":
    main()
