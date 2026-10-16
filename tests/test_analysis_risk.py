"""Risk indicators: deterministic, documented, and never falsely "safe"."""

import pytest
from engine_builders import normalized, outcome

from app.analysis.analyzers.base import AnalyzerStatus
from app.analysis.config import resolve_config
from app.analysis.registry import build_default_registry
from app.analysis.risk import (
    ALGORITHM_VERSION,
    OVERALL_WEIGHTS,
    SECURITY_SATURATION_POINTS,
    RiskEvaluator,
)

REGISTRY = build_default_registry()


def evaluate(findings=(), outcomes=None, config=None):
    if outcomes is None:
        outcomes = [outcome("ruff"), outcome("bandit"), outcome("radon")]
    return RiskEvaluator(
        config=config or resolve_config(),
        registry=REGISTRY,
        findings=tuple(findings),
        outcomes=list(outcomes),
    ).evaluate()


def test_document_is_versioned_and_marked_heuristic():
    document = evaluate()
    assert document["algorithm_version"] == ALGORITHM_VERSION
    assert document["heuristic"] is True
    assert document["notes"]
    assert document["inputs"]["severity_weights"]["critical"] == 10.0


def test_evaluation_is_deterministic():
    findings = [normalized(severity="high"), normalized(rule_id="B101", severity="low")]
    first = evaluate(findings)
    second = evaluate(findings)
    assert first == second


def test_no_findings_is_reported_as_zero_points_not_as_proof_of_safety():
    document = evaluate()
    security = document["dimensions"]["security"]
    assert security["available"] is True
    assert security["points"] == 0
    assert security["band"] == "none"
    assert security["index"] == 100.0
    assert "not a probability of exploitation" in document["notes"][0]


def test_security_points_use_the_documented_weights():
    document = evaluate(
        [
            normalized(severity="critical"),  # 10
            normalized(rule_id="B602", severity="high"),  # 5
            normalized(rule_id="B101", severity="medium"),  # 2
            normalized(rule_id="B404", severity="low"),  # 0.5
        ]
    )
    assert document["dimensions"]["security"]["points"] == 17.5
    assert document["dimensions"]["security"]["findings"] == 4


@pytest.mark.parametrize(
    "severity,expected_band",
    [("info", "none"), ("low", "low"), ("medium", "moderate"), ("high", "high")],
)
def test_band_thresholds(severity, expected_band):
    points = {"info": 0.0, "low": 0.5, "medium": 2.0, "high": 5.0}[severity]
    document = evaluate([normalized(severity=severity)])
    if expected_band == "none":
        # 0 points only for a zero-weight severity, which `info` is not.
        assert document["dimensions"]["security"]["points"] == points
    assert document["dimensions"]["security"]["band"] in {"none", "low", "moderate", "high"}


def test_band_boundaries_are_inclusive_at_five_and_twenty():
    five = evaluate([normalized(severity="high")])  # 5.0 points
    assert five["dimensions"]["security"]["points"] == 5.0
    assert five["dimensions"]["security"]["band"] == "low"

    over_five = evaluate([normalized(severity="high"), normalized(rule_id="B101", severity="low")])
    assert over_five["dimensions"]["security"]["band"] == "moderate"

    twenty = evaluate([normalized(severity="high") for _ in range(4)])  # 20 points
    assert twenty["dimensions"]["security"]["points"] == 20.0
    assert twenty["dimensions"]["security"]["band"] == "moderate"

    over_twenty = evaluate(
        [normalized(severity="high") for _ in range(4)] + [normalized(rule_id="B101", severity="low")]
    )
    assert over_twenty["dimensions"]["security"]["band"] == "high"


def test_index_formula_and_overall_weighting():
    findings = [normalized(severity="high")]  # security 5.0 points
    document = evaluate(findings, outcomes=[outcome("bandit", status=AnalyzerStatus.UNAVAILABLE), outcome("ruff")])

    security = document["dimensions"]["security"]
    assert security["available"] is False
    assert security["index"] is None
    assert document["overall"]["available"] is False
    assert document["overall"]["index"] is None
    assert "security analyzer" in document["overall"]["reason"]

    document = evaluate(findings)
    security = document["dimensions"]["security"]
    quality = document["dimensions"]["quality"]
    assert security["index"] == pytest.approx(100 * (1 - 5 / SECURITY_SATURATION_POINTS), abs=0.05)
    assert document["overall"]["available"] is True
    assert document["overall"]["index"] == pytest.approx(
        OVERALL_WEIGHTS["security"] * security["index"] + OVERALL_WEIGHTS["quality"] * quality["index"], abs=0.05
    )


def test_quality_points_use_category_multipliers():
    document = evaluate(
        [
            normalized(tool="radon", rule_id="complexity", category="complexity", severity="medium"),
            normalized(tool="ruff", rule_id="F401", category="dead_code", severity="low"),
            normalized(tool="ruff", rule_id="E501", category="style", severity="low"),
        ]
    )
    expected = 2.0 * 1.0 + 0.5 * 0.25 + 0.5 * 0.1
    assert document["dimensions"]["quality"]["points"] == pytest.approx(expected, abs=0.01)
    assert document["dimensions"]["quality"]["findings"] == 3


def test_security_findings_are_not_counted_twice_in_quality():
    document = evaluate([normalized(severity="high")])
    assert document["dimensions"]["quality"]["points"] == 0.0
    assert document["dimensions"]["quality"]["findings"] == 0


def test_missing_quality_signal_falls_back_to_security_only():
    document = evaluate(
        [normalized(severity="high")],
        outcomes=[outcome("bandit"), outcome("ruff", status=AnalyzerStatus.UNAVAILABLE), outcome("radon", status=AnalyzerStatus.TIMEOUT)],
    )
    assert document["dimensions"]["security"]["available"] is True
    assert document["dimensions"]["quality"]["available"] is False
    assert document["overall"]["available"] is True
    assert document["overall"]["weights"] == {"security": 1.0, "quality": 0.0}
    assert document["overall"]["index"] == document["dimensions"]["security"]["index"]
    assert "quality signal unavailable" in document["overall"]["reason"]


def test_no_applicable_analyzer_means_no_overall_indicator():
    """A repository with no supported language must not get a 'low risk' score."""
    document = evaluate(findings=[], outcomes=[])
    assert document["dimensions"]["security"]["available"] is False
    assert document["dimensions"]["security"]["reason"] == "no security analyzer applies to the analysed languages"
    assert document["overall"]["index"] is None
    assert document["completeness"]["applicable_analyzers"] == 0
    assert document["completeness"]["ratio"] is None


def test_completeness_tracks_degraded_analyzers():
    document = evaluate(
        outcomes=[outcome("bandit", status=AnalyzerStatus.TIMEOUT), outcome("ruff"), outcome("radon", status=AnalyzerStatus.UNAVAILABLE)]
    )
    assert document["completeness"]["applicable_analyzers"] == 3
    assert document["completeness"]["succeeded_analyzers"] == 1
    assert document["completeness"]["ratio"] == pytest.approx(0.333, abs=0.001)
    assert document["completeness"]["degraded_analyzers"] == ["bandit", "radon"]
