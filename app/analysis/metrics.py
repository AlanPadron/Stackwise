"""Project-level metrics: objective counts and measurements.

Design rules:

* **counts, not judgements** — anything derived (risk) lives in
  `app/analysis/risk.py`, and a metric that could not be measured is `None`, never
  `0`, so a missing radon is never read as "zero complexity";
* **documented method** — `lines.method` states how the line counts were
  obtained;
* **bounded JSON** — per-file detail is capped so one run cannot write an
  unbounded JSON blob into the database.

Counting method for lines: `radon raw`'s `sloc` (source lines of code, i.e.
statements + comments excluding blank lines) and `lloc` (logical lines) when
radon ran; otherwise the physical newline count of the analysed files
(`lines.physical`, always available).
"""

from typing import Any, Optional, Sequence

from app.analysis.analyzers.base import AnalyzerOutcome, AnalyzerStatus
from app.analysis.config import AnalysisConfig
from app.analysis.inventory import InventoryReport
from app.analysis.normalize import CATEGORIES, SEVERITIES, NormalizationResult

LOC_METHOD = (
    "lines.physical: newline count per analysed file (always available); "
    "lines.source/logical: sum of radon raw `sloc`/`lloc`, null when radon did not run"
)


class MetricsCalculator:
    """Builds the `AnalysisRun.metrics` document."""

    def __init__(
        self,
        *,
        config: AnalysisConfig,
        inventory: InventoryReport,
        outcomes: Sequence[AnalyzerOutcome],
        normalization: NormalizationResult,
        source_hash: Optional[str],
        duration_seconds: float,
    ):
        self._config = config
        self._inventory = inventory
        self._outcomes = tuple(outcomes)
        self._normalization = normalization
        self._source_hash = source_hash
        self._duration = duration_seconds

    def calculate(self) -> dict[str, Any]:
        return {
            "engine_version": self._config.engine_version,
            "config_version": self._config.config_version,
            "config_hash": self._config.hash(),
            "source_hash": self._source_hash,
            "duration_seconds": round(self._duration, 3),
            "languages": list(self._inventory.languages),
            "files": self._files(),
            "lines": self._lines(),
            "findings": self._findings(),
            "complexity": self._radon_block("complexity"),
            "maintainability": self._radon_block("maintainability"),
            "raw_source": self._radon_block("raw"),
            "analyzers": self._analyzers(),
            "limits": self._limits(),
            "exclusions": list(self._config.excluded_paths),
        }

    # --- sections ----------------------------------------------------------

    def _files(self) -> dict[str, Any]:
        stats = self._inventory.stats
        return {
            "discovered": stats.discovered,
            "analyzed": stats.analyzed,
            "skipped": stats.skipped,
            "unsupported_language": stats.unsupported,
            "failed": stats.failed,
            "directories": stats.directories,
            "directories_skipped": stats.directories_skipped,
            "symlinks_skipped": stats.symlinks_skipped,
            "total_bytes": stats.total_bytes,
            "file_count_limit_reached": stats.truncated,
            "skipped_by_reason": dict(sorted(stats.skipped_by_reason.items())),
            "failures": [{"path": path, "reason": reason} for path, reason in self._inventory.failures],
        }

    def _lines(self) -> dict[str, Any]:
        raw_totals = self._radon_totals()
        physical = sum(entry.line_count or 0 for entry in self._inventory.files)
        by_language: dict[str, int] = {}
        for entry in self._inventory.files:
            if entry.language:
                by_language[entry.language] = by_language.get(entry.language, 0) + (entry.line_count or 0)
        return {
            "physical": physical,
            "source": raw_totals.get("sloc") if raw_totals else None,
            "logical": raw_totals.get("lloc") if raw_totals else None,
            "comments": raw_totals.get("comments") if raw_totals else None,
            "physical_by_language": dict(sorted(by_language.items())),
            "method": LOC_METHOD,
        }

    def _findings(self) -> dict[str, Any]:
        findings = self._normalization.findings
        by_severity = {severity: 0 for severity in SEVERITIES}
        by_category = {category: 0 for category in CATEGORIES}
        by_analyzer: dict[str, int] = {}
        by_confidence = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
        files_with_findings: set[str] = set()

        for finding in findings:
            by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
            by_category[finding.category] = by_category.get(finding.category, 0) + 1
            by_analyzer[finding.tool] = by_analyzer.get(finding.tool, 0) + 1
            by_confidence[finding.confidence or "unknown"] = by_confidence.get(finding.confidence or "unknown", 0) + 1
            files_with_findings.add(finding.file_path)

        analyzed = self._inventory.stats.analyzed
        total = len(findings)
        return {
            "total": total,
            "by_severity": by_severity,
            "by_category": by_category,
            "by_analyzer": dict(sorted(by_analyzer.items())),
            "by_confidence": by_confidence,
            "files_with_findings": len(files_with_findings),
            "findings_per_analyzed_file": round(total / analyzed, 3) if analyzed else None,
            "duplicates_removed": self._normalization.duplicates_removed,
            "dropped_invalid": self._normalization.dropped,
            "dropped_by_reason": dict(sorted(self._normalization.dropped_by_reason.items())),
            "truncated": self._normalization.truncated,
        }

    def _analyzers(self) -> dict[str, Any]:
        items: dict[str, Any] = {}
        succeeded = 0
        failed = 0
        skipped = 0
        for outcome in self._outcomes:
            items[outcome.analyzer] = {
                "status": outcome.status.value,
                "version": outcome.version,
                "duration_seconds": round(outcome.duration_seconds, 3),
                "exit_code": outcome.exit_code,
                "findings": len(outcome.findings),
                "error_category": (
                    outcome.status.error_category.value if outcome.status.error_category else None
                ),
                "message": outcome.message,
                "truncated_output": outcome.truncated,
            }
            if outcome.succeeded:
                succeeded += 1
            elif outcome.status is AnalyzerStatus.NOT_APPLICABLE:
                skipped += 1
            else:
                failed += 1
        applicable = succeeded + failed + skipped
        return {
            "applicable": applicable,
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "complete": failed == 0,
            "items": items,
        }

    def _limits(self) -> dict[str, Any]:
        """The effective limits, so a stored run explains its own configuration."""
        return {
            "enabled_analyzers": list(self._config.enabled_analyzers),
            "ruff_select": self._config.ruff_select,
            "complexity_threshold": self._config.complexity_threshold,
            "complexity_high_threshold": self._config.complexity_high_threshold,
            "maintainability_min_rank": self._config.maintainability_min_rank,
            "max_files": self._config.max_file_count,
            "max_file_bytes": self._config.max_file_bytes,
            "max_extracted_bytes": self._config.max_extracted_bytes,
            "max_findings_per_run": self._config.max_findings_per_run,
            "max_analysis_duration_seconds": self._config.max_analysis_duration_seconds,
            "analyzer_timeout_seconds": self._config.analyzer_timeout_seconds,
            "overridden": list(self._config.overridden),
        }

    # --- radon passthrough -------------------------------------------------

    def _raw_metrics(self) -> Optional[dict[str, Any]]:
        for outcome in self._outcomes:
            if outcome.analyzer == "radon" and outcome.succeeded and outcome.metrics:
                return outcome.metrics
        return None

    def _radon_block(self, key: str) -> Optional[dict[str, Any]]:
        metrics = self._raw_metrics()
        if not metrics:
            return None
        block = metrics.get(key)
        if not isinstance(block, dict) or not block.get("available"):
            return None
        return block

    def _radon_totals(self) -> Optional[dict[str, int]]:
        block = self._radon_block("raw")
        if not block:
            return None
        totals = block.get("totals")
        return totals if isinstance(totals, dict) else None
