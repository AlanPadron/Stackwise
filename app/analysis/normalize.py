"""Finding normalisation: one canonical shape, stable fingerprints, deduplication.

Everything a client can see about a finding is decided here:

* paths become repository-relative (a `/tmp/stackwise_run_…/…` path never leaves
  the engine, and an absolute path outside the workspace drops the finding);
* severity/confidence/category are constrained to their canonical vocabularies
  (an unknown tool value degrades to `info`/`other` and is preserved in metadata
  rather than being silently accepted);
* text is redacted and length-bounded, metadata is JSON-safe and bounded;
* a `fingerprint` is derived from tool, rule, category, path, line and a
  rule-specific identity — never from a source snippet, so it cannot leak code.

Deduplication collapses identical fingerprints produced within one run (a tool
that reports the same issue twice). Findings from *different* analyzers are never
merged, even at the same line: two tools reporting at one location are two
different problems.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from app.analysis.analyzers.base import AnalyzerOutcome, RawFinding
from app.analysis.paths import normalize_relative_path
from app.analysis.redact import is_jsonable, redact, redact_url, sanitize_json

SEVERITIES = ("critical", "high", "medium", "low", "info")
CONFIDENCES = ("high", "medium", "low")
CATEGORIES = (
    "security",
    "bug",
    "complexity",
    "maintainability",
    "style",
    "dead_code",
    "performance",
    "other",
)

_MAX_TITLE = 200
_MAX_MESSAGE = 2000
_MAX_RULE_ID = 64
_MAX_LINE = 10_000_000


@dataclass(frozen=True)
class NormalizedFinding:
    tool: str
    rule_id: Optional[str]
    category: str
    severity: str
    confidence: Optional[str]
    title: str
    message: str
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    column_start: Optional[int]
    column_end: Optional[int]
    fingerprint: str
    references: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None

    def as_row(self, analysis_run_id, project_id) -> dict[str, Any]:
        """Column mapping for a bulk insert into `findings`."""
        return {
            "analysis_run_id": analysis_run_id,
            "project_id": project_id,
            "tool": self.tool,
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "title": self.title,
            "message": self.message,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "column_start": self.column_start,
            "column_end": self.column_end,
            "fingerprint": self.fingerprint,
            "references": self.references,
            "metadata": self.metadata,
        }


@dataclass
class NormalizationResult:
    findings: tuple[NormalizedFinding, ...] = ()
    duplicates_removed: int = 0
    dropped: int = 0
    dropped_by_reason: dict[str, int] = field(default_factory=dict)
    truncated: bool = False

    def record_drop(self, reason: str) -> None:
        self.dropped += 1
        self.dropped_by_reason[reason] = self.dropped_by_reason.get(reason, 0) + 1


class FindingNormalizer:
    """Turns analyzer outcomes into canonical, deduplicated findings."""

    def __init__(self, root: Path, *, max_findings: int):
        self._root = root
        self._max_findings = max_findings

    def normalize_all(self, outcomes: Iterable[AnalyzerOutcome]) -> NormalizationResult:
        result = NormalizationResult()
        collected: list[NormalizedFinding] = []
        seen: set[str] = set()

        for outcome in outcomes:
            if not outcome.succeeded:
                # A failed analyzer's partial output is not trusted.
                continue
            for raw in outcome.findings:
                normalized, reason = _normalize(raw, root=self._root)
                if normalized is None:
                    result.record_drop(reason or "invalid_finding")
                    continue
                if normalized.fingerprint in seen:
                    result.duplicates_removed += 1
                    continue
                seen.add(normalized.fingerprint)
                if len(collected) >= self._max_findings:
                    result.truncated = True
                    result.record_drop("findings_limit_reached")
                    continue
                collected.append(normalized)

        result.findings = tuple(collected)
        return result

    def normalize_one(self, raw: RawFinding) -> Optional[NormalizedFinding]:
        """Normalise one raw finding, or return `None` when it is unusable."""
        return _normalize(raw, root=self._root)[0]


def _normalize(raw: RawFinding, *, root: Path) -> tuple[Optional[NormalizedFinding], Optional[str]]:
    """Normalise one raw finding; the second element explains a `None`."""
    tool = redact(raw.tool, limit=_MAX_RULE_ID).strip()
    if not tool:
        return None, "missing_tool"

    file_path = normalize_relative_path(root, raw.file_path)
    if file_path is None:
        return None, "unsafe_or_missing_path"

    title = redact(raw.title, limit=_MAX_TITLE).strip()
    message = redact(raw.description, limit=_MAX_MESSAGE).strip()
    if not title and not message:
        return None, "empty_text"
    title = title or message[:_MAX_TITLE]
    message = message or title

    severity_raw = str(raw.severity or "").strip().lower()
    severity = severity_raw if severity_raw in SEVERITIES else "info"
    category_raw = str(raw.category or "").strip().lower()
    category = category_raw if category_raw in CATEGORIES else "other"
    confidence_raw = str(raw.confidence or "").strip().lower()
    confidence = confidence_raw if confidence_raw in CONFIDENCES else None
    rule_id = redact(raw.rule_id, limit=_MAX_RULE_ID).strip() or None

    line_start = _line(raw.line_start)
    line_end = _line(raw.line_end)
    if line_end is not None and line_start is not None and line_end < line_start:
        line_end = None
    column_start = _column(raw.column_start)
    column_end = _column(raw.column_end)

    metadata = sanitize_json(raw.metadata, max_bytes=4000)
    if metadata is None:
        metadata = {}
    if severity_raw and severity_raw != severity:
        metadata["tool_severity"] = redact(severity_raw, limit=16)
    if category_raw and category_raw != category:
        metadata["tool_category"] = redact(category_raw, limit=32)
    # Sanitised again *after* the tool_* notes were added, so the byte budget
    # covers what is actually stored.
    metadata = sanitize_json(metadata, max_bytes=4000)

    references = _references(raw.references)
    fingerprint = build_fingerprint(
        tool=tool,
        rule_id=rule_id,
        category=category,
        file_path=file_path,
        line_start=line_start,
        identity=raw.identity,
    )

    return (
        NormalizedFinding(
            tool=tool,
            rule_id=rule_id,
            category=category,
            severity=severity,
            confidence=confidence,
            title=title,
            message=message,
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            column_start=column_start,
            column_end=column_end,
            fingerprint=fingerprint,
            references=references,
            metadata=metadata,
        ),
        None,
    )


def build_fingerprint(
    *,
    tool: str,
    rule_id: Optional[str],
    category: str,
    file_path: str,
    line_start: Optional[int],
    identity: Optional[str] = None,
) -> str:
    """Stable sha256 (32 hex chars) over non-source, non-secret identity fields."""
    payload = "\x00".join(
        [
            tool,
            rule_id or "",
            category,
            file_path,
            str(line_start) if line_start is not None else "",
            redact(identity, limit=120) if identity else "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8", "surrogateescape")).hexdigest()[:32]


# Non-URL references a tool may legitimately provide (e.g. bandit's `CWE-78`).
_SAFE_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,31}$")


def _references(raw: Optional[dict[str, Any]]) -> Optional[dict[str, str]]:
    """Keep http(s) links and short opaque identifiers; drop everything else."""
    if not raw or not isinstance(raw, dict):
        return None
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not is_jsonable(value):
            continue
        if isinstance(value, str):
            url = redact_url(value)
            if url is not None:
                cleaned[redact(key, limit=32)] = url
            elif _SAFE_REFERENCE.match(value):
                cleaned[redact(key, limit=32)] = redact(value, limit=64)
        elif isinstance(value, (int, float, bool)):
            cleaned[redact(key, limit=32)] = str(value)
    return cleaned or None


def _line(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0 or value > _MAX_LINE:
        return None
    return value


def _column(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0 or value > _MAX_LINE:
        return None
    return value
