# ASTRA Phase 0 Research Harness

Offline-only feasibility experiments. This package is not part of the future iOS runtime. Reconstruction receives observed frames and public acquisition descriptors only. The evaluator receives hidden truth after a reconstruction result exists. This is a process/data-interface separation for trusted research code, not an OS security sandbox against deliberately hostile code.

Run from the repository root with the bundled Python 3.12 runtime:

```powershell
& 'C:\Users\richa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s phase0\tests -v
& 'C:\Users\richa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m phase0.run_experiment --output phase0\results\baseline
```

Dependencies: NumPy and Pillow. Tests use the Python standard library `unittest`.

Layout:

- `generator.py`: deterministic lunar-like scene/frame generator and hidden oracle types.
- `algorithms.py`, `quality.py`: reconstruction-side code; imports contain no generator/evaluator module.
- `runner.py`: serializes only observations to a child worker; oracle remains in the parent process.
- `evaluator.py`, `metrics.py`: post-reconstruction metrics and hidden-truth comparisons.
- `fixtures/`: frozen observation packages and separately stored evaluation oracle.
- `reports/`: generated human-readable and JSON experiment records.

All thresholds are declared in `config.py` and remain provisional architecture targets. A failed gate is reported as failed/inconclusive; code does not tune thresholds to observed outcomes.
