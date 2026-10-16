"""Bandit adapter: Python security analysis.

Invocation:

    bandit -f json -q <files…>

The process runs in the run's neutral working directory and receives absolute
paths, so the repository's own `.bandit`/`setup.cfg`/`pyproject.toml` is never
discovered. Bandit's severities are mapped as-is (`HIGH` → `high`,
`MEDIUM` → `medium`, `LOW` → `low`) and its confidence is kept as a **separate**
field: a heuristic security signal is not the same as a certainty. `critical` is
never produced by bandit — no analyzer in this engine claims it yet.

Bandit findings are *potential* issues, not proof of exploitability; the risk
evaluator treats them as one indicator among several (docs/ANALYSIS_ENGINE.md).

The raw `code` field (a source snippet) is deliberately **not** copied into the
finding: findings are returned to clients, and snippets can contain credentials.
"""

import json
from typing import Any, Optional

from app.analysis.analyzers.base import (
    AnalyzerContext,
    AnalyzerOutcome,
    AnalyzerStatus,
    RawFinding,
)
from app.analysis.redact import redact
from app.analysis.registry import AnalyzerSpec

SPEC = AnalyzerSpec(
    name="bandit",
    languages=frozenset({"python"}),
    category="security",
    capabilities=frozenset(
        {"security", "injection", "cryptography", "secrets", "subprocess", "deserialization"}
    ),
    executable="bandit",
)

EXIT_CLEAN = 0
EXIT_FINDINGS = 1

_SEVERITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNDEFINED": "info"}
_CONFIDENCE = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low", "UNDEFINED": None}


class BanditAnalyzer:
    name = SPEC.name

    def __init__(self, context: AnalyzerContext):
        self._context = context

    def analyze(self, context: AnalyzerContext) -> AnalyzerOutcome:
        if not context.paths:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.OK,
                version=context.runner.version(SPEC.executable),
                message="no eligible files",
            )

        executable = context.runner.resolve(SPEC.executable)
        version = context.runner.version(SPEC.executable)
        if executable is None:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.UNAVAILABLE,
                message="bandit is not installed",
            )

        argv = [
            executable,
            "--format",
            "json",
            "--quiet",
            *[context.absolute(path) for path in context.paths],
        ]
        result = context.runner.run(
            argv,
            timeout=context.config.analyzer_timeout_seconds,
            max_output_bytes=context.config.max_analyzer_output_bytes,
            cwd=context.cwd,
        )

        if not result.ok:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=result.status,
                version=version,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                message=result.message or _excerpt(result.stderr),
            )
        if result.truncated:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.OUTPUT_LIMIT,
                version=version,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                message="bandit output exceeded the configured limit",
                truncated=True,
            )
        if result.exit_code not in (EXIT_CLEAN, EXIT_FINDINGS):
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.EXECUTION_ERROR,
                version=version,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                message=_excerpt(result.stderr) or f"unexpected exit code {result.exit_code}",
            )

        findings, error = parse_bandit_json(result.stdout)
        if error is not None:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.INVALID_OUTPUT,
                version=version,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                message=error,
            )

        return AnalyzerOutcome(
            analyzer=SPEC.name,
            status=AnalyzerStatus.FINDINGS if findings else AnalyzerStatus.OK,
            findings=findings,
            version=version,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
        )


def build(context: AnalyzerContext) -> BanditAnalyzer:
    return BanditAnalyzer(context)


def parse_bandit_json(text: str) -> tuple[list[RawFinding], Optional[str]]:
    """Parse bandit's JSON report. Malformed entries are skipped, not fatal."""
    if not text.strip():
        return [], "bandit produced no output"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], "bandit output is not valid JSON"
    if not isinstance(payload, dict):
        return [], "bandit output is not a JSON object"

    results = payload.get("results")
    if results is None:
        return [], "bandit output has no 'results' key"
    if not isinstance(results, list):
        return [], "bandit 'results' is not a list"

    findings: list[RawFinding] = []
    for item in results:
        finding = _parse_item(item)
        if finding is not None:
            findings.append(finding)
    return findings, None


def _parse_item(item: Any) -> Optional[RawFinding]:
    if not isinstance(item, dict):
        return None
    filename = item.get("filename") or item.get("relative_path")
    if not isinstance(filename, str) or not filename:
        return None
    issue_text = item.get("issue_text")
    if not isinstance(issue_text, str) or not issue_text.strip():
        return None

    test_id = item.get("test_id") if isinstance(item.get("test_id"), str) else None
    test_name = item.get("test_name") if isinstance(item.get("test_name"), str) else None

    raw_severity = str(item.get("issue_severity", "")).upper()
    raw_confidence = str(item.get("issue_confidence", "")).upper()

    metadata: dict[str, Any] = {}
    if test_name:
        metadata["test_name"] = test_name
    if raw_severity:
        metadata["tool_severity"] = raw_severity
    if raw_confidence:
        metadata["tool_confidence"] = raw_confidence
    line_range = item.get("line_range")
    if isinstance(line_range, list) and line_range:
        metadata["line_range"] = [value for value in line_range if isinstance(value, int)][:50]

    references: dict[str, Any] = {}
    more_info = item.get("more_info")
    if isinstance(more_info, str) and more_info.startswith(("http://", "https://")):
        references["more_info"] = more_info
    cwe = item.get("issue_cwe")
    if isinstance(cwe, dict) and isinstance(cwe.get("id"), int):
        references["cwe"] = f"CWE-{cwe['id']}"
        link = cwe.get("link")
        if isinstance(link, str) and link.startswith(("http://", "https://")):
            references["cwe_url"] = link

    return RawFinding(
        tool=SPEC.name,
        rule_id=test_id,
        category="security",
        severity=_SEVERITY.get(raw_severity, "info"),
        confidence=_CONFIDENCE.get(raw_confidence),
        title=_title(test_id, test_name),
        description=issue_text,
        file_path=filename,
        line_start=_positive_int(item.get("line_number")),
        line_end=_positive_int(item.get("line_number")),
        column_start=_positive_int(item.get("col_offset")),
        column_end=_positive_int(item.get("end_col_offset")),
        references=references or None,
        metadata=metadata or None,
    )


def _title(test_id: Optional[str], test_name: Optional[str]) -> str:
    human = test_name.replace("_", " ").strip().capitalize() if test_name else "Security issue"
    return f"{test_id}: {human}" if test_id else human


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _excerpt(text: str) -> str:
    return redact(text.strip().replace("\n", " "), limit=300)
