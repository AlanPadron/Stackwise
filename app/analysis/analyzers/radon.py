"""Radon adapter: complexity and maintainability metrics for Python.

Three invocations, each with its own JSON output:

    radon cc  -s -j <files…>   cyclomatic complexity per function/method/class
    radon mi  -j <files…>      maintainability index per file
    radon raw -j <files…>      raw source metrics: loc, lloc, sloc, comments, …

Metrics and findings are kept strictly apart, because they mean different
things:

* **metrics** always come back — they are measurements, and they are stored under
  `AnalysisRun.metrics`, not as findings;
* **findings** are derived from two documented thresholds:
    - a block whose cyclomatic complexity is at or above
      `complexity_threshold` (default 11 → radon rank C or worse) is a
      `complexity` finding. High complexity makes code hard to test and reason
      about; it is *not* proof of a defect.
    - a file whose maintainability index ranks at or below
      `maintainability_min_rank` (default B) is a `maintainability` finding.

Maintainability index (radon) is `171 − 5.2·ln(V) − 0.23·G − 16.2·ln(LOC) −
50·sin(√(2.46·rad))`, where V = Halstead volume, G = total cyclomatic complexity,
LOC = logical lines of code, rad = comments/sloc ratio; radon ranks it A
(≥20), B (10–19), C (<10). LOC here means logical lines, so a file full of long
comments scores worse than its physical line count suggests — a known limitation
of the metric, not a property of the code.
"""

import json
from typing import Any, Optional

from app.analysis.analyzers.base import (
    AnalyzerContext,
    AnalyzerOutcome,
    AnalyzerStatus,
    RawFinding,
)
from app.analysis.paths import normalize_relative_path
from app.analysis.redact import redact
from app.analysis.registry import AnalyzerSpec

SPEC = AnalyzerSpec(
    name="radon",
    languages=frozenset({"python"}),
    category="metrics",
    capabilities=frozenset({"complexity", "maintainability", "raw-metrics"}),
    executable="radon",
)

RANK_ORDER = ("A", "B", "C", "D", "E", "F")
_RAW_KEYS = ("loc", "lloc", "sloc", "comments", "multi", "blank", "single_comments")
_MAX_FILES_IN_METRICS = 500


class RadonAnalyzer:
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
                message="radon is not installed",
            )

        absolute = [context.absolute(path) for path in context.paths]
        started_total = 0.0
        notes: list[str] = []
        metrics: dict[str, Any] = {}
        findings: list[RawFinding] = []
        exit_code: Optional[int] = None

        complexity_result = self._run(context, executable, ["cc", "-s", "-j", *absolute])
        started_total += complexity_result.duration_seconds
        exit_code = complexity_result.exit_code
        if complexity_result.status is not AnalyzerStatus.OK:
            return _failure(complexity_result, version, "radon cc")
        blocks, errors, parse_error = parse_complexity_json(complexity_result.stdout)
        if parse_error is not None:
            return AnalyzerOutcome(
                analyzer=SPEC.name,
                status=AnalyzerStatus.INVALID_OUTPUT,
                version=version,
                duration_seconds=started_total,
                exit_code=exit_code,
                message=f"radon cc: {parse_error}",
            )
        metrics["complexity"] = _complexity_metrics(context, blocks, errors)
        findings.extend(_complexity_findings(context, blocks))

        maintainability_result = self._run(context, executable, ["mi", "-j", *absolute])
        started_total += maintainability_result.duration_seconds
        if maintainability_result.status is not AnalyzerStatus.OK:
            notes.append(f"radon mi: {maintainability_result.message or 'failed'}")
            metrics["maintainability"] = {"available": False}
        else:
            values, mi_error = parse_maintainability_json(maintainability_result.stdout)
            if mi_error is not None:
                notes.append(f"radon mi: {mi_error}")
                metrics["maintainability"] = {"available": False}
            else:
                metrics["maintainability"] = _maintainability_metrics(context, values)
                findings.extend(_maintainability_findings(context, values))

        raw_result = self._run(context, executable, ["raw", "-j", *absolute])
        started_total += raw_result.duration_seconds
        if raw_result.status is not AnalyzerStatus.OK:
            notes.append(f"radon raw: {raw_result.message or 'failed'}")
            metrics["raw"] = {"available": False}
        else:
            values, raw_error = parse_raw_json(raw_result.stdout)
            if raw_error is not None:
                notes.append(f"radon raw: {raw_error}")
                metrics["raw"] = {"available": False}
            else:
                metrics["raw"] = _raw_metrics(context, values)

        return AnalyzerOutcome(
            analyzer=SPEC.name,
            status=AnalyzerStatus.FINDINGS if findings else AnalyzerStatus.OK,
            findings=findings,
            metrics=metrics,
            version=version,
            duration_seconds=started_total,
            exit_code=exit_code,
            message="; ".join(notes) or None,
        )

    def _run(self, context: AnalyzerContext, executable: str, args: list[str]):
        return context.runner.run(
            [executable, *args],
            timeout=context.config.analyzer_timeout_seconds,
            max_output_bytes=context.config.max_analyzer_output_bytes,
            cwd=context.cwd,
        )


