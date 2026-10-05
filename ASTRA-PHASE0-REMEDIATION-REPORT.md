# ASTRA Phase 0 Bounded Remediation Report

**Run:** `remediation-007`  
**Scope:** Phase 0 only: bad-frame rejection and stack edge retention  
**Final status:** **PASS under the preregistered gate scope**  
**Device status:** Synthetic/offline validation only; no iPhone or camera hardware tested.

This report supplements, and does not replace or rewrite, [`ASTRA-PHASE0-REPORT.md`](ASTRA-PHASE0-REPORT.md). The run-010 failure, earlier run history, source fixtures, golden outputs, metric definitions, and algorithm history remain preserved. The experimental Wiener path remains disabled.

## A. Root-cause analysis

### Blur, clipping, and motion rejection

The prior `quality.py` scorer had interpretable metrics, but its decision rules were too global for sparse lunar defects:

- Highlight rejection used the fraction of **all image pixels** above 0.995, with a 2% cutoff. A clipped patch confined to the lunar disk can occupy less than 2% of the full frame, so it can escape rejection. The scorer did not measure connected clipped area or clipping within the lunar disk.
- Sharpness decisions compared whole-frame mean gradient and limb gradient to burst medians. A blur outlier was not evaluated against a stable lunar-disk region or a local high-frequency loss measurement; its score could be diluted by background and texture.
- Transform magnitude was not a quality decision. The earlier scorer left `motion_alignment_confidence` as a placeholder, and did not reject unstable/abnormal registration transforms. This explains why clipping combined with large motion could survive even when the individual cues were weak.
- The high-pass MAD noise feature did distinguish the abnormal-noise case. It was retained and supplemented with a background-only high-pass MAD to avoid confusing lunar texture with sensor noise.

The remediation uses lunar-disk clipping fraction and connected clipped-area size, relative disk Laplacian energy, radial limb-gradient retention, whole-frame and background high-pass noise, exposure deviation, and post-registration translation/rotation/residual checks. It emits explicit reason codes; it is not a learned classifier.

### Edge retention

The controlled holdout stage sweep localizes the largest loss to **per-frame registration resampling**. On the primary clean holdout sequence, the best-source MTF50 was 0.2578125 cycles/pixel. Mean MTF50 for aligned individual sources was 0.2363281 with bilinear interpolation (91.67% retention), versus 0.2514648 with bicubic interpolation (97.54%). The selected bicubic path therefore removes most of the earlier interpolation loss.

The mean, quality-weighted mean, and median stacks each retained 100% of best-source MTF50 on this fixture. Sigma clipping reduced it by one discrete MTF bin to 96.97%; denoising caused no additional measured reduction. Registration RMS was only 0.0308 px, so transform error accumulation was not the dominant observed cause. Valid registration coverage was 100%, and the seam proxy is separately reported below; crop/overlap loss was not the limiting factor on this fixture. Reference selection was also improved to use a sharp, low-noise source among robust position inliers instead of the previous central-frame choice.

Fourier translation and rigid-warp candidates retained a higher MTF50 bin in some stage measurements. Their complete output metrics were less balanced, however, so they were not selected for the frozen final path. These synthetic results support interpolation/resampling as the main source of the run-010 edge loss; they do not establish the same cause on physical camera data.

## B. Files changed and preserved evidence

### Changed or added for the remediation

- Remediation modules: `phase0/remediation_algorithms.py`, `phase0/remediation_evaluator.py`, `phase0/remediation_experiment.py`, `phase0/remediation_protocol.py`, `phase0/remediation_quality.py`, and `phase0/remediation_worker.py`.
- Deterministic checks: `phase0/tests/test_remediation.py` (added; the original test file was not changed).
- New frozen fixture family: `phase0/fixtures/remed-001-{development,validation,holdout}-{clean16,outlier-80-or-150,motion-stress32}/`, with observations, evaluator-only oracle data, parameters, seeds, and hashes.
- New run history and artifacts: `phase0/results/remediation-002/` through `remediation-007/`; run-007 contains the release card, selected profile, gate-scope addendum, frozen holdout worker outputs, and all metrics/lineage outputs.
- Final summaries: this report and [`phase0/results/remediation-007/final-gates.json`](phase0/results/remediation-007/final-gates.json).

