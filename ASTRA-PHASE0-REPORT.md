# ASTRA Phase 0 — Scientific / Computational Feasibility Report

**Final status: FAIL**  
**Final baseline run:** `run-010`  
**Deconvolution experiment:** `run-011`  
**Current versions:** generator `lunar-sim-0.2`; metrics `metrics-0.3`; quality `quality-0.2`; alignment `align-0.2`; reconstruction `reconstruct-0.3`.  
**Scope:** Offline synthetic feasibility only. No Swift, SwiftUI, AVFoundation, Xcode project, or Phase 1 work was started.

## A. RECOVERED WORKSPACE STATE

Before Phase 0 work, the workspace contained only the approved product architecture and MVP roadmap, [ASTRA-Technical-Architecture-and-MVP-Roadmap.md](ASTRA-Technical-Architecture-and-MVP-Roadmap.md). There were no Python files, simulations, lunar generators, algorithms, fixtures, metric tools, experiment runners, reports or tests. Therefore there was no earlier Phase 0 result to mark as executed or verified.

At report time:

| State | Components |
|---|---|
| **IMPLEMENTED** | Synthetic lunar-like generator; observed/oracle data separation; frame scoring; translation/rotation registration; mean, weighted mean, median and sigma-clipped stacks; deterministic denoising; experimental Wiener deconvolution; metric/evaluation layer; isolated worker/runner; fixture freezing and golden output writing; JSON/Markdown report generation. |
| **EXECUTED** | Five unit tests; exploratory runs `run-001` and `run-002`; held-out experiments `run-003`–`run-010`; experimental Wiener branch in `run-004`, `run-009` and `run-011`. |
| **VERIFIED** | Final test suite: **5/5 passed**. Final held-out run `run-010`: registration, SNR-proxy and integrity gates passed; edge-retention and required blur/clipping rejection gates failed. |
| **FAILED** | Phase 0 provisional gate as a whole. The required blur/clipping recall was 0/2 on each held-out outlier fixture, and the 16-frame MTF50 proxy retention was 90.3% against a required 95%. |
| **NOT EXECUTED** | iPhone capture, real Moon sequences, a sensor-specific PSF/noise study, atmospheric seeing, a physical optical-resolution study, native Swift/Metal parity and any Phase 1 work. |
| **NOT VERIFIED** | Whether these synthetic results generalize to iPhone 14 Pro Max data or real lunar surface detail; whether the simulator is an adequate model of any specific iPhone lens/sensor pipeline. |

## B. FILES CREATED / MODIFIED

### Workspace-level files

- [ASTRA-Technical-Architecture-and-MVP-Roadmap.md](ASTRA-Technical-Architecture-and-MVP-Roadmap.md) — added the explicit optical information ceiling principle requested for Phase 0.
- [ASTRA-PHASE0-REPORT.md](ASTRA-PHASE0-REPORT.md) — this final report.

### Phase 0 source and documentation

- `phase0/README.md` — purpose, run commands, package layout and isolation limitation.
- `phase0/__init__.py` — package version.
- `phase0/config.py` — versions, provisional gates and default simulation settings.
- `phase0/types.py` — public observation/result contracts without hidden truth fields.
- `phase0/generator.py` — synthetic scene and sequence generator; evaluator-only oracle; frozen fixture writer.
- `phase0/quality.py` — interpretable frame-quality components and versioned decisions.
- `phase0/algorithms.py` — phase-correlation helper, Lucas–Kanade rigid alignment, stacks, denoiser and optional Wiener deconvolution.
- `phase0/metrics.py` — metric calculations.
- `phase0/evaluator.py` — post-reconstruction truth evaluation and metric definitions.
- `phase0/fixtures.py` — observation-only/oracle-only fixture loaders and golden output management.
- `phase0/worker.py` — child-process reconstruction entry point; accepts observations only.
- `phase0/runner.py` — observation-only process launch, output loading and worker failure capture.
- `phase0/run_experiment.py` — scenarios, gate evaluation and machine-readable/human-readable run report generation.
- `phase0/tests/test_phase0.py` — five deterministic, interface, registration, worker, and deconvolution tests.

### Generated artifacts

