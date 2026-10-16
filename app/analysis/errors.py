"""Error taxonomy for the analysis engine.

Every failure that ends up on an `AnalysisRun` carries one of these categories,
so an operator can tell "the archive was malicious" from "bandit timed out"
without reading a message string. Messages are sanitised before they are stored
(see `app/analysis/redact.py`).
"""

from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    SOURCE_ACQUISITION = "source_acquisition"
    INVALID_SOURCE = "invalid_source"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    RESOURCE_LIMIT = "resource_limit"
    CONFIGURATION = "configuration"
    ANALYZER_UNAVAILABLE = "analyzer_unavailable"
    ANALYZER_TIMEOUT = "analyzer_timeout"
    ANALYZER_EXECUTION = "analyzer_execution"
    OUTPUT_PARSING = "output_parsing"
    PERSISTENCE = "persistence"
    AUTHORIZATION = "authorization"
    RATE_LIMITED = "rate_limited"
    STALE_RUN = "stale_run"
    ORCHESTRATION = "orchestration"


class AnalysisError(Exception):
    """Base class for engine failures that map onto an error category."""

    category: ErrorCategory = ErrorCategory.ORCHESTRATION

    def __init__(self, message: str, *, category: Optional[ErrorCategory] = None):
        super().__init__(message)
        if category is not None:
            self.category = category


class SourceAcquisitionError(AnalysisError):
    """The snapshot could not be obtained (download failed, file missing)."""

    category = ErrorCategory.SOURCE_ACQUISITION


class InvalidSourceError(AnalysisError):
    """The snapshot exists but is not a usable, safe source tree."""

    category = ErrorCategory.INVALID_SOURCE


class ResourceLimitError(AnalysisError):
    """A configured limit (size, count, depth, ratio) was exceeded."""

    category = ErrorCategory.RESOURCE_LIMIT


class PathValidationError(InvalidSourceError):
    """A path escaped the workspace or is otherwise unacceptable."""


class AnalysisConfigError(ValueError):
    """An override a client sent that the platform refuses to apply (→ 422)."""


class AnalyzerError(AnalysisError):
    """An analyzer invocation failed. Individual analyzers degrade the run."""

    category = ErrorCategory.ANALYZER_EXECUTION
