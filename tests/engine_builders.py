"""Small builders for engine unit tests (not collected by pytest)."""

from pathlib import Path

from app.analysis.analyzers.base import AnalyzerOutcome, AnalyzerStatus, RawFinding
from app.analysis.inventory import FileEntry, InventoryReport, InventoryStats
from app.analysis.normalize import NormalizedFinding, build_fingerprint


def entry(path: str, *, language: str | None = "python", lines: int = 10, analyzers=("ruff", "bandit", "radon"), skipped=False, reason=None) -> FileEntry:
    return FileEntry(
        path=path,
        language=language,
        extension=".py" if path.endswith(".py") else "",
        size_bytes=100,
        line_count=lines,
        analyzers=tuple(analyzers),
        skipped=skipped,
        skip_reason=reason,
    )


def inventory(root: Path, files=(), *, discovered=None, skipped=0, failed=0) -> InventoryReport:
    files = tuple(files)
    stats = InventoryStats(
        discovered=len(files) + skipped if discovered is None else discovered,
        analyzed=len(files),
        skipped=skipped,
        failed=failed,
        total_lines=sum(item.line_count or 0 for item in files),
    )
    languages = tuple(sorted({item.language for item in files if item.language}))
    return InventoryReport(root=root, files=files, skipped=(), failures=(), stats=stats, languages=languages)


def outcome(
    analyzer: str = "ruff",
    *,
    status: AnalyzerStatus = AnalyzerStatus.OK,
    findings=(),
    metrics=None,
    version: str = "1.2.3",
    duration: float = 0.5,
    message=None,
) -> AnalyzerOutcome:
    return AnalyzerOutcome(
        analyzer=analyzer,
        status=status,
        findings=list(findings),
        metrics=metrics,
        version=version,
        duration_seconds=duration,
        exit_code=0 if status.succeeded else None,
        message=message,
    )


def finding(
    *,
    tool: str = "ruff",
    rule_id: str | None = "F401",
    category: str = "dead_code",
    severity: str = "low",
    file_path: str = "app.py",
    line_start: int | None = 1,
    title: str = "Ruff F401",
    message: str = "`os` imported but unused",
    confidence: str | None = None,
    identity: str | None = None,
    metadata: dict | None = None,
    references: dict | None = None,
) -> RawFinding:
    return RawFinding(
        tool=tool,
        rule_id=rule_id,
        category=category,
        severity=severity,
        title=title,
        description=message,
        confidence=confidence,
        file_path=file_path,
        line_start=line_start,
        identity=identity,
        metadata=metadata,
        references=references,
    )


def normalized(
    *,
    tool: str = "bandit",
    rule_id: str | None = "B602",
    category: str = "security",
    severity: str = "high",
    file_path: str = "app.py",
    line_start: int | None = 10,
    identity: str | None = None,
) -> NormalizedFinding:
    return NormalizedFinding(
        tool=tool,
        rule_id=rule_id,
        category=category,
        severity=severity,
        confidence="high",
        title=f"{tool} {rule_id}",
        message="potential issue",
        file_path=file_path,
        line_start=line_start,
        line_end=None,
        column_start=None,
        column_end=None,
        fingerprint=build_fingerprint(
            tool=tool,
            rule_id=rule_id,
            category=category,
            file_path=file_path,
            line_start=line_start,
            identity=identity,
        ),
        references=None,
        metadata=None,
    )


def demo_python_sources() -> dict[str, str]:
    """A small Python tree with at least one knowable finding per analyzer."""
    return {
        "demo-main/app.py": (
            "import os\n"
            "import subprocess\n"
            "import hashlib\n"
            "\n"
            "\n"
            "def tangled(values, flag, limit):\n"
            "    total = 0\n"
            "    for value in values:\n"
            "        if value > limit:\n"
            "            if flag:\n"
            "                total += value * 2\n"
            "            elif flag is None:\n"
            "                total += value\n"
            "            else:\n"
            "                total -= value\n"
            "        elif value < -limit:\n"
            "            total += 100\n"
            "        elif value < -10:\n"
            "            total += 50\n"
            "        elif value < -5:\n"
            "            total += 10\n"
            "        elif value < -1:\n"
            "            total += 5\n"
            "        else:\n"
            "            total += 1\n"
            "        while total > limit * 10:\n"
            "            total -= 1\n"
            "    try:\n"
            "        run()\n"
            "    except:\n"
            "        pass\n"
            "    return total\n"
            "\n"
            "\n"
            "def run():\n"
            '    subprocess.run("echo hi", shell=True)\n'
            '    hashlib.md5(b"x")\n'
            "    return undefined_name\n"
        ),
        "demo-main/pkg/util.py": "def add(a, b):\n    return a + b\n",
        "demo-main/README.md": "# demo\n",
        "demo-main/.git/config": "[core]\n",
        "demo-main/node_modules/junk/index.js": "console.log(1)\n",
    }
