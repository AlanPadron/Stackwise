"""Transparent, deterministic risk indicators.

What this is: a documented, versioned *heuristic* that turns already-normalised
findings into a few readable indicators. What this is **not**: a probability of
exploitation, a security guarantee, or a replacement for reading the findings.

Formula (algorithm version `risk-1`):

    severity weights        critical 10, high 5, medium 2, low 0.5, info 0
    quality multipliers     bug 0.75, complexity 1.0, maintainability 0.5,
                            performance 0.5, dead_code 0.25, style 0.1, other 0.25

    security.points = Σ severity_weight(finding) over findings of category
                      "security"
    quality.points  = Σ severity_weight × quality_multiplier over the remaining
                      findings
    points → band   0 → "none", ≤5 → "low", ≤20 → "moderate", >20 → "high"
    index           100 × (1 − min(1, points / saturation)) with saturation 50
                    (security) and 60 (quality): 100 = no weighted points found,
                    0 = the saturation point or worse

    overall.index   = 0.75 × security.index + 0.25 × quality.index

Reproducibility: the same findings and configuration always produce the same
numbers (nothing time- or order-dependent; findings arrive deduplicated, so a
tool that reports the same issue twice cannot double-count). Boundary behaviour
is pinned by tests.

Honest degradation: if no security analyzer ran successfully, `security.available`
is false and `overall.index` is **null** — the engine refuses to report a safe
number when the security signal is missing. If the quality signal is missing but
security is present, the overall index falls back to the security index alone and
says so.
"""

from typing import Any, Optional, Sequence

from app.analysis.analyzers.base import AnalyzerOutcome
from app.analysis.config import AnalysisConfig
from app.analysis.normalize import NormalizedFinding
from app.analysis.registry import AnalyzerRegistry

ALGORITHM_VERSION = "risk-1"

SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 10.0,
    "high": 5.0,
    "medium": 2.0,
    "low": 0.5,
    "info": 0.0,
}

QUALITY_MULTIPLIERS: dict[str, float] = {
    "bug": 0.75,
    "complexity": 1.0,
    "maintainability": 0.5,
    "performance": 0.5,
    "dead_code": 0.25,
    "style": 0.1,
    "other": 0.25,
}

SECURITY_SATURATION_POINTS = 50.0
QUALITY_SATURATION_POINTS = 60.0
OVERALL_WEIGHTS = {"security": 0.75, "quality": 0.25}
BAND_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.0, "none"),
    (5.0, "low"),
    (20.0, "moderate"),
)

NOTES = (
    "Heuristic indicator computed from normalised findings; it is not a "
    "probability of exploitation and not an audit result.",
    "Higher index = fewer weighted findings; the exact formula is documented in "
    "docs/ANALYSIS_ENGINE.md and versioned by algorithm_version.",
)


