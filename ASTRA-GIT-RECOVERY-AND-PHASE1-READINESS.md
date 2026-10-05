# ASTRA repository recovery and Phase 1 readiness

This handoff preserves the accepted Phase 0 remediation and prepares its existing pull request for review. Phase 1 is **INCONCLUSIVE / not started** because the accepted remediation has not yet been merged into `main`.

| Requested item | Recorded state |
|---|---|
| A. Git state recovered | Started on `main` at `7b25ee7d600ef9adddb7d12df6592f5d43b9d3c0`, tracking `origin/main`. The local and remote `phase0-remediation` branches were at `116c4398b898a4e79609d350a0911ef82e07087d`. No staged changes or stashes were present. Six remediation modules were modified; 90 legitimate remediation files were untracked, alongside an untracked bytecode file. The bytecode deletions seen on `main` already belonged to the cleanup commit on `phase0-remediation`. |
| B. Phase 0 preservation | A recovery archive of 272 source/evidence files, its SHA-256 manifest, a Git bundle of all refs, working/staged diffs, and the previous index were saved under ignored `phase0/.tmp/git-recovery-20261005T213410Z/`. All 272 files were byte-identical after switching branches. Historical run-010 remains FAIL. |
| C. Phase 0 PR/merge | Existing PR [#1](https://github.com/richardvictoria0929-cmyk/astra-iOS-astrophotography/pull/1), `phase0-remediation` to `main`, was open and unmerged with no submitted reviews or discussion comments at inspection. Before recovery it contained only ignore rules and bytecode cleanup. Its review conditions require scientific-gate review, Codex Code Review, and explicit approval before merge. |
| D. Phase 1 branch | `phase1-ios-capture-foundation` has not been created. Create it from updated `main` only after the accepted remediation is merged. |
| E. Files | Preserve/commit the six modified remediation modules, `test_remediation.py`, the remediation report, the additional remediation-002 diagnostic and complete remediation-003 through remediation-007 result history. Generator/runner modules, nine preregistered fixture families and earlier history were already committed. Add `.gitattributes` and this handoff. |
| F. Native iOS architecture | Not implemented in this recovery pass; the existing architecture roadmap remains the planning baseline. |
| G. Camera/capability implementation | Not started. Runtime camera discovery, control support and requested-versus-applied settings remain Phase 1 work after the merge prerequisite. |
| H. Evidence storage/provenance | Existing Phase 0 evidence verified and preserved. Native immutable source assets, checksums and capture-session manifests remain Phase 1 work. |
| I. Simulator-testable results | No Xcode, simulator build or simulator tests were run. Existing offline deterministic tests passed 8/8 in 11.721 seconds. They used development fixtures and temporary generated inputs, without rerunning the frozen holdout evaluation. |
| J. Real-device tests | No iPhone testing has occurred. Phase 1 still requires iPhone 14 Pro Max measurements: 100 requests, at least 99 durable outputs, matching manifest/output counts, strictly ordered timestamps, 100% reloaded checksum agreement, at least 95% manual exposure/ISO tolerance compliance where claimed, and measured median/p95 cadence. |
| K. Blockers | PR #1 requires review, approval and merge before Phase 1. The repository remains in OneDrive; a prior checkout was found blocked and holding `.git/index.lock`. No repository relocation was performed. |
| L. Phase 1 status | INCONCLUSIVE; not implemented or device-verified. |
| M. Next action | Review and merge the completed Phase 0 PR. Then update `main`, confirm it contains the accepted evidence and source commit, and create `phase1-ios-capture-foundation`. |

## Recovery and preservation details

The initial branch switch encountered an existing zero-byte index lock. A full process inspection identified an earlier `git checkout phase0-remediation` started at 05:26 local time, with its launcher and child process still running. After backups were complete, that blocked checkout was cancelled, the empty lock was moved into the recovery folder, and the requested branch switch succeeded. No reset, clean, restore, force-push or history rewrite was used.

The remediation branch's existing `.gitignore` excludes `__pycache__`, bytecode and `phase0/.tmp/`. Cache files and recovery archives are not commit content. The previous tracked-cache removal remains in commit `116c439`.

The repository uses `core.autocrlf=true`. Frozen JSON files in the workspace contain CRLF bytes, and their recorded SHA-256 commitments use those exact bytes. Git would otherwise normalize them to LF on commit, breaking commitments on a checkout that does not recreate CRLF. `.gitattributes` disables text conversion for `phase0/fixtures/**` and `phase0/results/**`. The staged-index audit verified all 245 fixture/result files match their current raw bytes. The 109 previously tracked evidence text files shown as changed differ from earlier Git blobs only in line endings. All 272 recovery-snapshot files still match. Earlier commits remain available. No metric, image, fixture parameter, label, gate or result value was edited.

## Evidence verification

The read-only audit confirmed all 29 recorded file-hash checks: 18 fixture observation/oracle files, six frozen holdout result files, four release-card references and the selected-profile development-summary reference. Oracle NPZ files were hashed without decoding their contents. Independently checked 198 observed source-array hashes and 72 output-array hashes across the holdout outputs; lineage parent/child hashes and complete, disjoint accept/reject decisions agree.

The accepted result remains PASS under its frozen scope: five failure labels at 100% recall; MTF50 retention 96.97%; maximum registration RMS 0.0488 px; 100% valid registration coverage; SNR gate gain 4.491x; integrity/provenance PASS; deterministic tests 8/8. The clean-motion false rejection remains disclosed as 1/32 stress frames and 1/148 good holdout frames overall. Deconvolution remains disabled; this evidence is synthetic/offline only.

## Clarifications for review, without changing frozen evidence

The original remediation report and result files are preserved. Reviewers should apply these clarifications:

- The report's prose says the final denoised result reduces clipping versus plain mean. Its table records mean clipping as 0 and final clipping as 0.000326. Ringing improves versus mean, while clipping increases slightly; clipping improves substantially versus the best single frame.
- The 4.491x gate statistic is the sigma-clipped **pre-denoise** SNR gain versus the selected best single source. The table's SNR proxy 24.827 belongs to the denoised output. These are distinct recorded measurements.
- “No generative processing was used” is supported by the operation records. The recorded artifact proxies do not prove the absolute absence of unsupported structure.
- The release card freezes version identifiers, profiles and output references, but has no historical source-file or Git commit hash. This recovery commit records the current source revision; it does not retroactively prove a historical source revision.
- The diagnostic weighted-mean path uses median background noise in its numerator and per-frame disk noise in its denominator. Clamping can flatten the weights, consistent with its near-identical mean/weighted results. The accepted sigma-clipped path does not use those weights.
- Reproduce the accepted configuration through `selected-profile.json`: its background-noise threshold is 1.5, while the library default remains 2.5. Bare library defaults are not the accepted profile.

These are local audit findings for PR review. They are not a GitHub Codex Code Review submission or merge approval. No frozen algorithm was retuned and no Phase 1 source was added.
