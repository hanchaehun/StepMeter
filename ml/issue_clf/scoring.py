"""Plan 6.2 measurement-only heuristic. Calibration is an explicit input."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ml.issue_clf.features import Features

SCORING_VERSION = 'issue-score-v1'
TERMS = ('severity', 'violation_extent', 'detection_ratio', 'on_path', 'confusion', 'estimated')


@dataclass(frozen=True)
class ScoreConfig:
    weights: tuple[float, ...]
    threshold: float

    def __post_init__(self):
        if not isinstance(self.weights, tuple):
            raise ValueError('Immutable weight tuple required')
        values = (*self.weights, self.threshold)
        if (len(self.weights) != len(TERMS) or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                    not math.isfinite(v) or not 0 <= v <= 1 for v in values) or
                not math.isclose(sum(self.weights), 1, abs_tol=1e-9)):
            raise ValueError('Six nonnegative weights summing to 1 and threshold in [0,1] required')

    def as_dict(self):
        return {'scoring_version': SCORING_VERSION, 'weights': dict(zip(TERMS, self.weights)),
                'threshold': self.threshold}

    @classmethod
    def from_dict(cls, raw):
        if (not isinstance(raw, dict) or set(raw) != {'scoring_version', 'weights', 'threshold'} or
                raw['scoring_version'] != SCORING_VERSION or
                not isinstance(raw['weights'], dict) or set(raw['weights']) != set(TERMS)):
            raise ValueError('Unsupported score configuration')
        return cls(tuple(raw['weights'][key] for key in TERMS), raw['threshold'])


@dataclass(frozen=True)
class ScoredIssue:
    confidence: float
    is_reference: bool
    score_reason: str


def score_features(features: Features, config: ScoreConfig, *, was_reference: bool = False) -> ScoredIssue:
    """Missing magnitude/estimate contributes zero; never infer certainty from text.

    Reference rules and off-path findings stay reference regardless of threshold.
    The estimate term is a penalty; the final weighted sum is clipped to [0,1].
    """
    if (type(features.on_path) is not bool or type(features.confusion) is not bool
            or type(was_reference) is not bool
            or (features.estimated is not None and type(features.estimated) is not bool)):
        raise ValueError('Boolean score features required')
    magnitude = features.violation_extent if features.violation_extent is not None else 0.0
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or not 0 <= v <= 1
           for v in (features.severity, magnitude, features.detection_ratio)):
        raise ValueError('Invalid score feature')
    values = (features.severity, magnitude, features.detection_ratio,
              float(features.on_path), float(features.confusion), -float(features.estimated is True))
    if any(not math.isfinite(v) or not -1 <= v <= 1 for v in values):
        raise ValueError('Invalid score feature')
    contributions = [w*v for w, v in zip(config.weights, values)]
    confidence = min(1.0, max(0.0, math.fsum(contributions)))
    index = max(range(len(TERMS)), key=lambda i: abs(contributions[i]))
    reason = f'{TERMS[index]} {contributions[index]:+.3f} ({SCORING_VERSION})'
    return ScoredIssue(confidence, was_reference or not features.on_path or confidence < config.threshold, reason)
