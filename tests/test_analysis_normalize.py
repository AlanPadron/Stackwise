"""Finding normalisation: paths, vocabularies, redaction, fingerprints, dedup."""

from pathlib import Path

from engine_builders import finding

from app.analysis.analyzers.base import AnalyzerStatus
from app.analysis.normalize import (
    NormalizedFinding,
    build_fingerprint,
    FindingNormalizer,
)

ROOT = Path("/workspace/run/source/repo")


def normalizer(max_findings: int = 100) -> FindingNormalizer:
    return FindingNormalizer(ROOT, max_findings=max_findings)


# --- paths -------------------------------------------------------------------


def test_absolute_paths_inside_the_workspace_become_relative():
    result = normalizer().normalize_one(finding(file_path=str(ROOT / "pkg" / "util.py")))
    assert isinstance(result, NormalizedFinding)
    assert result.file_path == "pkg/util.py"


def test_paths_outside_the_workspace_are_rejected():
    for candidate in ("/etc/passwd", "../../secret.py", str(ROOT.parent / "elsewhere.py"), "C:\\windows\\x.py"):
        assert normalizer().normalize_one(finding(file_path=candidate)) is None


def test_paths_with_control_characters_or_extreme_length_are_rejected():
    assert normalizer().normalize_one(finding(file_path="a\x00b.py")) is None
    assert normalizer().normalize_one(finding(file_path="x" * 600 + ".py")) is None


def test_dot_segments_are_collapsed():
    result = normalizer().normalize_one(finding(file_path="./pkg/./util.py"))
    assert result.file_path == "pkg/util.py"


# --- vocabularies ------------------------------------------------------------


def test_unknown_vocabulary_values_degrade_and_are_recorded():
    result = normalizer().normalize_one(
        finding(severity="BLOCKER", category="security-ish", confidence="certain")
    )
    assert result.severity == "info"
    assert result.category == "other"
    assert result.confidence is None
    assert result.metadata["tool_severity"] == "blocker"
    assert result.metadata["tool_category"] == "security-ish"


def test_canonical_values_pass_through():
    result = normalizer().normalize_one(
        finding(severity="critical", category="security", confidence="HIGH")
    )
    assert (result.severity, result.category, result.confidence) == ("critical", "security", "high")


def test_title_and_message_fall_back_to_each_other():
    only_message = finding(title="", message="the tool said this")
    normalized = normalizer().normalize_one(only_message)
    assert normalized.title == "the tool said this"
    assert normalized.message == "the tool said this"

    only_title = finding(title="Tool said something", message="")
    normalized = normalizer().normalize_one(only_title)
    assert normalized.message == "Tool said something"

    assert normalizer().normalize_one(finding(title="", message="")) is None


def test_line_and_column_values_are_validated():
    raw = finding(line_start=-5)
    assert normalizer().normalize_one(raw).line_start is None
    assert normalizer().normalize_one(finding(line_start=10**9)).line_start is None


# --- redaction and metadata --------------------------------------------------


def test_secret_shaped_text_is_redacted_from_findings():
    result = normalizer().normalize_one(
        finding(
            tool="bandit",
            rule_id="B105",
            title="Hardcoded password",
            message="possible hardcoded password: 'hunter2' password=hunter2",
        )
    )
    assert "hunter2" not in result.message
    assert "<redacted>" in result.message


def test_metadata_is_json_safe_redacted_and_bounded():
    result = normalizer().normalize_one(
        finding(
            metadata={
                "token": "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
                "nested": {"deep": {"deeper": {"deepest": {"too": {"far": 1}}}}},
                "object": object(),
                "a_set": {1, 2},
                "lines": [1, 2, 3],
            }
        )
    )
    assert "ghp_" not in str(result.metadata)
    assert result.metadata["lines"] == [1, 2, 3]
    assert "object" not in result.metadata and "a_set" not in result.metadata


def test_references_keep_only_http_urls():
    result = normalizer().normalize_one(
        finding(
            references={
                "more_info": "https://bandit.readthedocs.io/x",
                "evil": "javascript:alert(1)",
                "file": "file:///etc/passwd",
                "cwe": "CWE-78",
            }
        )
    )
    assert result.references == {"more_info": "https://bandit.readthedocs.io/x", "cwe": "CWE-78"}


# --- fingerprints ------------------------------------------------------------


def test_fingerprint_is_stable_and_ignores_the_message_text():
    first = normalizer().normalize_one(finding(message="first wording"))
    second = normalizer().normalize_one(finding(message="completely different wording"))
    assert first.fingerprint == second.fingerprint


def test_fingerprint_changes_with_location_rule_and_tool():
    base = normalizer().normalize_one(finding())
    assert base.fingerprint != normalizer().normalize_one(finding(line_start=2)).fingerprint
    assert base.fingerprint != normalizer().normalize_one(finding(rule_id="F841")).fingerprint
    assert base.fingerprint != normalizer().normalize_one(finding(tool="bandit")).fingerprint


def test_fingerprint_contains_no_path_and_is_bounded():
    fingerprint = build_fingerprint(
        tool="radon",
        rule_id="complexity",
        category="complexity",
        file_path="pkg/very/distinctive/name.py",
        line_start=42,
        identity="Svc.run",
    )
    assert "very" not in fingerprint and "Svc" not in fingerprint
    assert len(fingerprint) == 32
    assert fingerprint == build_fingerprint(
        tool="radon",
        rule_id="complexity",
        category="complexity",
        file_path="pkg/very/distinctive/name.py",
        line_start=42,
        identity="Svc.run",
    )


# --- deduplication and caps --------------------------------------------------


def test_identical_findings_are_deduplicated():
    from engine_builders import outcome

    normalizer_ = normalizer()
    result = normalizer_.normalize_all(
        [outcome(findings=[finding(), finding(), finding(file_path="other.py")])]
    )
    assert len(result.findings) == 2
    assert result.duplicates_removed == 1


def test_findings_from_different_tools_at_one_location_are_both_kept():
    from engine_builders import outcome

    result = normalizer().normalize_all(
        [
            outcome("ruff", findings=[finding(tool="ruff", rule_id="F821", severity="high")]),
            outcome("bandit", findings=[finding(tool="bandit", rule_id="B101", category="security")]),
        ]
    )
    assert len(result.findings) == 2


def test_findings_from_a_failed_analyzer_are_not_trusted():
    from engine_builders import outcome

    result = normalizer().normalize_all(
        [
            outcome("ruff", status=AnalyzerStatus.TIMEOUT, findings=[finding()]),
            outcome("bandit", findings=[finding(tool="bandit", rule_id="B101", category="security")]),
        ]
    )
    assert [item.tool for item in result.findings] == ["bandit"]


def test_finding_cap_truncates_and_is_recorded():
    from engine_builders import outcome

    findings = [finding(rule_id=f"F{index:03d}", line_start=index + 1) for index in range(10)]
    result = normalizer(max_findings=3).normalize_all([outcome(findings=findings)])

    assert len(result.findings) == 3
    assert result.truncated is True
    assert result.dropped_by_reason == {"findings_limit_reached": 7}


def test_drop_reasons_are_tracked():
    from engine_builders import outcome

    result = normalizer().normalize_all(
        [
            outcome(
                findings=[
                    finding(file_path="../../etc/passwd"),
                    finding(title="", message=""),
                    finding(),
                ]
            )
        ]
    )
    assert result.dropped == 2
    assert result.dropped_by_reason == {"unsafe_or_missing_path": 1, "empty_text": 1}
    assert len(result.findings) == 1
