"""Typed outcomes returned by storage write operations."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ItemFailure:
    """Machine-readable details for a failed write operation."""

    identity: str
    operation: str
    error_code: str
    message: str


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome and counters for one atomic storage write."""

    committed: bool
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    title_changed: int = 0
    off_list: int = 0
    failures: tuple[ItemFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class DatabaseBatchResult:
    """Commit/upload outcome for one SQLite database in a batch."""

    database: str
    committed: bool
    uploaded: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Explicit outcome for a possibly multi-database batch."""

    committed: bool
    databases: tuple[DatabaseBatchResult, ...] = ()
    rolled_back: bool = False