The original run-010 report, old fixtures and goldens, metric implementation/version, and old test suite were not overwritten. Remediation runs remain separate; the selected release is run-007.

## C. Algorithm and metric versions

| Component | Frozen version | Responsibility |
|---|---|---|
| Synthetic generator | `lunar-remediation-0.1` | New split-specific simulated observations and evaluator-private truth |
| Quality scorer | `quality-0.5` | Interpretable disk, edge, noise, exposure, and transform rejection features |
| Alignment | `align-0.7` | Robust position/reference selection, transform estimates, bicubic registration path |
| Reconstruction | `reconstruct-0.9` | Multi-variant stacking and conservative denoising; deconvolution unavailable/off |
| Metrics | `metrics-0.3` | Existing metric definitions retained unchanged |
| Evaluator | `remediation-evaluator-0.1` | Confusion matrices, stage metrics, artifact metrics, provenance audit |
| Rejection profile | `rejection-profile-0.6` | Thresholds selected from development and frozen before holdout |
| Protocol | `phase0-remediation-protocol-0.1` | Preregistered split, labels, metric/gate scope, freeze order |

No gate or metric definition was changed. The frozen thresholds are recorded in `phase0/results/remediation-007/selected-profile.json` and the release card. They include 0.4% lunar-disk clipping, 12 pixels maximum clipped connected component, 0.55 minimum relative disk Laplacian energy, 0.62 minimum relative limb gradient, 1.5 maximum relative background-noise MAD, 0.35 maximum exposure deviation, translation outlier z=3, maximum rotation 1.5 degrees, and registration residual 0.28.

## D. New preregistered fixture split

The split and label commitments were frozen before selection; thresholds were chosen using development only, then checked on validation. The release card was written before holdout processing. Holdout observations were processed by a worker without oracle access; reconstruction and image-output hashes were frozen in `holdout/worker-output-freeze.json` before the private oracle was opened. No code, threshold, metric, or gate was changed after that evaluation.

| Split | Seed | Clean primary | Class-balanced failures | Wider motion/rotation stress |
|---|---:|---:|---:|---:|
| Development | 41401–41403 | 16 frames | 80 frames: 40 good plus 8 per primary failure tag | 32 clean frames |
| Validation | 52401–52403 | 16 frames | 80 frames: 40 good plus 8 per primary failure tag | 32 clean frames |
| Holdout | 63401–63403 | 16 frames | 150 frames: 100 good plus 10 per primary failure tag | 32 clean frames |

Primary tags are strong blur, clipping, large motion, abnormal noise, and mixed. Mixed samples carry multiple one-vs-rest tags. The wider-motion fixtures use translation span ±2.0 px and rotation span ±0.65 degrees; standard fixtures use ±1.25 px and ±0.30 degrees. All fixture IDs, full generator parameters, observation/oracle SHA-256 hashes, and expected label commitments are stored in `phase0/results/remediation-007/preregistration.json` and the split summaries. The holdout IDs are `remed-001-holdout-clean16`, `remed-001-holdout-outlier-150`, and `remed-001-holdout-motion-stress32`.

The preregistered gate scope matches the original baseline: registration is checked on all fixtures; SNR and MTF50 gates use the primary clean 16-frame stack, with other fixture values retained as diagnostics; per-class recall is measured on the class-balanced outlier fixture; integrity is checked on all outputs. This scope is recorded in the immutable run-007 gate-scope addendum.

## E. Frame-rejection results by failure class

Holdout results on the 150-frame class-balanced fixture (`N=100` good frames; overlapping failure labels) were:

| Failure label (one-vs-rest) | TP | FP | FN | TN | Recall | Precision | OVR false-positive rate | Good frames rejected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Strong blur | 20 | 30 | 0 | 100 | 100% | 40% | 23.08% | 0/100 |
| Clipping | 20 | 30 | 0 | 100 | 100% | 40% | 23.08% | 0/100 |
| Large motion | 20 | 30 | 0 | 100 | 100% | 40% | 23.08% | 0/100 |
| Abnormal noise | 10 | 40 | 0 | 100 | 100% | 20% | 28.57% | 0/100 |
| Mixed | 10 | 40 | 0 | 100 | 100% | 20% | 28.57% | 0/100 |

The one-vs-rest false positives are other **bad** frames carrying different labels, not accepted good frames. At the unique-frame level, all 50 failure frames were rejected and all 100 good frames were retained (TP=50, FP=0, FN=0, TN=100; recall and precision 100%). The class-balanced fixture good-frame false-rejection rate was 0%.

In the separate 32-frame clean motion stress fixture, one clean frame was rejected for `registration_rotation_outlier`: 1/32 (3.125%). Across the three holdout fixtures, 1 of 148 good frames was rejected (0.676%). This is explicitly reported; no false-rejection target was preregistered as a pass/fail gate. The primary clean16 fixture rejected 0/16 frames.

## F. Stage-by-stage edge-retention analysis

Primary clean holdout (`metrics-0.3`, MTF50 in cycles/pixel):

| Stage | MTF50 | Retention vs best source |
|---|---:|---:|
| A. Best source | 0.2578125 | 100.00% |
| B. Aligned individual sources, bilinear mean | 0.2363281 | 91.67% |
| B. Aligned individual sources, bicubic mean (selected path) | 0.2514648 | 97.54% |
| B. Fourier translation mean | 0.2587891 | 100.38% |
| B. Fourier rigid mean | 0.2607422 | 101.14% |
| C. Aligned mean stack | 0.2578125 | 100.00% |
| D. Quality-weighted stack | 0.2578125 | 100.00% |
| E. Median stack | 0.2578125 | 100.00% |
| F. Sigma-clipped stack | 0.2500000 | 96.97% |
| G. Denoised stack | 0.2500000 | 96.97% |

The MTF metric is quantized on these small synthetic frames: the one-bin reduction at sigma clipping is about 3.03 percentage points. The final selected stack remains above the 95% gate. Fourier variants were evaluated across complete-image metrics below rather than chosen on MTF50 alone.

## G. Stacking and reconstruction variants

Metrics below use the primary clean holdout and unchanged `metrics-0.3` definitions. RMSE, ringing, seam, clipping, and unsupported high-frequency energy are lower-is-better; the SNR proxy and MTF50 are higher-is-better. The false-detail column is the evaluator's unsupported high-frequency energy ratio.

| Variant | RMSE | SNR proxy | MTF50 retention | Clipped fraction | Ringing | Seam proxy | Unsupported HF ratio |
|---|---:|---:|---:|---:|---:|---:|---:|
| Best single source | 0.053064 | 5.329 | 100.00% | 0.136393 | 0.213843 | 0.173600 | 28.256 |
| Registered mean | 0.011221 | 25.183 | 100.00% | 0 | 0.038859 | 0.100707 | 1.025 |
| Quality-weighted mean | 0.011221 | 25.183 | 100.00% | 0 | 0.038859 | 0.100707 | 1.025 |
| Median | 0.013035 | 21.777 | 100.00% | 0.003147 | 0.029980 | 0.122114 | 1.417 |
| Sigma clipped | 0.011859 | 23.932 | 96.97% | 0.000760 | 0.023062 | 0.116483 | 1.140 |
| **Sigma clipped + denoised (frozen final)** | **0.011544** | **24.827** | **96.97%** | **0.000326** | **0.023062** | **0.108618** | **1.068** |
| Fourier sigma-clipped + denoised | 0.012956 | 21.680 | 100.00% | 0.000760 | 0.046814 | 0.100752 | 1.555 |
| Fourier rigid sigma-clipped + denoised | 0.013681 | 20.502 | 100.00% | 0.000217 | 0.060254 | 0.117968 | 1.845 |

