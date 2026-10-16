"""Source provider interface.

Acquisition is deliberately separate from analysis: a provider turns "where the
code is" into a validated `SourceSnapshot` (a read-only directory tree plus its
origin metadata), and knows nothing about analyzers. Today one provider is
implemented end-to-end (`ArchiveSourceProvider`, covering the GitHub zipball the
import downloads); a future `GitSourceProvider` or `SnapshotSourceProvider`
implements the same protocol and is dispatched from
`app/analysis/orchestrator.py` without touching the pipeline.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from app.analysis.workspace import RunWorkspace


@dataclass(frozen=True)
class SourceSnapshot:
    """An acquired source tree, rooted at `root` and owned by a run workspace."""

    root: Path
    source_type: str  # "github" — the only intake left (see app/api/v1/projects.py)
    origin: Optional[str] = None  # e.g. "octocat/hello-world@main" — metadata only
    content_hash: Optional[str] = None  # sha256 over the extracted files


@runtime_checkable
class SourceProvider(Protocol):
    """What the orchestrator needs from any source."""

    source_type: str

    def acquire(self, workspace: RunWorkspace) -> SourceSnapshot:
        """Materialise the snapshot inside `workspace` (blocking, CPU/IO bound)."""
        ...

