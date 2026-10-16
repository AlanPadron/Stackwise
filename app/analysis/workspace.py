"""Temporary workspace for one analysis run.

Layout (mode 0o700, one per run, deleted in a `finally` block):

    <root>/
      source/   extraction target for the snapshot; the repository root lives
                inside it (GitHub zipballs wrap everything in `repo-ref/`)
      work/     neutral cwd for analyzer processes, so a repository cannot feed
                its own pyproject.toml/.bandit/.radon.cfg to a tool
      home/     HOME for analyzer processes
      tmp/      TMPDIR for analyzer processes

Nothing here is ever a session/temp file with a predictable name, and nothing
outside `<root>` is written.
"""

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunWorkspace:
    root: Path
    source: Path
    workdir: Path
    home: Path
    tmp: Path

    @classmethod
    def create(cls, *, prefix: str = "stackwise_run_") -> "RunWorkspace":
        root = Path(tempfile.mkdtemp(prefix=prefix))
        os.chmod(root, stat.S_IRWXU)
        workspace = cls(
            root=root,
            source=root / "source",
            workdir=root / "work",
            home=root / "home",
            tmp=root / "tmp",
        )
        for directory in (workspace.source, workspace.workdir, workspace.home, workspace.tmp):
            directory.mkdir(mode=stat.S_IRWXU)
        return workspace

    def cleanup(self) -> None:
        """Best-effort recursive delete; never raises."""
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "RunWorkspace":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()
