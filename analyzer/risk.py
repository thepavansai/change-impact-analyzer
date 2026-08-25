"""Transparent, explainable risk scoring.

Reviewers will ask "why 82?" — so the score is a weighted sum of interpretable
signals, and we return the full breakdown, not just a number.

    score = 100 * sum(weight_i * normalized_signal_i)

Signals
-------
blast_radius      how many components are affected      (breadth)
depth             longest dependency chain reached      (reach)
fan_out           direct (depth-1) dependents           (immediacy)
api_exposure      is a public API/contract affected?    (external break risk)
test_gap          fraction of impacted code lacking tests
type_change       did a field/method TYPE change?       (backward-incompat)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .diff import ChangedSymbol
from .impact import AffectedComponent

WEIGHTS = {
    "blast_radius": 0.25,
    "depth": 0.15,
    "fan_out": 0.15,
    "api_exposure": 0.20,
    "test_gap": 0.10,
    "type_change": 0.15,
}


@dataclass
class RiskResult:
    score: int
    level: str
    breakdown: List[Tuple[str, float, float]]  # (signal, raw_normalized, weighted_pts)


def _level(score: int) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def score_risk(affected: Dict[str, AffectedComponent],
               changes: List[ChangedSymbol],
               n_tests_recommended: int) -> RiskResult:
    prod = {k: v for k, v in affected.items() if not v.is_test}
    n_affected = len(prod)

    blast = min(n_affected / 6.0, 1.0)               # ~6 components -> saturated
    max_depth = max([v.depth for v in prod.values()], default=0)
    depth = min(max_depth / 4.0, 1.0)                # chain of 4 -> saturated
    fan_out_count = sum(1 for v in prod.values() if v.depth == 1)
    fan_out = min(fan_out_count / 4.0, 1.0)
    api_exposure = 1.0 if any(v.is_api for v in prod.values()) else 0.0

    tested = sum(1 for v in prod.values() if _has_test(v.cls, affected))
    test_gap = 1.0 - (n_tests_recommended > 0 and (tested / max(n_affected, 1)) or 0.0)
    test_gap = max(0.0, min(test_gap, 1.0))

    type_change = 1.0 if any(
        c.change == "MODIFIED" and c.before != c.after for c in changes
    ) else 0.4 if changes else 0.0

    signals = {
        "blast_radius": blast,
        "depth": depth,
        "fan_out": fan_out,
        "api_exposure": api_exposure,
        "test_gap": test_gap,
        "type_change": type_change,
    }

    breakdown = []
    total = 0.0
    for name, w in WEIGHTS.items():
        pts = 100 * w * signals[name]
        total += pts
        breakdown.append((name, round(signals[name], 2), round(pts, 1)))

    score = int(round(total))
    return RiskResult(score=score, level=_level(score), breakdown=breakdown)


def _has_test(cls: str, affected: Dict[str, AffectedComponent]) -> bool:
    # a very rough proxy: is any test component in the affected set at all?
    return any(v.is_test for v in affected.values())
