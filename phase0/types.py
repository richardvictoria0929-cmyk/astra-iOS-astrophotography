"""Public observation/result contracts. Deliberately contains no ground truth."""

from dataclasses import dataclass, field
from typing import Any
import numpy as np


@dataclass(frozen=True)
class ObservationSequence:
    fixture_id: str
    frames: np.ndarray  # N,H,W float32, normalized sensor samples, clipping retained
    frame_ids: tuple[str, ...]
    public_metadata: tuple[dict[str, Any], ...]
    algorithm_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.frames.ndim != 3 or self.frames.shape[0] != len(self.frame_ids):
            raise ValueError("frames must have shape (N,H,W) and match frame_ids")
        if len(self.public_metadata) != len(self.frame_ids):
            raise ValueError("metadata count must match frame_ids")
        forbidden = {"truth", "ground_truth", "true_shift", "true_transform", "oracle"}
        for record in self.public_metadata:
            if forbidden.intersection(record):
                raise ValueError("observation metadata contains hidden evaluation fields")


@dataclass(frozen=True)
class FrameAssessment:
    frame_id: str
    components: dict[str, float]
    decision: str
    reasons: tuple[str, ...]
    score_version: str = "quality-0.1"


@dataclass(frozen=True)
class Alignment:
    frame_id: str
    reference_id: str
    dx: float
    dy: float
    rotation_deg: float
    confidence: float
    residual: float
    status: str
    version: str = "align-0.2"


@dataclass
class ReconstructionResult:
    fixture_id: str
    reference_id: str
    accepted_ids: list[str]
    rejected_ids: list[str]
    assessments: list[FrameAssessment]
    alignments: list[Alignment]
    baselines: dict[str, np.ndarray]
    operations: list[dict[str, Any]]
    algorithm_version: str = "reconstruct-0.3"
    warnings: list[str] = field(default_factory=list)
