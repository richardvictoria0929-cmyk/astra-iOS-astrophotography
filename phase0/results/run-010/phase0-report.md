# ASTRA Phase 0 Experiment Report

**Status:** FAIL
**Run:** `run-010` · **UTC:** 2026-10-05T20:12:35.563592+00:00
**Environment:** Python 3.12.14, NumPy 2.3.5, Pillow 12.3.0

## A. Recovered workspace state

Before this run the workspace contained only the approved architecture/roadmap. No Phase 0 code, fixtures, experiments, reports, or tests existed.

## B. Files created / modified

The Phase 0 package contains generator, observation/result contracts, reconstruction/quality modules, evaluator metrics, isolated worker/runner, tests, frozen fixtures, and this report. See `phase0/`.

## C. Experiment design

Synthetic lunar-like scenes contain a high-contrast limb, broad gradients, crater-like basins/rims, fine stochastic texture and smooth regions. Frames vary by translations, small rotations, exposure, Poisson-like shot noise and Gaussian read noise. Stress sequences include injected blur, clipping/motion and abnormal noise. Baselines include ordinary single, selected best single, registered mean/weighted mean/median/sigma-clipped stack, stack plus conservative denoising, and optional experimental Wiener output.

## D. Ground-truth isolation

Fixture observations and evaluator-private oracle are stored separately. Reconstruction runs in a fresh child process with a temporary observation-only NPZ, no oracle path/object/keys/environment, and no import of generator/evaluator modules. Hidden transforms and clean references are read by the parent evaluator only after the child returns. This is a code/data interface boundary, not an OS sandbox against intentionally hostile Python code.

## E. Algorithms tested

Frame score components: highlight clipping, shadow-floor fraction, contrast, gradient sharpness, estimated lunar-limb sharpness, Laplacian variance, MAD high-pass noise and exposure. Registration: robust iterative Lucas–Kanade translation plus small rotation; phase-correlation translation is separately unit-tested. Stacks: mean, equal weighted mean, median and sigma-clipped mean. Denoising: 12% local low-pass mix. Experimental Wiener deconvolution is off unless explicitly requested.

## F. Metrics

Machine-readable definitions are in `metric-definitions.json`. They cover registration error, truth-referenced SNR proxy, limb-gradient sharpness, MTF50 proxy, half-map FRC proxy, clipping, ringing/halo, border seam/interpolation proxy, unsupported high-frequency energy, reconstruction RMSE/PSNR and rejection accuracy. Several are synthetic-only proxies and are not sensor calibration or proof of lunar truth.

## G. Quantitative results

| Fixture | Sources | Accepted | Rejected | SNR gain vs best | MTF50 retention | Registration RMS px | FRC proxy c/px | Runtime s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gate-noise-16-holdout | 16 | 16 | 0 | 3.171 | 0.903 | 0.031100318825746345 | 0.354 | 1.17 |
| outlier-stress-24-holdout | 24 | 23 | 1 | 19.273 | 1.000 | 0.08474260534703841 | 0.375 | 1.67 |
| rotation-stress-20-holdout | 20 | 19 | 1 | 20.280 | 0.900 | 0.0843283693616047 | 0.333 | 1.39 |

Detailed per-image metrics and all failed comparisons are in the fixture metrics JSON files.

## H. Bad-frame rejection results

Outlier stress: TP=1, FN=2, FP=0, TN=19, overall injected-outlier recall=0.333, blur/clipping recall used for the provisional gate=0.000, abnormal-noise recall=1.000, false rejection rate of good frames=0.000.

## I. Artifact / false-detail findings

See each fixture's ringing/halo, seam/interpolation and unsupported high-frequency metrics. The metrics are warning indicators, not a universal artifact detector. Deconvolution was not included unless requested; it remains experimental.

## J. Optical information ceiling assessment

The simulation's clean scene is an evaluator oracle, not captured astronomical evidence. Any lower error or higher SNR proxy establishes recovery only within the simulator's sampled bandwidth/PSF/noise model. No claim of exceeding optical/sensor sampling or of recovered real lunar craters follows. Upscaling and sharpness are not accepted as resolution evidence.

## K. Golden fixtures created

| Fixture ID | Use | Seed | Input/oracle hashes |
|---|---|---:|---|
| gate-noise-16-holdout | deterministic; see generation parameters in `phase0/fixtures/gate-noise-16-holdout/fixture.json` | 9613 | `f2325a9a507f` / `dedbbc8830b9` |
| outlier-stress-24-holdout | deterministic; see generation parameters in `phase0/fixtures/outlier-stress-24-holdout/fixture.json` | 7381 | `68d74c357540` / `485795d95761` |
| rotation-stress-20-holdout | deterministic; see generation parameters in `phase0/fixtures/rotation-stress-20-holdout/fixture.json` | 5287 | `ff6851d9259b` / `52b009d09cb8` |

## L. Provisional gate evaluation

| Gate | Result | Evidence |
|---|---|---|
| registration_rms_le_0.25px | PASS | `{"pass":true,"value_by_fixture":{"gate-noise-16-holdout":0.031100318825746345,"outlier-stress-24-holdout":0.08474260534703841,"rotation-stress-20-holdout":0.0843283693616047}}` |
| registration_valid_fraction_ge_0.90 | PASS | `{"pass":true,"evaluated_fraction_by_fixture":{"gate-noise-16-holdout":1.0,"outlier-stress-24-holdout":1.0,"rotation-stress-20-holdout":1.0}}` |
| snr_proxy_gain_16_frames_ge_2.5 | PASS | `{"pass":true,"value":3.170750657514131}` |
| edge_proxy_loss_le_5_percent | FAIL | `{"pass":false,"retention":0.9032258064516129}` |
| seeded_blur_or_clipping_recall_ge_0.90 | FAIL | `{"pass":false,"value":0.0}` |
| integrity_records_present | PASS | `{"pass":true}` |

## M. Phase 0 status

**FAIL**

## N. Limitations

Synthetic lunar morphology and Gaussian/Poisson-like noise are approximations. Registration and quality thresholds need broader parameter sweeps and independently reviewed fixtures. FRC/MTF and artifact proxies are limited by synthetic limb, masks, interpolation and finite image dimensions. There is no iPhone camera/RAW/thermal evidence in Phase 0. Ground-truth isolation is architectural/process-level, not a security sandbox.

## O. Recommended next action

Do not proceed to Phase 1. Review failed gates and evidence below; decide whether to improve definitions, algorithm or fixture coverage. Thresholds were not changed.
