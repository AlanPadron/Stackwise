"""Controlled execution of analyzer processes.

What this does *not* claim to be: a sandbox. There is no syscall filtering, no
namespace or cgroup isolation, and no network namespace — see
docs/ANALYSIS_ENGINE.md → Isolation. What it does guarantee:

* no shell, ever: the command is an argument vector with an absolute executable
  path resolved by us (`shell=True` would let a repository's file name become a
  command);
* a scrubbed environment built from scratch — analyzers never inherit
  `DATABASE_URL`, `SECRET_KEY`, provider tokens or any other application secret;
* a neutral working directory, so a repository cannot feed its own
  `pyproject.toml`, `.bandit` or `.radon.cfg` to a tool;
* bounded stdout/stderr (temp files, read back truncated) and a bounded file
  write size, so an analyzer that spams output cannot exhaust memory or disk;
* a wall-clock timeout with process-group kill, plus CPU, address-space and
  open-file limits on POSIX (`resource.setrlimit`).
"""

import os
import resource
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from app.analysis.analyzers.base import AnalyzerStatus
from app.analysis.observability import log_event
from app.analysis.redact import redact

# Environment variables an analyzer is allowed to see. Everything else — the
# application's own secrets above all — is dropped.
_ENV_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
_ENV_EXPLICIT = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "NO_COLOR": "1",
    "TERM": "dumb",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
}

_VERSION_TIMEOUT_SECONDS = 10.0
_VERSION_OUTPUT_BYTES = 4096


@dataclass(frozen=True)
class ProcessLimits:
    """Resource ceilings applied to every analyzer process."""

    timeout_seconds: float
    max_output_bytes: int
    memory_mb: int = 1024
    cpu_seconds: int = 120
    max_file_bytes: int = 0  # 0 → derived from max_output_bytes


@dataclass
class ProcessResult:
    """The outcome of one process invocation."""

    status: AnalyzerStatus
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    truncated: bool = False
    message: Optional[str] = None
    argv: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.status is AnalyzerStatus.OK


