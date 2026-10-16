"""Safe intake of a GitHub repository zipball.

The archive is untrusted input, even though it comes from a repository the
caller's token can read. This module is the only place that turns bytes into a
directory tree, and it enforces, in one pass over a single `ZipFile` handle:

* archive size, per-file size, total extracted size, file count, nesting depth;
* compression ratio (archive bombs), including entries that lie about their size;
* path safety — absolute paths, drive letters, `..` traversal, NUL/control
  characters, over-long names: anything that would land outside the destination;
* entry kind — only regular files and directories; symbolic links, hard links,
  FIFOs, sockets and device nodes are rejected outright.

Nothing from the archive's metadata is trusted: `external_attr` is used only to
*reject* unusual entries, never to set permissions or ownership.

`extract_archive()` validates and writes in one pass, so a rejected archive
leaves nothing behind.
"""

import hashlib
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from app.analysis.config import AnalysisConfig
from app.analysis.errors import (
    InvalidSourceError,
    ResourceLimitError,
    SourceAcquisitionError,
)
from app.analysis.sources.base import SourceSnapshot
from app.analysis.workspace import RunWorkspace

_CHUNK = 64 * 1024
_MAX_NAME_CHARS = 500
_MAX_SEGMENT_CHARS = 255
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class ArchiveEntry:
    """One validated entry, described by its normalised relative path."""

    path: str
    parts: tuple[str, ...]
    is_directory: bool
    uncompressed_size: int
    compressed_size: int


@dataclass(frozen=True)
class ArchiveReport:
    files: int
    directories: int
    total_uncompressed_bytes: int
    max_depth: int


def extract_archive(archive_path: Path, destination: Path, config: AnalysisConfig) -> ArchiveReport:
    """Validate and extract `archive_path` into `destination` (created if absent)."""
    destination.mkdir(parents=True, exist_ok=True)
    with _open_archive(archive_path, config) as archive:
        report = _validate(archive, config)
        _extract(archive, destination, config, report)
    return report


class _OpenedArchive:
    """Context manager so `_validate`/`_extract` share one handle (no TOCTOU)."""

    def __init__(self, archive_path: Path, config: AnalysisConfig):
        self._path = archive_path
        self._config = config
        self._handle: zipfile.ZipFile | None = None

    def __enter__(self) -> zipfile.ZipFile:
        path = self._path
        if not path.exists():
            raise SourceAcquisitionError("The downloaded snapshot no longer exists")
        if not path.is_file():
            raise InvalidSourceError("The downloaded snapshot is not a regular file")
        size = path.stat().st_size
        if size <= 0:
            raise InvalidSourceError("The downloaded snapshot is empty")
        if size > self._config.max_archive_bytes:
            raise ResourceLimitError(
                f"The archive exceeds the {self._config.max_archive_bytes // (1024 * 1024)}MB limit"
            )
        try:
            self._handle = zipfile.ZipFile(path, "r")
        except zipfile.BadZipFile as exc:
            raise InvalidSourceError("The file is not a valid ZIP archive") from exc
        return self._handle

    def __exit__(self, *exc_info: object) -> None:
        if self._handle is not None:
            self._handle.close()


def _open_archive(archive_path: Path, config: AnalysisConfig) -> _OpenedArchive:
    return _OpenedArchive(archive_path, config)


def _validate(archive: zipfile.ZipFile, config: AnalysisConfig) -> ArchiveReport:
    entries = _validated_entries(archive, config)
    files = [entry for entry in entries if not entry.is_directory]
    directories = len(entries) - len(files)
    return ArchiveReport(
        files=len(files),
        directories=directories,
        total_uncompressed_bytes=sum(entry.uncompressed_size for entry in files),
        max_depth=max((len(entry.parts) for entry in entries), default=0),
    )