- `phase0/fixtures/` — three original development fixtures plus three frozen held-out fixtures. Each has `observed/frames.npz`, `evaluator-private/oracle.npz`, `fixture.json`, and held-out golden reference outputs/metrics under versioned `golden-*` folders.
- `phase0/results/run-001/` through `run-011/` — per-fixture metric JSON, run summaries, metric definitions and generated reports. Failed and exploratory runs are retained; none were overwritten.
- `phase0/.tmp/` — temporary observation-only child-process inputs and test scratch space; it is cleaned up after a normal run.

## C. EXPERIMENT DESIGN

The generator creates a 4× supersampled, 96×96-pixel lunar-like field with a disk limb, broad illumination gradients, smooth low-gradient regions, crater-like basins/rims, and band-limited fine texture. A shared scene is rendered into a sequence with controlled x/y translations, small rotations, exposure variation, blur, clipping, and noise. Parameters and seed are fixed in each fixture manifest.

Noise is an explicit approximation: Poisson-like sampling is performed as `Poisson(max(image,0) / shot_scale) * shot_scale`; independent Gaussian read noise is then added; samples are clipped to [0,1]. It is not a calibrated iPhone photon/read-noise model. Blur is a Gaussian PSF in the Fourier domain; an injected motion/defocus-like blur is represented by an additional broad Gaussian, not a full physical motion kernel. Rotations and translations are resampled with bilinear interpolation. Exposure variation is multiplicative; clipping is a hard [0,1] clip. The simulation does not include Bayer mosaics, demosaicing, lens distortion, rolling shutter, OIS, Apple multi-frame fusion, atmospheric turbulence, variable seeing, or real lunar photometry.

Held-out fixtures:

| Fixture | Purpose | Seed | Sequence | Injected failures |
|---|---|---:|---:|---|
| `gate-noise-16-holdout` | Primary 16-frame stacking gate, no injected failures | 9613 | 16 frames, up to ±1.25 px translation and ±0.30° rotation | None |
| `outlier-stress-24-holdout` | Noise and rejection stress | 7381 | 24 frames, same nominal shift/rotation range | Strong blur, large motion + highlight clipping, abnormal noise |
| `rotation-stress-20-holdout` | Wider motion/rotation stress | 5287 | 20 frames, up to ±1.8 px and ±0.90° per frame | Strong blur, large motion + highlight clipping, abnormal noise |

The run protocol freezes generator parameters, seed, input/oracle hashes, expected failure indices, algorithm/metric versions, output reference arrays and regression tolerances. Every major comparison includes an ordinary single frame, selected best single frame, registered stack, stack plus denoising, and—when invoked—the experimental deconvolution output.

The provisional targets in the approved architecture were not changed. The gate evaluates 16-frame SNR-proxy gain, sub-pixel registration error/coverage, MTF50 proxy retention, seeded blur/clipping rejection, and integrity records independently.

## D. GROUND-TRUTH ISOLATION

The generator writes observed frames to `observed/frames.npz` and ground truth/transforms/failure labels to a separate `evaluator-private/oracle.npz`. `run_experiment` loads observations and public fixture metadata, starts a fresh Python child process with only a temporary observation NPZ and output directory, waits for its result, and **only then** loads the evaluator oracle and invokes evaluation. The child environment, arguments and working directory do not receive the oracle object, path, keys, transforms or clean reference. The reconstruction modules do not import generator or evaluator modules; a unit test checks this boundary and checks that public metadata has no ground-truth fields.

This is an architectural/data-interface boundary for trusted research code, not a Windows OS security sandbox. A deliberately hostile Python process running as the same user could traverse readable workspace files. The current reconstruction modules have no such file traversal code; a later threat model that treats algorithms as hostile would need stronger operating-system sandboxing.

## E. ALGORITHMS TESTED

