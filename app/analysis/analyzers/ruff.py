"""Ruff adapter: Python linting and defect detection.

Invocation (documented in docs/ANALYSIS_ENGINE.md → Analyzers):

    ruff check --isolated --no-cache --output-format=json --select <rules> <files…>

`--isolated` ignores every configuration file in the repository (a repository
must not be able to change what the platform checks), `--select` is the
deliberate, versioned rule set (default `E4,E7,E9,F,B`), and `--no-cache` keeps
ruff from writing a cache into the workspace. Output is ruff's JSON, never its
human-readable text.

Severity mapping (ruff has no severities of its own — this table is the policy):

    high    invalid-syntax, F811/F821/F822/F823 (redefinitions, undefined or
            mis-used names), E902 (unreadable file)
    medium  B* (flake8-bugbear: likely bugs) and the statement-level mistakes
            E711/E712/E713/E714/E721/E722/E731 (e.g. a bare `except`)
    low     everything else — hygiene such as unused imports (F401) or unused
            variables (F841)

Exit codes: 0 = clean, 1 = findings (a normal result, not a failure), 2 = ruff
could not run (bad configuration or a usage error).
"""

import json
import re
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
    name="ruff",
    languages=frozenset({"python"}),
    category="lint",
    capabilities=frozenset({"lint", "bug-risk", "unused-code", "import-hygiene"}),
    executable="ruff",
)

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

_HIGH_CODES = frozenset({"invalid-syntax", "E902", "E999", "F811", "F821", "F822", "F823"})
# Statement-level mistakes that are behaviour bugs rather than formatting:
# comparison to None, bare `except`, assignment to a lambda.
_MEDIUM_CODES = frozenset({"E711", "E712", "E713", "E714", "E721", "E722", "E731"})
# flake8-bandit rules are `S` + digits (`S602`); `SIM`/`SLF`/`SLOT` are not.
_SECURITY_CODE = re.compile(r"^S\d+$")
# Unused imports/variables: real hygiene noise, not behaviour.
_DEAD_CODE_CODES = frozenset({"F401", "F841"})
# The printf / f-string family (F50x, F541) is formatting hygiene.
_FORMATTING_CODES = frozenset(
    {"F501", "F502", "F503", "F504", "F505", "F506", "F507", "F508", "F509", "F541"}
)
_STYLE_PREFIXES = ("E4", "E5", "E7", "C4", "SIM", "UP", "I", "RUF", "PERF", "T20", "DTZ", "LOG", "G", "ERA", "PTH", "PT", "Q", "EM", "FA", "TD", "FURB")
_BUG_PREFIXES = ("B", "E9", "F8", "F7", "F6", "TRY", "RET", "PIE", "ARG", "TID")


class RuffAnalyzer:
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
                version=None,
                message="ruff is not installed",
            )

        argv = [
            executable,
            "check",
            "--isolated",
            "--no-cache",
            "--output-format=json",
            "--select",
            context.config.ruff_select,
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
                message="ruff output exceeded the configured limit",
                truncated=True,
            )
        if result.exit_code == EXIT_ERROR:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=_classify_error_exit(result.stderr),
                version=version,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                message=_excerpt(result.stderr),
            )
        if result.exit_code not in (EXIT_CLEAN, EXIT_FINDINGS):
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.EXECUTION_ERROR,
                version=version,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                message=f"unexpected exit code {result.exit_code}",
            )

        findings, error = parse_ruff_json(result.stdout)
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


def build(context: AnalyzerContext) -> RuffAnalyzer:
    return RuffAnalyzer(context)


def parse_ruff_json(text: str) -> tuple[list[RawFinding], Optional[str]]:
    """Parse ruff's `--output-format=json` payload.

    Malformed output yields `(findings_so_far, reason)`; a single unusable entry
    is skipped rather than discarding the rest of the report.
    """
    if not text.strip():
        return [], "ruff produced no output"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], "ruff output is not valid JSON"
    if not isinstance(payload, list):
        return [], "ruff output is not a JSON array"

    findings: list[RawFinding] = []
    for item in payload:
        finding = _parse_item(item)
        if finding is not None:
            findings.append(finding)
    return findings, None


def _parse_item(item: Any) -> Optional[RawFinding]:
    if not isinstance(item, dict):
        return None
    message = item.get("message")
    if not isinstance(message, str) or not message.strip():
        return None
    code = item.get("code")
    if not isinstance(code, str) or not code:
        code = None
    filename = item.get("filename")
    if not isinstance(filename, str) or not filename:
        return None

    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    end_location = item.get("end_location") if isinstance(item.get("end_location"), dict) else {}

    metadata: dict[str, Any] = {}
    if code:
        metadata["ruff_rule"] = code
    if isinstance(item.get("noqa_row"), int):
        metadata["noqa_row"] = item["noqa_row"]
    fix = item.get("fix")
    if isinstance(fix, dict):
        metadata["fix_available"] = not fix.get("applicability") == "display"

    references: dict[str, Any] = {}
    url = item.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        references["rule_url"] = url

    return RawFinding(
        tool=SPEC.name,
        rule_id=code,
        category=_category(code),
        severity=_severity(code, message),
        confidence=None,  # ruff does not report confidence
        title=f"Ruff {code}" if code else "Ruff syntax error",
        description=message,
        file_path=filename,
        line_start=_positive_int(location.get("row")),
        column_start=_positive_int(location.get("column")),
        line_end=_positive_int(end_location.get("row")),
        column_end=_positive_int(end_location.get("column")),
        references=references or None,
        metadata=metadata or None,
    )


def _severity(code: Optional[str], message: str) -> str:
    if code is None:
        return "high" if message.lower().startswith("syntaxerror") else "low"
    if code in _HIGH_CODES:
        return "high"
    if code in _MEDIUM_CODES or _SECURITY_CODE.match(code):
        return "medium"
    if code.startswith("E9") or code.startswith("F82"):
        return "high"
    if code.startswith(_BUG_PREFIXES):
        return "medium"
    return "low"


def _category(code: Optional[str]) -> str:
    if code is None:
        return "bug"
    if code in _DEAD_CODE_CODES:
        return "dead_code"
    if code in _HIGH_CODES or code in _MEDIUM_CODES or code.startswith("E9"):
        return "bug"
    if _SECURITY_CODE.match(code):
        return "security"
    if code in _FORMATTING_CODES or code.startswith(_STYLE_PREFIXES):
        return "style"
    if code.startswith(_BUG_PREFIXES) or code.startswith("F"):
        return "bug"
    return "other"


def _classify_error_exit(stderr: str) -> AnalyzerStatus:
    """Tell a configuration mistake from a genuine execution error (exit code 2)."""
    lowered = stderr.lower()
    config_markers = ("unknown rule", "invalid", "unexpected argument", "usage:", "no such option")
    return AnalyzerStatus.INVALID_CONFIG if any(m in lowered for m in config_markers) else AnalyzerStatus.EXECUTION_ERROR


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _excerpt(text: str) -> str:
    return redact(text.strip().replace("\n", " "), limit=300) or "ruff failed"