def _validated_entries(archive: zipfile.ZipFile, config: AnalysisConfig) -> tuple[ArchiveEntry, ...]:
    infos = archive.infolist()
    if len(infos) > config.max_file_count * 2:
        raise ResourceLimitError(f"The archive has more than {config.max_file_count} entries")

    entries: list[ArchiveEntry] = []
    file_count = 0
    total_bytes = 0

    for info in infos:
        name, is_directory = _normalise_name(info.filename, config)
        kind = _entry_kind(info, name, is_directory)

        if kind == "directory":
            entries.append(ArchiveEntry(name, tuple(name.split("/")), True, 0, info.compress_size))
            continue
        if kind != "file":
            raise InvalidSourceError(
                f"The archive contains a {kind} entry, which is not allowed: {name}"
            )

        file_count += 1
        if file_count > config.max_file_count:
            raise ResourceLimitError(f"The archive has more than {config.max_file_count} files")
        if info.file_size > config.max_file_bytes:
            raise ResourceLimitError(
                f"{name} exceeds the {config.max_file_bytes // 1024}KB per-file limit"
            )
        total_bytes += info.file_size
        if total_bytes > config.max_extracted_bytes:
            raise ResourceLimitError(
                f"The extracted archive would exceed "
                f"{config.max_extracted_bytes // (1024 * 1024)}MB"
            )
        if info.file_size > 0:
            if info.compress_size <= 0:
                raise ResourceLimitError(f"{name} has an implausible compressed size")
            if info.file_size / info.compress_size > config.max_compression_ratio:
                raise ResourceLimitError(
                    f"{name} exceeds the maximum compression ratio "
                    f"({config.max_compression_ratio}:1) and looks like an archive bomb"
                )

        entries.append(
            ArchiveEntry(name, tuple(name.split("/")), False, info.file_size, info.compress_size)
        )

    if not entries:
        raise InvalidSourceError("The archive is empty")
    return tuple(entries)


def _normalise_name(raw_name: str, config: AnalysisConfig) -> tuple[str, bool]:
    """Validate an entry name and return `(relative posix path, is_directory)`."""
    if not raw_name:
        raise InvalidSourceError("The archive contains an entry with an empty name")
    if len(raw_name) > _MAX_NAME_CHARS:
        raise InvalidSourceError("The archive contains an entry with an over-long name")
    if any(char == "\x00" or (ord(char) < 32 and char not in "\t") for char in raw_name):
        raise InvalidSourceError("The archive contains an entry with control characters in its name")

    name = raw_name.replace("\\", "/")
    is_directory = name.endswith("/")
    name = name.rstrip("/")
    if not name:
        raise InvalidSourceError("The archive contains an entry with an empty name")
    if name.startswith("/") or _WINDOWS_DRIVE.match(name) or name.startswith("//"):
        raise InvalidSourceError(f"The archive contains an absolute path: {name}")

    parts: list[str] = []
    for segment in name.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise InvalidSourceError(f"The archive contains a path traversal entry: {raw_name}")
        if len(segment) > _MAX_SEGMENT_CHARS:
            raise InvalidSourceError("The archive contains an entry with an over-long path segment")
        parts.append(segment)

    if not parts:
        raise InvalidSourceError("The archive contains an entry with an empty name")
    if len(parts) > config.max_workspace_depth:
        raise ResourceLimitError(
            f"The archive nests deeper than {config.max_workspace_depth} directories: {raw_name}"
        )
    return "/".join(parts), is_directory


def _entry_kind(info: zipfile.ZipInfo, name: str, is_directory: bool) -> str:
    """Classify an entry from its Unix mode bits (and the trailing `/` convention).

    Archivers written by tools that do not record Unix attributes leave the file
    type bits empty (`zipfile.writestr` writes mode `0o600`), so "no type" is
    treated as a regular file. Anything that *does* declare a type other than
    regular file or directory — symlink, FIFO, socket, device — is refused by the
    caller. Hard links have no ZIP representation.
    """
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode) if mode else 0
    if file_type == stat.S_IFLNK:
        return "symbolic link"
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        return "special filesystem"
    if is_directory or file_type == stat.S_IFDIR:
        return "directory"
    return "file"


