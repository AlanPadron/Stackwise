"""Analyzer adapters: parsing, severity mapping, registry, controlled execution."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from app.analysis.analyzers import bandit as bandit_module
from app.analysis.analyzers import radon as radon_module
from app.analysis.analyzers import ruff as ruff_module
from app.analysis.analyzers.base import AnalyzerContext, AnalyzerStatus
from app.analysis.config import resolve_config
from app.analysis.registry import AnalyzerSpec, AnalyzerRegistry, build_default_registry
from app.analysis.runner import AnalyzerRunner, ProcessLimits

RUFF_PAYLOAD = json.dumps(
    [
        {
            "code": "F401",
            "message": "`os` imported but unused",
            "filename": "/ws/app.py",
            "location": {"row": 1, "column": 8},
            "end_location": {"row": 1, "column": 10},
            "fix": {"applicability": "safe", "edits": []},
            "url": "https://docs.astral.sh/ruff/rules/unused-import",
            "noqa_row": 1,
        },
        {
            "code": "F821",
            "message": "Undefined name `undefined_name`",
            "filename": "/ws/app.py",
            "location": {"row": 10, "column": 12},
            "end_location": {"row": 10, "column": 26},
        },
        {
            "code": "E722",
            "message": "Do not use bare `except`",
            "filename": "/ws/app.py",
            "location": {"row": 8, "column": 5},
            "end_location": {"row": 8, "column": 10},
        },
        {
            "code": "B006",
            "message": "Do not use mutable data structures for argument defaults",
            "filename": "/ws/app.py",
            "location": {"row": 3, "column": 1},
            "end_location": {"row": 3, "column": 20},
        },
        {"code": "SIM101", "message": "Multiple isinstance calls", "filename": "/ws/app.py", "location": {"row": 4, "column": 1}},
        {"code": "F541", "message": "f-string without any placeholders", "filename": "/ws/app.py", "location": {"row": 5, "column": 1}},
        {"code": "invalid-syntax", "message": "Expected an expression", "filename": "/ws/broken.py", "location": {"row": 1, "column": 1}},
        {"message": "", "filename": "/ws/app.py"},
        "not-a-report-entry",
        {"code": "F401", "message": "no filename"},
    ]
)

BANDIT_PAYLOAD = json.dumps(
    {
        "results": [
            {
                "test_id": "B602",
                "test_name": "subprocess_popen_with_shell_equals_true",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "issue_text": "subprocess call with shell=True identified, security issue.",
                "line_number": 37,
                "col_offset": 4,
                "end_col_offset": 30,
                "filename": "/ws/app.py",
                "more_info": "https://bandit.readthedocs.io/en/1.9.4/plugins/b602.html",
                "issue_cwe": {"id": 78, "link": "https://cwe.mitre.org/data/definitions/78.html"},
                "code": "subprocess.run(SECRET_COMMAND, shell=True)",
            },
            {
                "test_id": "B101",
                "test_name": "assert_used",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "issue_text": "Use of assert detected.",
                "line_number": 5,
                "filename": "/ws/app.py",
            },
            {
                "test_id": "B404",
                "test_name": "blacklist",
                "issue_severity": "UNDEFINED",
                "issue_confidence": "UNDEFINED",
                "issue_text": "blacklisted import",
                "line_number": 2,
                "filename": "/ws/app.py",
            },
            {"test_id": "B999", "issue_severity": "HIGH", "issue_text": "no filename"},
        ],
        "metrics": {"_totals": {"SEVERITY.HIGH": 2}},
    }
)

RADON_CC_PAYLOAD = json.dumps(
    {
        "pkg/util.py": [
            {"type": "function", "rank": "A", "complexity": 1, "name": "add", "lineno": 1, "endline": 2, "closures": []},
            {
                "type": "class",
                "rank": "B",
                "complexity": 6,
                "name": "Svc",
                "lineno": 5,
                "methods": [
                    {"type": "method", "rank": "C", "complexity": 12, "name": "run", "classname": "Svc", "lineno": 7, "endline": 20}
                ],
            },
            {
                "type": "function",
                "rank": "D",
                "complexity": 25,
                "name": "tangled",
                "lineno": 30,
                "endline": 60,
                "closures": [{"type": "function", "rank": "B", "complexity": 9, "name": "inner", "lineno": 40}],
            },
        ],
        "broken.py": {"error": "invalid syntax"},
    }
)

RADON_MI_PAYLOAD = json.dumps(
    {"pkg/util.py": {"mi": 8.4, "rank": "C"}, "mid.py": {"mi": 15.0, "rank": "B"}, "ok.py": {"mi": 90.0, "rank": "A"}}
)

RADON_RAW_PAYLOAD = json.dumps(
    {"pkg/util.py": {"loc": 60, "lloc": 40, "sloc": 35, "comments": 5, "multi": 1, "blank": 3, "single_comments": 0}}
)


def _context(temp_root: Path, *, runner: AnalyzerRunner, paths=("app.py",), config=None) -> AnalyzerContext:
    return AnalyzerContext(
        root=temp_root,
        cwd=temp_root,
        paths=tuple(paths),
        config=config or resolve_config(),
        runner=runner,
    )


def _runner(temp_root: Path) -> AnalyzerRunner:
    return AnalyzerRunner(
        workspace_home=temp_root / "home", workspace_tmp=temp_root / "tmp", workdir=temp_root
    )


# --- ruff --------------------------------------------------------------------


def test_ruff_severity_and_category_mapping():
    findings, error = ruff_module.parse_ruff_json(RUFF_PAYLOAD)
    assert error is None
    by_code = {finding.rule_id: finding for finding in findings}

    assert (by_code["F401"].severity, by_code["F401"].category) == ("low", "dead_code")
    assert (by_code["F821"].severity, by_code["F821"].category) == ("high", "bug")
    assert (by_code["E722"].severity, by_code["E722"].category) == ("medium", "bug")
    assert (by_code["B006"].severity, by_code["B006"].category) == ("medium", "bug")
    assert (by_code["SIM101"].severity, by_code["SIM101"].category) == ("low", "style")
    assert (by_code["F541"].severity, by_code["F541"].category) == ("low", "style")
    assert (by_code["invalid-syntax"].severity, by_code["invalid-syntax"].category) == ("high", "bug")

    assert by_code["F401"].line_start == 1 and by_code["F401"].column_start == 8
    assert by_code["F401"].line_end == 1 and by_code["F401"].column_end == 10
    assert by_code["F401"].references == {"rule_url": "https://docs.astral.sh/ruff/rules/unused-import"}
    assert by_code["F401"].metadata["noqa_row"] == 1
    # Malformed entries are skipped, the rest of the report survives.
    assert len(findings) == 7


def test_ruff_reports_parse_errors_without_raising():
    assert ruff_module.parse_ruff_json("")[1] is not None
    assert ruff_module.parse_ruff_json("{not json")[1] is not None
    assert ruff_module.parse_ruff_json('{"a": 1}')[1] is not None


def test_ruff_exit_code_two_is_classified_from_stderr():
    assert ruff_module._classify_error_exit("error: Unknown rule selector: XX") is AnalyzerStatus.INVALID_CONFIG
    assert ruff_module._classify_error_exit("thread panicked") is AnalyzerStatus.EXECUTION_ERROR


def test_ruff_analyzer_marks_findings_and_never_treats_exit_one_as_failure(temp_root):
    runner = _runner(temp_root)
    (temp_root / "app.py").write_text("import os\n", encoding="utf-8")
    context = _context(temp_root, runner=runner)

    result = ruff_module.build(context).analyze(context)

    assert result.status is AnalyzerStatus.FINDINGS
    assert result.exit_code == 1
    assert result.findings and result.findings[0].rule_id == "F401"


def test_analyzer_without_files_is_not_a_failure(temp_root):
    runner = _runner(temp_root)
    context = _context(temp_root, runner=runner, paths=())
    result = ruff_module.build(context).analyze(context)
    assert result.status is AnalyzerStatus.OK
    assert result.findings == []


def test_missing_executable_is_reported_as_unavailable(temp_root, monkeypatch):
    runner = _runner(temp_root)
    monkeypatch.setattr(AnalyzerRunner, "resolve", staticmethod(lambda executable: None))
    context = _context(temp_root, runner=runner)

    result = ruff_module.build(context).analyze(context)

    assert result.status is AnalyzerStatus.UNAVAILABLE
    assert result.status.error_category.value == "analyzer_unavailable"


def test_analyzer_reports_invalid_output_when_the_tool_prints_garbage(temp_root, monkeypatch):
    runner = _runner(temp_root)
    monkeypatch.setattr(AnalyzerRunner, "resolve", staticmethod(lambda executable: "/usr/bin/true"))
    monkeypatch.setattr(
        AnalyzerRunner,
        "run",
        lambda self, argv, **kwargs: _fake_process(stdout="not json at all", exit_code=1),
    )
    context = _context(temp_root, runner=runner)

    result = ruff_module.build(context).analyze(context)
    assert result.status is AnalyzerStatus.INVALID_OUTPUT
    assert result.status.error_category.value == "output_parsing"


def test_analyzer_reports_output_limit_when_output_is_truncated(temp_root, monkeypatch):
    runner = _runner(temp_root)
    monkeypatch.setattr(AnalyzerRunner, "resolve", staticmethod(lambda executable: "/usr/bin/true"))
    monkeypatch.setattr(
        AnalyzerRunner,
        "run",
        lambda self, argv, **kwargs: _fake_process(stdout="[]", exit_code=1, truncated=True),
    )
    context = _context(temp_root, runner=runner)

    result = ruff_module.build(context).analyze(context)
    assert result.status is AnalyzerStatus.OUTPUT_LIMIT


def _fake_process(*, stdout="", stderr="", exit_code=0, truncated=False, status=AnalyzerStatus.OK, message=None):
    from app.analysis.runner import ProcessResult

    return ProcessResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
        message=message,
    )


# --- bandit ------------------------------------------------------------------


def test_bandit_parsing_keeps_severity_and_confidence_apart():
    findings, error = bandit_module.parse_bandit_json(BANDIT_PAYLOAD)
    assert error is None
    by_id = {finding.rule_id: finding for finding in findings}

    shell = by_id["B602"]
    assert shell.severity == "high" and shell.confidence == "high"
    assert shell.category == "security"
    assert shell.metadata["test_name"] == "subprocess_popen_with_shell_equals_true"
    assert shell.metadata["tool_severity"] == "HIGH"
    assert shell.references["cwe"] == "CWE-78"
    assert shell.references["more_info"].startswith("https://bandit.readthedocs.io")

    assert by_id["B101"].severity == "low" and by_id["B101"].confidence == "high"
    assert by_id["B404"].severity == "info" and by_id["B404"].confidence is None
    assert "B999" not in by_id  # no filename → unusable entry


def test_bandit_source_snippets_are_never_copied():
    findings, _ = bandit_module.parse_bandit_json(BANDIT_PAYLOAD)
    shell = next(finding for finding in findings if finding.rule_id == "B602")
    serialized = json.dumps(
        {
            "description": shell.description,
            "metadata": shell.metadata,
            "references": shell.references,
            "title": shell.title,
        }
    )
    assert "SECRET_COMMAND" not in serialized
    assert "shell=True)" not in serialized
    assert "code" not in (shell.metadata or {})


def test_bandit_rejects_malformed_reports():
    assert bandit_module.parse_bandit_json("")[1] is not None
    assert bandit_module.parse_bandit_json("[]")[1] is not None
    assert bandit_module.parse_bandit_json('{"metrics": {}}')[1] is not None
    assert bandit_module.parse_bandit_json('{"results": {}}')[1] is not None


# --- radon -------------------------------------------------------------------


def test_radon_complexity_parsing_flattens_methods_and_ignores_closures():
    blocks, errors, error = radon_module.parse_complexity_json(RADON_CC_PAYLOAD)
    assert error is None
    assert errors == {"broken.py": "invalid syntax"}

    util_blocks = blocks["pkg/util.py"]
    assert [block["name"] for block in util_blocks] == ["add", "run", "tangled"]
    assert [block["complexity"] for block in util_blocks] == [1, 12, 25]
    assert util_blocks[1]["classname"] == "Svc"
    # Closures are not double counted.
    assert all(block["name"] != "inner" for block in util_blocks)


def test_radon_complexity_findings_use_the_configured_thresholds(temp_root):
    blocks, _, _ = radon_module.parse_complexity_json(RADON_CC_PAYLOAD)
    config = resolve_config()
    context = _context(temp_root, runner=_runner(temp_root), config=config)

    findings = radon_module._complexity_findings(context, blocks)
    by_symbol = {finding.identity: finding for finding in findings}

    assert "add" not in by_symbol  # complexity 1 < threshold 11
    assert by_symbol["Svc.run"].severity == "medium"
    assert by_symbol["tangled"].severity == "high"
    assert by_symbol["tangled"].category == "complexity"
    assert by_symbol["tangled"].metadata["complexity"] == 25
    assert by_symbol["tangled"].file_path == "pkg/util.py"


def test_radon_maintainability_findings_follow_the_rank_floor(temp_root):
    values, error = radon_module.parse_maintainability_json(RADON_MI_PAYLOAD)
    assert error is None

    config = resolve_config()
    context = _context(temp_root, runner=_runner(temp_root), config=config)
    by_file = {finding.file_path: finding for finding in radon_module._maintainability_findings(context, values)}

    assert by_file["ok.py"] if "ok.py" in by_file else True  # rank A is not reported at default settings
    assert "ok.py" not in by_file
    assert by_file["mid.py"].severity == "low"
    assert by_file["pkg/util.py"].severity == "medium"
    assert by_file["pkg/util.py"].category == "maintainability"


def test_radon_metrics_document_structure(temp_root):
    blocks, errors, _ = radon_module.parse_complexity_json(RADON_CC_PAYLOAD)
    mi_values, _ = radon_module.parse_maintainability_json(RADON_MI_PAYLOAD)
    raw_values, _ = radon_module.parse_raw_json(RADON_RAW_PAYLOAD)
    context = _context(temp_root, runner=_runner(temp_root))

    complexity = radon_module._complexity_metrics(context, blocks, errors)
    maintainability = radon_module._maintainability_metrics(context, mi_values)
    raw = radon_module._raw_metrics(context, raw_values)

    assert complexity["files_measured"] == 1
    assert complexity["blocks_measured"] == 3
    assert complexity["max"] == 25
    assert complexity["distribution"]["A"] == 1
    assert complexity["unparsable_files"] == {"broken.py": "invalid syntax"}
    assert complexity["files"]["pkg/util.py"]["top_blocks"][0]["symbol"] == "tangled"

    assert maintainability["distribution"] == {"A": 1, "B": 1, "C": 1, "D": 0, "E": 0, "F": 0}
    assert maintainability["min"] == 8.4

    assert raw["totals"]["sloc"] == 35
    assert raw["files"]["pkg/util.py"]["lloc"] == 40


# --- registry ----------------------------------------------------------------


def test_registry_rejects_duplicates_and_unknown_lookups():
    registry = AnalyzerRegistry()
    spec = AnalyzerSpec(
        name="fake", languages=frozenset({"python"}), category="lint", capabilities=frozenset(), executable="fake"
    )
    registry.register(spec, lambda context: None)
    with pytest.raises(ValueError):
        registry.register(spec, lambda context: None)
    with pytest.raises(KeyError):
        registry.get("nope")
    assert "fake" in registry and len(registry) == 1


def test_default_registry_applicability_respects_the_enabled_subset():
    registry = build_default_registry()
    assert registry.names() == ("ruff", "bandit", "radon")
    assert registry.applicable("python") == ("ruff", "bandit", "radon")
    assert registry.applicable("python", enabled=["ruff"]) == ("ruff",)
    assert registry.applicable("ruby") == ()
    assert registry.languages() == frozenset({"python"})
    assert registry.security_analyzers() == ("bandit",)
    assert registry.spec("bandit").category == "security"


# --- controlled execution ----------------------------------------------------


def test_runner_reports_a_missing_executable(temp_root):
    runner = _runner(temp_root)
    result = runner.run(["definitely-not-installed", "--version"], timeout=5, max_output_bytes=1024)
    assert result.status is AnalyzerStatus.UNAVAILABLE


def test_runner_scrubs_the_environment(temp_root, monkeypatch):
    runner = _runner(temp_root)
    monkeypatch.setenv("SECRET_KEY", "super-secret-value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/stackwise")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "gh-client-secret")

    result = runner.run(
        [sys.executable, "-c", "import json,os;print(json.dumps(dict(os.environ)))"],
        timeout=30,
        max_output_bytes=100_000,
    )

    environment = json.loads(result.stdout)
    assert result.status is AnalyzerStatus.OK
    assert "SECRET_KEY" not in environment
    assert "DATABASE_URL" not in environment
    assert "GITHUB_CLIENT_SECRET" not in environment
    assert "PYTHONPATH" not in environment
    assert os.path.isdir(environment["HOME"]) and environment["HOME"].startswith(str(temp_root))


def test_runner_truncates_excessive_output(temp_root):
    runner = _runner(temp_root)
    result = runner.run(
        [sys.executable, "-c", "print('x' * 50000)"], timeout=30, max_output_bytes=1000
    )
    assert result.truncated is True
    assert len(result.stdout) <= 1000


def test_runner_kills_a_timed_out_process_and_its_children(temp_root):
    runner = _runner(temp_root)
    marker = temp_root / "late-write.txt"
    script = (
        "import pathlib, time\n"
        "time.sleep(3)\n"
        f"pathlib.Path({str(marker)!r}).write_text('written')\n"
    )

    started = time.monotonic()
    result = runner.run([sys.executable, "-c", script], timeout=0.5, max_output_bytes=10_000)
    elapsed = time.monotonic() - started

    assert result.status is AnalyzerStatus.TIMEOUT
    assert elapsed < 2.5
    time.sleep(3.2)
    assert not marker.exists()


def test_runner_applies_rlimits_to_the_child(temp_root):
    runner = _runner(temp_root)
    runner.apply_limits(ProcessLimits(timeout_seconds=30, max_output_bytes=10_000, memory_mb=512, cpu_seconds=5))
    script = (
        "import resource\n"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0] // (1024*1024))\n"
    )
    result = runner.run([sys.executable, "-c", script], timeout=30, max_output_bytes=10_000)
    assert result.stdout.strip() == "512"


def test_runner_requires_an_absolute_or_resolvable_program(temp_root):
    runner = _runner(temp_root)
    with pytest.raises(ValueError):
        runner.run([], timeout=1, max_output_bytes=10)
