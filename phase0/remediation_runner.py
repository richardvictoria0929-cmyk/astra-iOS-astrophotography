"""Isolated observation-only launch for remediation reconstruction."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import numpy as np


def run_remediation_isolated(observations, *, thresholds=None):
    if any(k in json.dumps(observations.public_metadata).lower()
           for k in ("truth", "oracle", "true_shift", "transform")):
        raise ValueError("observation metadata failed hidden-truth leakage audit")
    scratch_parent = Path(__file__).resolve().parent / ".tmp"
    scratch_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="astra-remediation-observed-", dir=scratch_parent) as td:
        root = Path(td)
        inp, out = root / "input.npz", root / "output"
        public_config = dict(observations.algorithm_config)
        if thresholds:
            public_config["remediation_thresholds"] = thresholds
        np.savez_compressed(inp, frames=observations.frames,
                            frame_ids=np.asarray(observations.frame_ids),
                            public_metadata_json=np.asarray(json.dumps(observations.public_metadata)),
                            public_config_json=np.asarray(json.dumps(public_config)),
                            fixture_id=np.asarray(observations.fixture_id))
        entry = Path(__file__).resolve().parent.parent
        code = "import sys;sys.path.insert(0," + repr(str(entry)) + ");from phase0.remediation_worker import main;main()"
        cmd = [sys.executable, "-I", "-c", code, "--input", str(inp), "--output", str(out)]
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
               "WINDIR": os.environ.get("WINDIR", ""), "TEMP": str(root), "TMP": str(root),
               "PYTHONNOUSERSITE": "1"}
        started = time.perf_counter()
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=600)
        elapsed = time.perf_counter() - started
        if proc.returncode != 0:
            raise RuntimeError(f"remediation worker failed ({proc.returncode})\n{proc.stdout}\n{proc.stderr}")
        record = json.loads((out / "result.json").read_text(encoding="utf-8"))
        with np.load(out / "images.npz", allow_pickle=False) as data:
            images = {key: data[key].copy() for key in data.files}
    return record, images, elapsed
