import subprocess
import json
import shutil
import sys
from typing import List, Optional
from app.models.analysis import Finding
from pathlib import Path

def _resolve_executable(name: str) -> Optional[str]:
    """Find an analyzer binary on PATH, falling back to the running interpreter's bin dir.

    Tools installed in a virtualenv (e.g. ruff/bandit/radon) are not on PATH unless the
    venv is activated, so uvicorn launched via its venv path would silently find nothing.
    """
    found = shutil.which(name)
    if found:
        return found
    candidate = Path(sys.executable).parent / name
    return str(candidate) if candidate.is_file() else None

class AnalyzerBase:
    def __init__(self, project_path: Path):
        self.project_path = project_path

    def run_command(self, args: List[str], timeout: int = 30) -> str:
        executable = _resolve_executable(args[0])
        if executable is None:
            return ""
        try:
            result = subprocess.run(
                [executable, *args[1:]],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False  # Critical security: no shell=True
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            return ""
        except Exception:
            return ""

class RuffAnalyzer(AnalyzerBase):
    def analyze(self) -> List[Finding]:
        # Ruff output in JSON format
        output = self.run_command(["ruff", "check", ".", "--output-format=json"])
        findings = []
        if not output:
            return findings

        try:
            data = json.loads(output)
            for item in data:
                # Ruff JSON: {'code': 'F401', 'message': '...', 'filename': 'file.py',
                #             'location': {'row': 1, 'column': 1}, ...}
                code = item.get("code") or ""
                # Ruff has no severity levels; treat syntax/undefined-name errors as high
                # and the rest as low so findings map onto the high/medium/low buckets.
                severity = "high" if code.startswith("E9") or code.startswith("F82") else "low"
                findings.append(Finding(
                    tool="ruff",
                    rule_id=item.get("code"),
                    severity=severity,
                    title=f"Ruff {item.get('code')}",
                    message=item.get("message"),
                    file_path=item.get("filename"),
                    line_start=str(item.get("location", {}).get("row")),
                    line_end=None
                ))
        except json.JSONDecodeError:
            pass
        return findings

class BanditAnalyzer(AnalyzerBase):
    def analyze(self) -> List[Finding]:
        # Bandit output in JSON format
        output = self.run_command(["bandit", "-r", ".", "-f", "json", "-q"])
        findings = []
        if not output:
            return findings

        try:
            data = json.loads(output)
            results = data.get("results", [])
            for item in results:
                # Bandit JSON: [{'issue_severity': 'HIGH', 'issue_text': '...', 'filename': '...', 'line_number': 1, ...}]
                findings.append(Finding(
                    tool="bandit",
                    rule_id=item.get("test_id"),
                    severity=item.get("issue_severity", "medium").lower(),
                    title=item.get("issue_text"),
                    message=item.get("issue_severity") + " severity issue detected",
                    file_path=item.get("filename") or item.get("relative_path"),
                    line_start=str(item.get("line_number")),
                    line_end=None
                ))
        except json.JSONDecodeError:
            pass
        return findings

class RadonAnalyzer(AnalyzerBase):
    def analyze(self) -> List[Finding]:
        # Radon for Cyclomatic Complexity (CC)
        # Radon returns text, we can use CC's JSON output via command line if available or parse text
        # For V1, we use the CC tool and parse the output
        output = self.run_command(["radon", "cc", ".", "-s", "--json"])
        findings = []
        if not output:
            return findings

        try:
            data = json.loads(output)
            for file_path, contents in data.items():
                for block in contents:
                    # block: {'name': 'func_name', 'lineno': 10, 'complexity': 15, 'rank': 'C'}
                    complexity = block.get("complexity", 0)
                    if complexity > 10: # Threshold for "Finding"
                        findings.append(Finding(
                            tool="radon",
                            rule_id="complexity",
                            severity="medium" if complexity < 20 else "high",
                            title="High Cyclomatic Complexity",
                            message=f"Function {block.get('name')} has complexity {complexity} (Rank {block.get('rank')})",
                            file_path=file_path,
                            line_start=str(block.get("lineno")),
                            line_end=None
                        ))
        except json.JSONDecodeError:
            pass
        return findings