- **Frame scoring:** Components include total clipping fraction, highlight clipping fraction, underexposed fraction, contrast standard deviation, mean gradient, limb-edge sharpness, Laplacian variance, high-pass MAD noise estimate, relative sharpness/noise and median exposure. Current selection rules reject highlight clipping above 2%, limb-edge sharpness below 0.68× the burst median, noise above 1.35× the burst median, or global edge sharpness below 0.55× its median. Components and reason codes are retained. These are experimental burst-relative rules, not validated camera thresholds.
- **Selection:** Frames rejected during quality scoring or low-confidence alignment do not contribute to the stack. Each source receives a decision/reason; accepted and rejected IDs must agree with assessment records.
- **Alignment:** Robust iterative Lucas–Kanade rigid fitting estimates x/y translation plus small rotation from observed pixels. A phase-correlation estimator with spatial sub-pixel refinement is also implemented and separately tested. Transform, confidence, residual, reference ID and status are stored. The aligner is not given expected shifts.
- **Stacking:** Equal mean, equal weighted mean, median and per-pixel sigma-clipped mean are produced. `weighted_mean` currently uses equal weights; it is retained as a baseline/API slot and is not a distinct weighted-quality experiment yet.
- **Denoising:** A deterministic 12% mix toward a 3×3 local low-pass result is used. It is intentionally mild but still shows measurable MTF50 proxy loss.
- **Deconvolution:** An experimental Fourier-domain Wiener filter uses a Gaussian PSF assumption (σ=0.8 px) and regularization 0.025. It is off by default. The PSF is a test assumption, not measured iPhone optics.

## F. METRICS

Machine-readable definitions are in `phase0/results/run-010/metric-definitions.json`.

| Metric | Definition / units | Better direction | Limitations |
|---|---|---|---|
| Registration error | RMS of estimated minus known relative x/y shift; pixels. Rotation residual is also reported in degrees. | Lower | Evaluator-only synthetic ground truth; only high-confidence fits counted. |
| SNR proxy | Mean clean signal in a clean-truth-defined low-gradient lunar ROI divided by RMSE to that clean reference; ratio. | Higher | Evaluator-only truth-referenced proxy; not calibrated sensor SNR. |
| Edge sharpness | Mean image gradient in a truth-selected limb band; normalized intensity/pixel. | Higher only if noise/artifacts do not rise | Noise itself increases gradient. |
| MTF50 proxy | First 0.5 crossing of the Fourier magnitude of the differentiated radial limb edge-spread profile; cycles/pixel. | Higher | Synthetic limb/known geometry proxy; not a system MTF calibration. Used for the provisional 5% edge-retention gate. |
| FRC proxy | First radial Fourier ring where correlation between independently accumulated half-stacks falls below 1/7; cycles/pixel. | Higher | Relative consistency only; not absolute resolved-detail proof. |
| Clipping fraction | Pixels at normalized floor ≤0.002 or ceiling ≥0.995; fraction. | Lower | Thresholds are for normalized synthetic samples. |
| Ringing/halo | Maximum output overshoot beyond the 5×5 local range of clean truth near limb; normalized intensity. | Lower | Truth-referenced proxy; not a universal halo detector. |
| Seam/interpolation proxy | Mean gradient in the outer 3-pixel border divided by interior mean gradient; ratio. | Lower when crop support is unchanged | Scene/content sensitive; only a controlled warning metric. |
| False-detail indicator | High-pass(output) minus high-pass(clean) squared energy divided by clean high-pass energy; ratio, plus RMSE. | Lower | Synthetic evaluator-only disagreement; cannot certify physical truth. |
| Reconstruction error | RMSE and PSNR against the noiseless sampled reference; normalized units/dB. | Lower RMSE, higher PSNR | Only available for synthetic fixtures. |
| Rejection accuracy | TP/FN/FP/TN, precision, recall and false rejection rate vs hidden injected-failure labels. | Higher precision/recall, lower false rejects | Synthetic failure classes only; evaluator-only labels. |

## G. QUANTITATIVE RESULTS

Final measurements are from `run-010` (metric version 0.3) after the reconstruction worker returned and the oracle was loaded by the evaluator.