The final denoised variant improves RMSE, clipping, ringing, seam proxy, and unsupported-HF energy substantially versus the best single frame, while passing the MTF50 gate. Relative to plain mean, it spends one MTF bin and has slightly higher RMSE/seam proxy, while reducing ringing and clipping; this is recorded as a tradeoff, not hidden. Fourier translation gains that MTF bin over the frozen final stack, but its RMSE is about 12% higher, SNR proxy about 13% lower, ringing about 2× higher, and unsupported-HF ratio about 46% higher. The Fourier-rigid variant also has a higher MTF50 bin, but RMSE is about 19% higher, SNR proxy about 17% lower, ringing about 2.6× higher, and unsupported-HF ratio about 73% higher. Neither was selected. The experimental deconvolution path was not used.

## H. Regression results for previously passing gates

| Regression gate | Threshold | Holdout result | Status |
|---|---:|---:|---|
| Registration RMS | ≤0.25 px | 0.0308 px clean16; 0.0394 px outlier; 0.0488 px stress | PASS |
| Valid registration coverage | ≥90% | 100% on all three fixtures | PASS |
| 16-frame SNR-proxy gain | ≥2.5× | 4.491× on clean16 | PASS |
| Integrity/provenance | Complete, hashes match | 3/3 fixture audits pass; complete source decisions, hashes, lineage edges; output hashes match | PASS |
| Deterministic tests | All pass | 8/8 (5 prior + 3 remediation checks) | PASS |

The SNR and MTF values for outlier and stress fixtures are diagnostics only under the frozen baseline gate scope; they are preserved in each `metrics.json`.

## I. Artifact and false-detail analysis

On primary clean16, the chosen stack lowered best-single RMSE from 0.053064 to 0.011544; ringing from 0.213843 to 0.023062; seam proxy from 0.173600 to 0.108618; clipping from 13.64% to 0.033%; and unsupported high-frequency ratio from 28.256 to 1.068. It did not synthesize new structure: the evaluator checks output/source lineage and high-frequency error against the known simulation oracle. This supports the integrity gate for the synthetic experiment only, not a physical-scene scientific claim.

The source-frame and output hashes, per-frame accept/reject decisions, rejection reason codes, alignment transforms, operation parameters, metrics, and parent/child lineage edges are present in the frozen reconstruction artifacts. All three holdout audits report matching hashes and complete lineage. Deconvolution is marked disabled.

## J. Final gate table

| Gate | Preregistered requirement | Holdout result | Status |
|---|---|---|---|
| Registration | RMS ≤0.25 px and coverage ≥90% | Max RMS 0.0488 px; min coverage 100% | PASS |
| 16-frame SNR | ≥2.5× | 4.491× | PASS |
| Edge retention | MTF50 ≥95% | 96.97% | PASS |
| Blur rejection | Recall ≥90% | 100% | PASS |
| Clipping rejection | Recall ≥90% | 100% | PASS |
| Large-motion rejection | Recall ≥90% | 100% | PASS |
| Abnormal-noise rejection | Recall ≥90% | 100% | PASS |
| Mixed-failure rejection | Recall ≥90% | 100% | PASS |
| Good-frame false rejection | Report explicitly | 0/100 class-balanced; 1/32 stress; 1/148 overall | REPORTED; no gate threshold |
| Scientific integrity/provenance | Full lineage and hashes | All 3 holdout audits pass | PASS |
| Deterministic tests | All pass | 8/8 | PASS |

## K. Status

**PASS** for this bounded Phase 0 remediation under the recorded gate scope. The historical run-010 status remains **FAIL** in the original report; this report records the subsequent frozen remediation run and its result.

## L. Recommendation

Stop Phase 0 work here and recommend a **Phase 1 review**. Do not begin Phase 1 automatically. The next review should decide whether the synthetic evidence and its remaining clean-motion false rejection are adequate to authorize native iOS camera-capture work. No iPhone 14 Pro Max behavior, AVFoundation capability, thermal performance, or real lunar image quality has been validated by this offline Phase 0 pass.
