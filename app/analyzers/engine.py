import subprocess
import json
from typing import List
from app.models.analysis import Finding
from pathlib import Path

class AnalyzerBase:
    def __init__(self, project_path: Path):
        self.project_path = project_path

    def run_command(self, args: List[str], timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                args,
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
        output = self.run_command(["ruff", "check", ".", "--format=json"])
        findings = []
        if not output:
            return findings

        try:
            data = json.loads(output)
            for item in data:
                # Ruff JSON: [{'code': 'E101', 'message': '...', 'location': {'row': 1, 'column': 1, 'resource': 'file.py'}, ...}]
                findings.append(Finding(
                    tool="ruff",
                    rule_id=item.get("code"),
                    severity=item.get("level", "warning"),
                    title=f"Ruff {item.get('code')}",
                    message=item.get("message"),
                    file_path=item.get("location", {}).get("relative", item.get("location", {}).get("resource")),
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
                    file_path=item.get("relative_path"),
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