class AnalyzerRunner:
    """Runs analyzer binaries for one analysis run."""

    def __init__(self, *, workspace_home: Path, workspace_tmp: Path, workdir: Path):
        self._home = Path(workspace_home)
        self._tmp = Path(workspace_tmp)
        self._workdir = Path(workdir)
        self._versions: dict[str, Optional[str]] = {}
        # The caller (a RunWorkspace) creates these; re-creating them is cheap and
        # means a mis-wired runner cannot hand a child a non-existent HOME/TMPDIR.
        for directory in (self._home, self._tmp, self._workdir):
            directory.mkdir(parents=True, exist_ok=True)

    # --- discovery ---------------------------------------------------------

    @staticmethod
    def resolve(executable: str) -> Optional[str]:
        """Absolute path of an analyzer binary, or `None` when it is not installed.

        The active interpreter's bin directory is searched too: tools installed
        in the project virtualenv are not on `PATH` when uvicorn is started
        without activating it.
        """
        import shutil
        import sys

        found = shutil.which(executable)
        if found:
            return found
        candidate = Path(sys.executable).parent / executable
        return str(candidate) if candidate.is_file() else None

    def version(self, executable: str) -> Optional[str]:
        """First line of `<tool> --version`, cached per run. Never raises."""
        if executable in self._versions:
            return self._versions[executable]
        resolved = self.resolve(executable)
        version: Optional[str] = None
        if resolved is not None:
            result = self.run(
                [resolved, "--version"],
                timeout=_VERSION_TIMEOUT_SECONDS,
                max_output_bytes=_VERSION_OUTPUT_BYTES,
            )
            output = (result.stdout or result.stderr).strip().splitlines()
            if output:
                version = redact(output[0], limit=64)
        self._versions[executable] = version
        return version

    # --- execution ---------------------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        max_output_bytes: int,
        cwd: Optional[Path] = None,
    ) -> ProcessResult:
        """Run `argv` and classify the process outcome (never raises)."""
        if not argv:
            raise ValueError("argv must not be empty")
        executable = argv[0]
        if not os.path.isabs(executable):
            resolved = self.resolve(executable)
            if resolved is None:
                return ProcessResult(
                    status=AnalyzerStatus.UNAVAILABLE,
                    message=f"{executable} is not installed",
                    argv=tuple(argv),
                )
            argv = [resolved, *argv[1:]]

        started = time.monotonic()
        try:
            # Temp files, not pipes: no reader thread to deadlock, and the reader
            # below can cap how much of the output it ever holds in memory.
            stdout_file = tempfile.TemporaryFile()
            stderr_file = tempfile.TemporaryFile()
        except OSError as exc:  # pragma: no cover - depends on the host
            return ProcessResult(
                status=AnalyzerStatus.EXECUTION_ERROR,
                message=redact(f"could not create capture files: {exc}"),
                argv=tuple(argv),
            )

        with stdout_file, stderr_file:
            try:
                process = subprocess.Popen(
                    list(argv),
                    cwd=str(cwd or self._workdir),
                    env=self._environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    start_new_session=(os.name == "posix"),
                    preexec_fn=self._child_setup if os.name == "posix" else None,
                )
            except (OSError, ValueError) as exc:
                return ProcessResult(
                    status=AnalyzerStatus.EXECUTION_ERROR,
                    message=redact(f"could not start {Path(executable).name}: {exc}"),
                    duration_seconds=time.monotonic() - started,
                    argv=tuple(argv),
                )

            try:
                exit_code: Optional[int] = process.wait(timeout=timeout)
                status = AnalyzerStatus.OK
                message: Optional[str] = None
            except subprocess.TimeoutExpired:
                self._terminate(process)
                exit_code = None
                status = AnalyzerStatus.TIMEOUT
                message = f"timed out after {timeout:g}s"

            duration = time.monotonic() - started
            stdout, stdout_truncated = _read_limited(stdout_file, max_output_bytes)
            stderr, stderr_truncated = _read_limited(stderr_file, max(max_output_bytes // 4, 8192))

        return ProcessResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            truncated=stdout_truncated or stderr_truncated,
            message=message,
            argv=tuple(argv),
        )

    # --- internals ---------------------------------------------------------

    def _environment(self) -> dict[str, str]:
        env = {key: os.environ[key] for key in _ENV_PASSTHROUGH if key in os.environ}
        env.update(_ENV_EXPLICIT)
        env["HOME"] = str(self._home)
        env["TMPDIR"] = str(self._tmp)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONSTARTUP", None)
        return env

    def _child_setup(self) -> None:  # pragma: no cover - runs in the forked child
        """Apply rlimits in the child, before exec.

        `RLIMIT_NPROC` is deliberately *not* set: it is accounted per real UID, so
        a limit low enough to bound one analyzer would also cap every other process
        the service account owns — including the analyzer's own thread pool, which
        makes ruff/bandit die with "failed to spawn thread". The remaining limits
        bound the two resources an analyzer can actually exhaust (time, memory) plus
        the size of any file it writes.
        """
        limits = (
            (resource.RLIMIT_CPU, self._cpu_seconds, self._cpu_seconds),
            (resource.RLIMIT_AS, self._memory_bytes, self._memory_bytes),
            (resource.RLIMIT_FSIZE, self._file_bytes, self._file_bytes),
            (resource.RLIMIT_CORE, 0, 0),
        )
        for which, soft, hard in limits:
            try:
                current_soft, current_hard = resource.getrlimit(which)
            except (ValueError, OSError):
                continue
            if current_hard != resource.RLIM_INFINITY:
                soft = min(soft, current_hard)
                hard = min(hard, current_hard)
            try:
                resource.setrlimit(which, (soft, hard))
            except (ValueError, OSError):
                continue

    _cpu_seconds = 120
    _memory_bytes = 1024 * 1024 * 1024
    _file_bytes = 16 * 1024 * 1024

    def apply_limits(self, limits: ProcessLimits) -> None:
        """Set the rlimits used by the next spawned child."""
        self._cpu_seconds = limits.cpu_seconds
        self._memory_bytes = limits.memory_mb * 1024 * 1024
        self._file_bytes = limits.max_file_bytes or max(limits.max_output_bytes * 2, 16 * 1024 * 1024)

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        """Kill the process *and* its children where the platform allows it."""
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            else:  # pragma: no cover - non-POSIX hosts
                process.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - the process is already being abandoned
            log_event("analyzer_process_unreaped", level=30, pid=process.pid)


def _read_limited(handle, limit: int) -> tuple[str, bool]:
    handle.seek(0)
    data = handle.read(limit + 1)
    truncated = len(data) > limit
    return data[:limit].decode("utf-8", "replace"), truncated

