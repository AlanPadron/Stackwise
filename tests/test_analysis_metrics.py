"""Metrics: objective counts, and "unavailable" kept distinct from zero."""

from pathlib import Path

from engine_builders import entry, finding, inventory, normalized, outcome

from app.analysis.analyzers.base import AnalyzerStatus
from app.analysis.config import AnalysisConfigOverrides, resolve_config
from app.analysis.metrics import MetricsCalculator
from app.analysis.normalize import NormalizationResult

ROOT = Path("/workspace/repo")

RADON_METRICS = {
    "complexity": {
        "available": True,
        "files_measured": 1,
        "blocks_measured": 3,
        "average": 8.0,
        "max": 25,
        "distribution": {"A": 1, "B": 1, "C": 1, "D": 0, "E": 0, "F": 0},
        "files": {"app.py": {"blocks": 3, "max": 25, "average": 8.0, "rank_counts": {}, "top_blocks": []}},
    },
    "maintainability": {
        "available": True,
        "files_measured": 1,
        "average": 70.0,
        "min": 70.0,
        "distribution": {"A": 1, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0},
        "files": {"app.py": {"mi": 70.0, "rank": "A"}},
    },
    "raw": {
        "available": True,
        "files_measured": 1,
        "totals": {"loc": 40, "lloc": 30, "sloc": 28, "comments": 4, "multi": 1, "blank": 8, "single_comments": 0},
        "files": {},
    },
}
RADON_METRICS_UNAVAILABLE = {
    "complexity": {"available": False},
    "maintainability": {"available": False},
    "raw": {"available": False},
}


def _calculator(*, outcomes, files, normalization=None, config=None, inventory_overrides=None):
    report = inventory(ROOT, files, **(inventory_overrides or {"discovered": len(files) + 2, "skipped": 2}))
    return MetricsCalculator(
        config=config or resolve_config(),
        inventory=report,
        outcomes=outcomes,
        normalization=normalization or NormalizationResult(),
        source_hash="hash",
        duration_seconds=1.5,
    ).calculate()


def test_counts_come_from_the_inventory_and_findings():
    files = (entry("app.py", lines=30), entry("pkg/util.py", lines=10))
    normalization = NormalizationResult(
        findings=(
            normalized(tool="ruff", rule_id="F401", category="dead_code", severity="low", file_path="app.py", line_start=1),
            normalized(tool="ruff", rule_id="F821", category="bug", severity="high", file_path="app.py", line_start=9),
            normalized(tool="bandit", rule_id="B602", category="security", severity="high", file_path="pkg/util.py", line_start=3),
        ),
        duplicates_removed=2,
        dropped=1,
        dropped_by_reason={"unsafe_or_missing_path": 1},
    )
    metrics = _calculator(
        outcomes=[
            outcome("ruff", findings=[finding()]),
            outcome("bandit", findings=[finding(tool="bandit")]),
            outcome("radon", status=AnalyzerStatus.UNAVAILABLE, version=None),
        ],
        files=files,
        normalization=normalization,
    )

    assert metrics["files"]["analyzed"] == 2
    assert metrics["files"]["discovered"] == 4
    assert metrics["files"]["skipped"] == 2
    assert metrics["lines"]["physical"] == 40
    assert metrics["lines"]["source"] is None  # radon produced no raw metrics
    assert metrics["lines"]["physical_by_language"] == {"python": 40}
    assert "newline count" in metrics["lines"]["method"]

    assert metrics["findings"]["total"] == 3
    assert metrics["findings"]["by_severity"] == {"critical": 0, "high": 2, "medium": 0, "low": 1, "info": 0}
    assert metrics["findings"]["by_category"]["security"] == 1
    assert metrics["findings"]["by_analyzer"] == {"bandit": 1, "ruff": 2}
    assert metrics["findings"]["files_with_findings"] == 2
    assert metrics["findings"]["findings_per_analyzed_file"] == 1.5
    assert metrics["findings"]["duplicates_removed"] == 2
    assert metrics["findings"]["dropped_invalid"] == 1
    assert metrics["findings"]["dropped_by_reason"] == {"unsafe_or_missing_path": 1}

    assert metrics["analyzers"]["applicable"] == 3
    assert metrics["analyzers"]["succeeded"] == 2
    assert metrics["analyzers"]["failed"] == 1
    assert metrics["analyzers"]["complete"] is False
    assert metrics["analyzers"]["items"]["radon"]["status"] == "unavailable"
    assert metrics["analyzers"]["items"]["radon"]["error_category"] == "analyzer_unavailable"


def test_radon_metrics_are_passed_through_but_not_as_findings():
    metrics = _calculator(
        outcomes=[outcome("radon", metrics=RADON_METRICS)],
        files=(entry("app.py", lines=40),),
    )
    assert metrics["complexity"]["max"] == 25
    assert metrics["maintainability"]["min"] == 70.0
    assert metrics["raw_source"]["totals"]["loc"] == 40
    assert metrics["lines"]["source"] == 28
    assert metrics["lines"]["logical"] == 30
    assert metrics["lines"]["comments"] == 4


def test_unavailable_measurements_are_null_not_zero():
    metrics = _calculator(
        outcomes=[outcome("radon", status=AnalyzerStatus.UNAVAILABLE, metrics=None)],
        files=(entry("app.py"),),
    )
    assert metrics["complexity"] is None
    assert metrics["maintainability"] is None
    assert metrics["raw_source"] is None
    assert metrics["lines"]["source"] is None


def test_per_file_rate_is_unavailable_without_analysed_files():
    metrics = _calculator(
        outcomes=[outcome("ruff", status=AnalyzerStatus.NOT_APPLICABLE)],
        files=(),
        inventory_overrides={"discovered": 3, "skipped": 3},
    )
    assert metrics["findings"]["findings_per_analyzed_file"] is None
    assert metrics["analyzers"]["skipped"] == 1
    assert metrics["analyzers"]["complete"] is True


def test_effective_limits_and_exclusions_are_recorded():
    config = resolve_config(
        AnalysisConfigOverrides(excluded_paths=["tests"], complexity_threshold=7, ruff_select=["F"])
    )
    metrics = _calculator(outcomes=[outcome()], files=(entry("app.py"),), config=config)

    limits = metrics["limits"]
    assert limits["complexity_threshold"] == 7
    assert limits["ruff_select"] == "F"
    assert metrics["exclusions"] == ["tests"]
    assert set(limits["overridden"]) == {"excluded_paths", "complexity_threshold", "ruff_select"}
    assert metrics["config_hash"] == config.hash()
    assert metrics["engine_version"] and metrics["config_version"]
    assert metrics["duration_seconds"] == 1.5
    assert metrics["source_hash"] == "hash"