| Fixture | Frames | Accepted | Rejected | Translation RMS (px) | Rotation RMS (°) | Evaluated transform coverage | SNR proxy gain vs best single | MTF50 retention vs best single | FRC proxy (cycles/px) | Runtime (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gate noise, 16 frames | 16 | 16 | 0 | 0.0311 | 0.2541 | 15/15 (100%) | 3.171× | 90.3% | 0.3542 | 1.19 |
| Outlier stress | 24 | 23 | 1 | 0.0847 | 0.2661 | 22/22 (100%) | 19.273× | 100.0% | 0.3750 | 1.80 |
| Rotation stress | 20 | 19 | 1 | 0.0843 | 0.2488 | 18/18 (100%) | 20.280× | 90.0% | 0.3333 | 1.27 |

For the primary 16-frame sequence, best-single RMSE was **0.05145** and sigma-clipped stack RMSE **0.01718**. The SNR proxy increased from **5.005** to **15.870** (3.171×). The MTF50 proxy decreased from **0.24219** to **0.21875 cycles/pixel**, a **9.7% loss**, which fails the ≤5% loss target. The mild denoiser changed RMSE only from 0.01718 to **0.01717** and further lowered the edge proxies slightly.

All attempted results and failed comparisons are retained in `phase0/results/run-001/` through `run-011/`. Development runs 001–002 exposed weak registration and scorer behavior. Run 002’s scorer thresholds were selected after reviewing its outcome labels, so that run is marked exploratory and is not used as confirmatory evidence. The held-out seeds were then frozen and evaluated with the thresholds unchanged. Runs 003–006 predate the final bookkeeping/metric version tags and are retained as history; run 007 fixed a frame-assessment consistency defect; run 008 scoped the rejection gate to blur/clipping as specified; run 010 is the final baseline evaluation. Run 011 adds the separately requested experimental deconvolution branch.

## H. BAD-FRAME REJECTION RESULTS

On each 20/24-frame held-out stress fixture, the scorer rejected the **abnormal-noise** frame but failed to reject either required failure type:

| Required injected class | Detected / injected | Recall |
|---|---:|---:|
| Strong blur | 0/1 | 0% |
| Highlight clipping + large motion | 0/1 | 0% |
| Abnormal noise (reported separately) | 1/1 | 100% |

For the provisional blur/clipping gate, recall is **0/2 = 0%**, below the required 90%. On all three injected classes together, TP=1, FN=2, FP=0, TN=19 in the 24-frame sequence; overall recall=33.3%, precision=100%, and false rejection among the 19 good frames=0%. The 20-frame rotation-stress fixture gives the same class-specific outcome. This gate is a clear failure.

## I. ARTIFACT / FALSE-DETAIL FINDINGS

- The stack substantially reduced truth-referenced error and noise in these simulated sequences. On the primary fixture, the unsupported high-frequency energy ratio fell from **34.18** for the best single frame to **0.78** for the sigma-clipped stack and **0.67** after mild denoising. This indicates noise/resampling agreement with the simulator, not generative detail creation.
- Primary-fixture limb halo proxy fell from **0.167** for best single to **0.020** for the stack and **0.018** after denoising. These do not cancel the separate MTF50 retention failure.
- The rotation-stress border seam/interpolation proxy rose from **0.229** for best single to **0.284** for the stack (0.278 after denoising). The measure is scene-sensitive, but it flags border/support behavior for further investigation.
- With Wiener deconvolution on the primary fixture, SNR proxy fell from **15.87** (stack) to **9.49**, RMSE rose from **0.01718** to **0.02806**, halo proxy rose from **0.0204** to **0.0712**, and unsupported high-frequency energy rose from **0.78** to **2.91**. The MTF50 proxy increased to 0.289 cycles/pixel, but this coincided with worse truth error/artifact measures and is not evidence of recovered resolution. Keep deconvolution off.
- No generative operation exists in the scientific path. All “false-detail” values compare outputs against synthetic ground truth; they cannot show that any real lunar feature has been recovered or invented.

## J. OPTICAL INFORMATION CEILING ASSESSMENT

ASTRA must not claim recoverable resolution beyond what is supported by the optical system, sensor sampling, captured spatial-frequency content, registration diversity, and signal-to-noise ratio of the source frames. Upscaling, sharpening and deconvolution do not by themselves establish recovered resolution.

In this synthetic experiment, the aligned stack recovers lower-noise estimates of the generator’s own sampled, blurred scene. Sub-pixel shifts support more stable sampling and combination in the simulator, but the current pipeline resamples back to the source dimensions and does not establish a higher optical cutoff. The primary result also fails the MTF50 retention gate by 4.7 percentage points. No conclusion about iPhone optics, actual Moon detail, or sub-pixel super-resolution is justified.

## K. GOLDEN FIXTURES CREATED

Each listed fixture has an observation NPZ and a separate evaluator-private oracle NPZ; fixture JSON includes generator version, seed, parameters, expected failure indices, hashes, and the golden reference pointer. Golden arrays are versioned by algorithm/metric versions, with declared pixel/metric tolerances for future Swift/Metal comparison.

| Fixture ID | Intended future native use | Seed | Observation SHA-256 prefix | Oracle SHA-256 prefix | Golden reference |
|---|---|---:|---|---|---|
| `gate-noise-16-holdout` | Primary registration/stack/denoise parity fixture | 9613 | `f2325a9a507fc0d1` | `dedbbc8830b91fad` | `golden-reconstruct-0.3-metrics-0.3/` |
| `outlier-stress-24-holdout` | Scoring/rejection/stack robustness fixture | 7381 | `68d74c357540bb09` | `485795d9576167ba` | `golden-reconstruct-0.3-metrics-0.3/` |
| `rotation-stress-20-holdout` | Translation/rotation and boundary stress fixture | 5287 | `ff6851d9259b9e5c` | `52b009d09cb8b8dd` | `golden-reconstruct-0.3-metrics-0.3/` |

Golden comparison tolerances: normalized-pixel maximum absolute error 0.001; translation transform absolute error 0.10 px; RMSE range ±max(0.0002, 1%); SNR proxy ±2%; MTF50 proxy ±0.015 cycles/pixel; clipping-fraction tolerance 0.001. These are regression tolerances, not replacements for the scientific gates.

## L. PROVISIONAL GATE EVALUATION

Final source: `phase0/results/run-010/run-summary.json`.

| Provisional gate | Result | Measured value |
|---|---|---|
| Known-shift registration ≤0.25 px RMS | **PASS** | 0.0311 px primary; 0.0847 px outlier; 0.0843 px rotation stress |
| Valid registration coverage ≥90% | **PASS** | 100% in all three fixtures |
| 16-frame SNR-proxy improvement ≥2.5× | **PASS** | 3.171× |
| Edge/MTF50 proxy loss ≤5% | **FAIL** | 9.7% loss; 90.3% retention |
| Seeded blur/clipping rejection ≥90% | **FAIL** | 0% (0 of 2 required cases) |
| Source IDs, operations and versioned integrity records | **PASS** | All held-out output integrity audits passed |

The thresholds were not altered.

## M. PHASE 0 STATUS

**FAIL**

## N. LIMITATIONS

- The scene, PSF, noise, exposure, clipping and resampling models are intentionally simplified and not calibrated to iPhone 14 Pro Max hardware.
- The SNR, MTF50, FRC, ringing, seam and false-detail metrics are synthetic proxies. In particular, the primary stack fails the declared edge-retention criterion despite strong SNR/RMSE improvement.
- Blur and clipping rejection did not generalize in the held-out fixtures. Quality-scoring thresholds were explored on development seeds; run 002 is explicitly non-confirmatory. Final run 010 uses separate held-out seeds and frozen quality thresholds.
- The worker boundary prevents ordinary code paths from receiving hidden truth, but does not prevent a deliberately hostile same-user process from browsing the workspace without OS-level sandboxing.
- No real telescope/phone calibration, physical PSF, atmospheric seeing, or real lunar data were used. The result cannot validate the device capture assumptions in the architecture document.
- Experimental Wiener output made SNR/RMSE/halo/unsupported-energy results worse than the stack on the primary fixture. Its higher MTF50 proxy is not accepted as a detail claim.

Execution failures and recovery:

1. Initial command: `& 'C:\Users\richa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s phase0\tests -v`. The integration test failed with `PermissionError: [Errno 13] Permission denied` while writing `input.npz` under the runtime’s default AppContainer temp directory; cleanup also returned `WinError 5`. The sub-pixel test also failed: estimated `-0.0275` vs expected `-0.38` (tolerance 0.18). A workspace-local scratch directory and spatial sub-pixel refinement resolved both.
2. A later test run hit `NameError: name 'observations' is not defined` in `phase0/worker.py` while creating lineage edges. The identifier was corrected to `obs`; the integration and final tests then passed.
3. Final test command, same as above, completed **5 tests, OK**, exit code 0. The final baseline and deconvolution experiment commands both exited 0; their scientific gate result is FAIL as reported, not an execution error.

## O. RECOMMENDED NEXT ACTION

Do not proceed to Phase 1. Keep the provisional gates unchanged and redesign/revalidate two parts of the Phase 0 pipeline: (1) blur/highlight-clipping detection that catches both seeded classes on held-out data, and (2) a stack/denoise strategy that retains at least 95% of the declared MTF50 proxy. Use a new preregistered fixture split, retain all development runs, and do not tune against the holdout oracle. Revisit device-specific assumptions only after Phase 0 passes.
