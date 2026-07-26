"""Explicit transaction boundary for SQLite writes."""

import sqlite3
from types import TracebackType
from typing import Callable, Optional, Type


class SQLiteUnitOfWork:
    """Commit a write block as one unit, or roll it back on any failure."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def __enter__(self) -> sqlite3.Cursor:
        self.connection.execute("BEGIN IMMEDIATE")
        return self.connection.cursor()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        if exc_type is not None:
            self.connection.rollback()
            return False

        try:
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return False


class BorrowedSQLiteUnitOfWork:
    """Yield a cursor while an outer batch owns commit and rollback."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        on_error: Optional[Callable[[], None]] = None,
    ):
        self.connection = connection
        self.on_error = on_error

    def __enter__(self) -> sqlite3.Cursor:
        return self.connection.cursor()

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        if exc_type is not None and self.on_error is not None:
            self.on_error()
        return False
