"""Path normalisation shared by the normaliser and the analyzers.

Everything that is persisted (finding paths, metrics keys) must be a repository
relative, POSIX-separated path. Tools are invoked with absolute paths, so this
module is the single place that maps them back — and the single place that
refuses a path that points outside the workspace, contains `..`, carries
control characters, or is a Windows drive path.
"""

import os
import re
from pathlib import Path
from typing import Optional

MAX_PATH_CHARS = 500
_CONTROL = [(chr(code), None) for code in list(range(0x00, 0x20)) + [0x7f]]
# A Windows drive prefix (`C:\…`). Checked *before* separators are normalised,
# because `os.path.splitdrive` is platform-dependent and recognises nothing on
# the POSIX hosts this backend runs on.
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def _has_control_characters(value: str) -> bool:
    return any(char in value for char, _ in _CONTROL)


def normalize_relative_path(root: Path, raw: object) -> Optional[str]:
    """Return `raw` as a repository-relative posix path, or `None` if unacceptable."""
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > MAX_PATH_CHARS or _has_control_characters(candidate):
        return None
    if _WINDOWS_DRIVE.match(candidate):
        return None

    candidate = candidate.replace("\\", "/")
    root_resolved = _resolved(root)

    if candidate.startswith("/"):
        try:
            candidate = _resolved(Path(candidate)).relative_to(root_resolved).as_posix()
        except (ValueError, OSError):
            return None
        if candidate in (".", ""):
            return None

    parts: list[str] = []
    for segment in candidate.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return None
        parts.append(segment)

    if not parts:
        return None
    normalized = "/".join(parts)
    return normalized if len(normalized) <= MAX_PATH_CHARS else None


def is_within(root: Path, candidate: Path) -> bool:
    """Whether `candidate` really lives under `root` after symlink resolution."""
    root_resolved = _resolved(root)
    try:
        candidate_resolved = _resolved(candidate)
    except OSError:
        return False
    return candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents


def lexical_relative_path(root: Path, absolute: object) -> Optional[str]:
    """Root-relative path of a filesystem entry, **without** resolving symlinks.

    Inventory records what is on disk — a symlink is listed as the symlink, even
    when it points at something else inside the tree. Resolution (and the escape
    check that goes with it) belongs to `SourceReader`, which is the only thing
    that opens a file.
    """
    if not isinstance(absolute, str):
        return None
    relative = os.path.relpath(absolute, str(root))
    return normalize_relative_path(root, relative)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return Path(os.path.abspath(str(path)))