def _extract(
    archive: zipfile.ZipFile,
    destination: Path,
    config: AnalysisConfig,
    report: ArchiveReport,
) -> None:
    """Write the validated entries, re-checking the size caps while writing.

    The central directory can lie about sizes, so the caps are enforced against
    the bytes actually written, not against `ZipInfo.file_size`.
    """
    root = destination.resolve()
    written_total = 0

    for info in archive.infolist():
        # Names are normalised again here (not carried over from `_validate`) so
        # that extraction is safe on its own, even when called with a fresh handle.
        name, is_directory = _normalise_name(info.filename, config)
        target = destination.joinpath(*name.split("/"))
        if not str(target.parent.resolve()).startswith(str(root)):
            raise InvalidSourceError(f"Refusing to extract outside the workspace: {name}")

        if is_directory:
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        written_here = 0
        try:
            with archive.open(info) as source_handle, open(target, "wb") as target_handle:
                while True:
                    chunk = source_handle.read(_CHUNK)
                    if not chunk:
                        break
                    written_here += len(chunk)
                    written_total += len(chunk)
                    if written_here > config.max_file_bytes:
                        raise ResourceLimitError(
                            f"{name} exceeds the {config.max_file_bytes // 1024}KB per-file limit"
                        )
                    if written_total > config.max_extracted_bytes:
                        raise ResourceLimitError(
                            f"The extracted archive exceeds "
                            f"{config.max_extracted_bytes // (1024 * 1024)}MB"
                        )
                    target_handle.write(chunk)
        except zipfile.BadZipFile as exc:
            raise InvalidSourceError(f"Corrupt archive entry: {name}") from exc

    if report.files == 0:
        raise InvalidSourceError("The archive contains no files")


def repository_root(destination: Path) -> Path:
    """Return the repository root inside an extraction directory.

    GitHub's zipball wraps everything in a single `repo-ref/` directory; when the
    extraction directory holds exactly one directory and no files, that directory
    is the repository root. Otherwise the directory itself is the root.
    """
    entries = sorted(destination.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink():
        candidate = entries[0]
        if any(candidate.iterdir()):
            return candidate
    return destination


def hash_tree(root: Path, *, budget_bytes: int) -> str:
    """sha256 over the tree's relative paths, sizes and file contents.

    Bounded by `budget_bytes`; if the tree somehow exceeds it (it cannot, by the
    extraction limits) the hash covers a prefix and `content_hash` is still
    stable for identical inputs.
    """
    digest = hashlib.sha256()
    consumed = 0
    for path in _iter_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            continue
        digest.update(relative.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        file_digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                while consumed < budget_bytes:
                    chunk = handle.read(_CHUNK)
                    if not chunk:
                        break
                    consumed += len(chunk)
                    file_digest.update(chunk)
        except OSError:
            continue
        digest.update(file_digest.digest())
    return digest.hexdigest()


def _iter_files(root: Path) -> Iterator[Path]:
    for current, _dirnames, filenames in sorted_walk(root):
        for filename in filenames:
            candidate = Path(current) / filename
            if candidate.is_file() and not candidate.is_symlink():
                yield candidate


def sorted_walk(root: Path):
    """`os.walk` with sorted, deterministic order and no symlink following."""
    import os

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        yield current, dirnames, filenames


def discard_archive(path: "Path | str") -> None:
    """Delete a spooled archive (the downloaded GitHub snapshot); never raises.

    Two callers need this: the API, when a request fails *before* the pipeline
    takes ownership of the file, and the orchestrator, which discards it on
    success, failure and interruption alike.
    """
    try:
        candidate = Path(path)
        if candidate.exists():
            os.remove(candidate)
    except OSError:
        # Losing the race with the OS or a permission problem is not worth
        # failing a run over; the workspace is still cleaned up.
        pass


class ArchiveSourceProvider:
    """Source provider for the repository snapshot already on disk.

    `acquire` is blocking (extraction and hashing are IO/CPU bound); the
    orchestrator runs it in a worker thread.
    """

    def __init__(
        self,
        archive_path: Path,
        *,
        config: AnalysisConfig,
        source_type: str = "github",
        origin: str | None = None,
    ):
        self._archive_path = Path(archive_path)
        self._config = config
        self.source_type = source_type
        self.origin = origin

    def acquire(self, workspace: RunWorkspace) -> SourceSnapshot:
        extract_archive(self._archive_path, workspace.source, self._config)
        root = repository_root(workspace.source)
        content_hash = hash_tree(root, budget_bytes=self._config.max_extracted_bytes)
        return SourceSnapshot(
            root=root,
            source_type=self.source_type,
            origin=self.origin,
            content_hash=content_hash,
        )