def build(context: AnalyzerContext) -> RadonAnalyzer:
    return RadonAnalyzer(context)


def _failure(result, version: Optional[str], label: str) -> AnalyzerOutcome:
    return AnalyzerOutcome(
        analyzer=SPEC.name,
        status=result.status,
        version=version,
        duration_seconds=result.duration_seconds,
        exit_code=result.exit_code,
        message=f"{label}: {result.message or redact(result.stderr, limit=200)}",
    )


# --- parsing -----------------------------------------------------------------


def _load(text: str, label: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not text.strip():
        return None, f"{label} produced no output"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, f"{label} output is not valid JSON"
    if not isinstance(payload, dict):
        return None, f"{label} output is not a JSON object"
    return payload, None


def parse_complexity_json(
    text: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], Optional[str]]:
    """Return `(blocks_by_path, errors_by_path, parse_error)` for `radon cc -j`."""
    payload, error = _load(text, "radon cc")
    if error is not None:
        return {}, {}, error

    blocks_by_path: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for path, contents in payload.items():
        if not isinstance(path, str):
            continue
        if isinstance(contents, dict) and "error" in contents:
            errors[path] = redact(contents.get("error"), limit=200)
            continue
        if not isinstance(contents, list):
            errors[path] = "unexpected block list"
            continue
        blocks_by_path[path] = [block for block in _flatten_blocks(contents) if block is not None]
    return blocks_by_path, errors, None


def _flatten_blocks(blocks: Any, classname: Optional[str] = None):
    if not isinstance(blocks, list):
        return
    for block in blocks:
        if not isinstance(block, dict):
            continue
        current_class = block.get("classname") or classname
        yield _block_view(block, current_class)
        # A class block carries its methods; closures are skipped on purpose
        # (their complexity is already attributed to the enclosing block).
        yield from _flatten_blocks(block.get("methods"), current_class)


def _block_view(block: dict[str, Any], classname: Optional[str]) -> Optional[dict[str, Any]]:
    complexity = block.get("complexity")
    if not isinstance(complexity, int):
        return None
    name = block.get("name") if isinstance(block.get("name"), str) else None
    if name is None:
        return None
    block_type = block.get("type") if isinstance(block.get("type"), str) else "function"
    if block_type == "class":
        return None
    return {
        "name": name,
        "classname": classname if isinstance(classname, str) else None,
        "type": block_type,
        "line": _positive_int(block.get("lineno")),
        "end_line": _positive_int(block.get("endline")),
        "complexity": complexity,
        "rank": _rank(block.get("rank")),
    }


def parse_maintainability_json(text: str) -> tuple[dict[str, dict[str, Any]], Optional[str]]:
    """Return `{path: {"mi": float, "rank": str}}` for `radon mi -j`."""
    payload, error = _load(text, "radon mi")
    if error is not None:
        return {}, error
    values: dict[str, dict[str, Any]] = {}
    for path, contents in payload.items():
        if not isinstance(path, str) or not isinstance(contents, dict):
            continue
        mi = contents.get("mi")
        if not isinstance(mi, (int, float)) or isinstance(mi, bool):
            continue
        values[path] = {"mi": round(float(mi), 2), "rank": _rank(contents.get("rank"))}
    return values, None


def parse_raw_json(text: str) -> tuple[dict[str, dict[str, int]], Optional[str]]:
    """Return `{path: {loc, lloc, sloc, comments, multi, blank, …}}` for `radon raw -j`."""
    payload, error = _load(text, "radon raw")
    if error is not None:
        return {}, error
    values: dict[str, dict[str, int]] = {}
    for path, contents in payload.items():
        if not isinstance(path, str) or not isinstance(contents, dict):
            continue
        values[path] = {
            key: int(contents[key])
            for key in _RAW_KEYS
            if isinstance(contents.get(key), int) and not isinstance(contents.get(key), bool)
        }
    return values, None


# --- findings ----------------------------------------------------------------


def _complexity_findings(
    context: AnalyzerContext, blocks_by_path: dict[str, list[dict[str, Any]]]
) -> list[RawFinding]:
    threshold = context.config.complexity_threshold
    high = context.config.complexity_high_threshold
    findings: list[RawFinding] = []
    for path, blocks in blocks_by_path.items():
        relative = normalize_relative_path(context.root, path)
        if relative is None:
            continue
        for block in sorted(blocks, key=lambda item: (item["line"] or 0, item["name"])):
            if block["complexity"] < threshold:
                continue
            qualname = f"{block['classname']}.{block['name']}" if block["classname"] else block["name"]
            findings.append(
                RawFinding(
                    tool=SPEC.name,
                    rule_id="complexity",
                    category="complexity",
                    severity="high" if block["complexity"] >= high else "medium",
                    title="High cyclomatic complexity",
                    description=(
                        f"{qualname} has a cyclomatic complexity of {block['complexity']} "
                        f"(rank {block['rank']}); the configured threshold is {threshold}."
                    ),
                    file_path=relative,
                    line_start=block["line"],
                    line_end=block["end_line"],
                    metadata={
                        "complexity": block["complexity"],
                        "rank": block["rank"],
                        "block_type": block["type"],
                        "symbol": qualname,
                    },
                    identity=qualname,
                )
            )
    return findings