class RiskEvaluator:
    """Computes the `AnalysisRun.risk` document."""

    def __init__(
        self,
        *,
        config: AnalysisConfig,
        registry: AnalyzerRegistry,
        findings: Sequence[NormalizedFinding],
        outcomes: Sequence[AnalyzerOutcome],
    ):
        self._config = config
        self._registry = registry
        self._findings = tuple(findings)
        self._outcomes = tuple(outcomes)

    def evaluate(self) -> dict[str, Any]:
        outcomes_by_name = {outcome.analyzer: outcome for outcome in self._outcomes}
        known = [name for name in outcomes_by_name if name in self._registry]

        security_names = [n for n in known if self._registry.spec(n).category == "security"]
        quality_names = [n for n in known if self._registry.spec(n).category != "security"]

        security_ok = [n for n in security_names if outcomes_by_name[n].succeeded]
        quality_ok = [n for n in quality_names if outcomes_by_name[n].succeeded]

        security_points = sum(
            SEVERITY_WEIGHTS.get(finding.severity, 0.0)
            for finding in self._findings
            if finding.category == "security"
        )
        quality_points = sum(
            SEVERITY_WEIGHTS.get(finding.severity, 0.0) * QUALITY_MULTIPLIERS.get(finding.category, 0.25)
            for finding in self._findings
            if finding.category != "security"
        )

        security = _dimension(
            points=security_points,
            saturation=SECURITY_SATURATION_POINTS,
            available=bool(security_ok),
            reason=None
            if security_ok
            else _unavailable_reason(security_names, outcomes_by_name, "security analyzer"),
            analyzer_names=security_names,
            outcome_names=security_ok,
            findings=sum(1 for f in self._findings if f.category == "security"),
        )
        quality = _dimension(
            points=quality_points,
            saturation=QUALITY_SATURATION_POINTS,
            available=bool(quality_ok),
            reason=None
            if quality_ok
            else _unavailable_reason(quality_names, outcomes_by_name, "quality analyzer"),
            analyzer_names=quality_names,
            outcome_names=quality_ok,
            findings=sum(1 for f in self._findings if f.category != "security"),
        )

        applicable = len(known)
        succeeded = len(security_ok) + len(quality_ok)
        degraded = [name for name in known if outcomes_by_name[name].status.failed]
        overall = self._overall(security, quality, degraded)

        return {
            "algorithm_version": ALGORITHM_VERSION,
            "heuristic": True,
            "dimensions": {"security": security, "quality": quality},
            "completeness": {
                "applicable_analyzers": applicable,
                "succeeded_analyzers": succeeded,
                "ratio": round(succeeded / applicable, 3) if applicable else None,
                "degraded_analyzers": sorted(degraded),
            },
            "overall": overall,
            "inputs": {
                "security_points": round(security_points, 2),
                "quality_points": round(quality_points, 2),
                "findings_counted": len(self._findings),
                "severity_weights": SEVERITY_WEIGHTS,
                "quality_multipliers": QUALITY_MULTIPLIERS,
            },
            "notes": list(NOTES),
        }

    def _overall(self, security: dict[str, Any], quality: dict[str, Any], degraded: Sequence[str]) -> dict[str, Any]:
        if not security["available"]:
            return {
                "available": False,
                "index": None,
                "band": None,
                "weights": dict(OVERALL_WEIGHTS),
                "reason": (
                    "no security analyzer produced results, so the engine will not "
                    f"report an overall indicator ({security['reason']})"
                ),
            }
        if quality["available"]:
            index = (
                OVERALL_WEIGHTS["security"] * security["index"]
                + OVERALL_WEIGHTS["quality"] * quality["index"]
            )
            weights = dict(OVERALL_WEIGHTS)
            reason = None
        else:
            index = security["index"]
            weights = {"security": 1.0, "quality": 0.0}
            reason = f"quality signal unavailable ({quality['reason']}); security only"
        return {
            "available": True,
            "index": round(index, 1),
            "band": _band(security["points"] * OVERALL_WEIGHTS["security"] + quality["points"] * OVERALL_WEIGHTS["quality"]),
            "weights": weights,
            "reason": reason,
            "degraded_analyzers": sorted(degraded),
        }


def _dimension(
    *,
    points: float,
    saturation: float,
    available: bool,
    reason: Optional[str],
    analyzer_names: Sequence[str],
    outcome_names: Sequence[str],
    findings: int,
) -> dict[str, Any]:
    index = round(100.0 * (1.0 - min(1.0, points / saturation)), 1) if available else None
    return {
        "available": available,
        "reason": reason,
        "findings": findings,
        "points": round(points, 2),
        "index": index,
        "band": _band(points),
        "analyzers": sorted(analyzer_names),
        "analyzers_with_results": sorted(outcome_names),
    }


def _band(points: float) -> str:
    for threshold, name in BAND_THRESHOLDS:
        if points <= threshold:
            return name
    return "high"


def _unavailable_reason(
    names: Sequence[str], outcomes_by_name: dict[str, AnalyzerOutcome], label: str
) -> str:
    if not names:
        return f"no {label} applies to the analysed languages"
    statuses = ", ".join(f"{name}={outcomes_by_name[name].status.value}" for name in sorted(names))
    return f"{label} did not produce results ({statuses})"
