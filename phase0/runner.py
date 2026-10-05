"""Parent/evaluator orchestration. Oracle never enters child process arguments or files."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import numpy as np

from .types import ObservationSequence


def run_reconstruction_isolated(observations: ObservationSequence, *, deconvolution=False) -> tuple[dict, dict, float]:
    """Run the trusted worker in a fresh process with an observation-only temp directory.

    This is process/data-interface isolation, not a hostile-code OS sandbox. The
    child receives neither an oracle object/path nor oracle keys/values/environment.
    """
    if any(k in json.dumps(observations.public_metadata).lower() for k in ("truth", "oracle", "true_shift")):
        raise ValueError("observation metadata failed hidden-truth leakage audit")
    scratch_parent = Path(__file__).resolve().parent / ".tmp"
    scratch_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="astra-phase0-observed-", dir=scratch_parent) as td:
        root = Path(td)
        input_path = root / "input.npz"
        output_path = root / "output"
        np.savez_compressed(input_path, frames=observations.frames,
                            frame_ids=np.asarray(observations.frame_ids),
                            public_metadata_json=np.asarray(json.dumps(observations.public_metadata)),
                            fixture_id=np.asarray(observations.fixture_id),
                            public_config_json=np.asarray(json.dumps(observations.algorithm_config)))
        entry = Path(__file__).resolve().parent.parent
        code = "import sys;sys.path.insert(0," + repr(str(entry)) + ");from phase0.worker import main;main()"
        cmd = [sys.executable, "-I", "-c", code, "--input", str(input_path), "--output", str(output_path)]
        if deconvolution:
            cmd.append("--deconvolution")
        env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
               "WINDIR": os.environ.get("WINDIR", ""), "TEMP": str(root), "TMP": str(root),
               "PYTHONNOUSERSITE": "1"}
        started = time.perf_counter()
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=180)
        elapsed = time.perf_counter() - started
        if proc.returncode != 0:
            raise RuntimeError(f"reconstruction worker failed (exit {proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}\nCOMMAND:\n{subprocess.list2cmdline(cmd)}")
        record = json.loads((output_path / "result.json").read_text(encoding="utf-8"))
        with np.load(output_path / "images.npz", allow_pickle=False) as data:
            images = {key: data[key].copy() for key in data.files}
    return record, images, elapsed