def _maintainability_findings(
    context: AnalyzerContext, values: dict[str, dict[str, Any]]
) -> list[RawFinding]:
    floor = RANK_ORDER.index(context.config.maintainability_min_rank)
    findings: list[RawFinding] = []
    for path, value in values.items():
        relative = normalize_relative_path(context.root, path)
        if relative is None:
            continue
        rank = value["rank"]
        if RANK_ORDER.index(rank) < floor:
            continue
        severity = {"A": "info", "B": "low", "C": "medium"}.get(rank, "low")
        findings.append(
            RawFinding(
                tool=SPEC.name,
                rule_id="maintainability-index",
                category="maintainability",
                severity=severity,
                title="Low maintainability index",
                description=(
                    f"Maintainability index {value['mi']} (rank {rank}); radon ranks below "
                    f"{context.config.maintainability_min_rank} are reported."
                ),
                file_path=relative,
                line_start=None,
                metadata={"mi": value["mi"], "rank": rank},
                identity="mi",
            )
        )
    return findings


# --- metrics -----------------------------------------------------------------


def _relative(context: AnalyzerContext, path: str) -> Optional[str]:
    if not isinstance(path, str):
        return None
    return normalize_relative_path(context.root, path)


def _complexity_metrics(
    context: AnalyzerContext,
    blocks_by_path: dict[str, list[dict[str, Any]]],
    errors: dict[str, str],
) -> dict[str, Any]:
    distribution = {rank: 0 for rank in RANK_ORDER}
    per_file: dict[str, Any] = {}
    complexities: list[int] = []

    for path, blocks in blocks_by_path.items():
        relative = _relative(context, path)
        if relative is None:
            continue
        values = [block["complexity"] for block in blocks]
        complexities.extend(values)
        for block in blocks:
            distribution[block["rank"]] += 1
        top = sorted(blocks, key=lambda item: (-item["complexity"], item["line"] or 0))[:5]
        per_file[relative] = {
            "blocks": len(values),
            "max": max(values) if values else None,
            "average": round(sum(values) / len(values), 2) if values else None,
            "rank_counts": _rank_counts(blocks),
            "top_blocks": [
                {
                    "symbol": f"{block['classname']}.{block['name']}" if block["classname"] else block["name"],
                    "line": block["line"],
                    "complexity": block["complexity"],
                    "rank": block["rank"],
                }
                for block in top
            ],
        }

    return {
        "available": True,
        "files_measured": len(per_file),
        "blocks_measured": len(complexities),
        "average": round(sum(complexities) / len(complexities), 2) if complexities else None,
        "max": max(complexities) if complexities else None,
        "distribution": distribution,
        "unparsable_files": _bounded(
            {path: message for path, message in errors.items()}, _MAX_FILES_IN_METRICS
        ),
        "files": _bounded(per_file, _MAX_FILES_IN_METRICS),
    }


def _maintainability_metrics(
    context: AnalyzerContext, values: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    distribution = {rank: 0 for rank in RANK_ORDER}
    per_file: dict[str, Any] = {}
    measured: list[float] = []
    for path, value in values.items():
        relative = _relative(context, path)
        if relative is None:
            continue
        per_file[relative] = {"mi": value["mi"], "rank": value["rank"]}
        distribution[value["rank"]] += 1
        measured.append(value["mi"])
    return {
        "available": True,
        "files_measured": len(per_file),
        "average": round(sum(measured) / len(measured), 2) if measured else None,
        "min": min(measured) if measured else None,
        "distribution": distribution,
        "files": _bounded(per_file, _MAX_FILES_IN_METRICS),
    }


def _raw_metrics(context: AnalyzerContext, values: dict[str, dict[str, int]]) -> dict[str, Any]:
    per_file: dict[str, Any] = {}
    totals = {key: 0 for key in _RAW_KEYS}
    for path, metrics in values.items():
        relative = _relative(context, path)
        if relative is None:
            continue
        per_file[relative] = metrics
        for key in _RAW_KEYS:
            totals[key] += metrics.get(key, 0)
    return {
        "available": True,
        "files_measured": len(per_file),
        "totals": totals,
        "files": _bounded(per_file, _MAX_FILES_IN_METRICS),
    }


def _rank_counts(blocks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {rank: 0 for rank in RANK_ORDER}
    for block in blocks:
        counts[block["rank"]] += 1
    return counts


def _bounded(values: dict[str, Any], limit: int) -> dict[str, Any]:
    if len(values) <= limit:
        return values
    trimmed = dict(sorted(values.items())[:limit])
    trimmed["_truncated"] = True
    return trimmed


def _rank(value: Any) -> str:
    if isinstance(value, str) and value.upper() in RANK_ORDER:
        return value.upper()
    return "F"


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
