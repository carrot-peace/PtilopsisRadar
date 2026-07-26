# coding=utf-8
"""Composite SQLite storage behavior assembled from repository mixins."""

import sqlite3
from abc import abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

from trendradar.storage.sqlite.ai_filter import SQLiteAIFilterRepositoryMixin
from trendradar.storage.sqlite.news import SQLiteNewsRepositoryMixin
from trendradar.storage.sqlite.rss import SQLiteRSSRepositoryMixin
from trendradar.storage.sqlite.schedule import SQLiteScheduleRepositoryMixin
from trendradar.storage.unit_of_work import (
    BorrowedSQLiteUnitOfWork,
    SQLiteUnitOfWork,
)


class SQLiteStorageMixin(
    SQLiteNewsRepositoryMixin,
    SQLiteRSSRepositoryMixin,
    SQLiteScheduleRepositoryMixin,
    SQLiteAIFilterRepositoryMixin,
):
    """Connection, schema, and transaction mechanics shared by repositories."""

    @abstractmethod
    def _get_connection(self, date: Optional[str] = None, db_type: str = "news") -> sqlite3.Connection:
        """获取数据库连接"""
        pass

    @abstractmethod
    def _get_configured_time(self) -> datetime:
        """获取配置时区的当前时间"""
        pass

    @abstractmethod
    def _format_date_folder(self, date: Optional[str] = None) -> str:
        """格式化日期文件夹名 (ISO 格式: YYYY-MM-DD)"""
        pass

    @abstractmethod
    def _format_time_filename(self) -> str:
        """格式化时间文件名 (格式: HH-MM)"""
        pass

    def _unit_of_work(self, connection: sqlite3.Connection):
        if not getattr(self, "_sqlite_batch_active", False):
            return SQLiteUnitOfWork(connection)

        connections = getattr(self, "_sqlite_batch_connections", None)
        if connections is None:
            connections = {}
            self._sqlite_batch_connections = connections
        connection_id = id(connection)
        if connection_id not in connections:
            connection.execute("BEGIN IMMEDIATE")
            connections[connection_id] = connection
        return BorrowedSQLiteUnitOfWork(
            connection,
            on_error=self._mark_sqlite_batch_failed,
        )

    def _begin_sqlite_batch(self) -> None:
        if getattr(self, "_sqlite_batch_active", False):
            raise RuntimeError("Nested storage batches are not supported")
        self._sqlite_batch_active = True
        self._sqlite_batch_failed = False
        self._sqlite_batch_connections = {}

    def _mark_sqlite_batch_failed(self) -> None:
        self._sqlite_batch_failed = True

    def _finish_sqlite_batch(self, commit: bool) -> list[tuple[str, bool, str]]:
        connections = getattr(self, "_sqlite_batch_connections", {})
        labels = getattr(self, "_sqlite_connection_labels", {})
        batch_failed = getattr(self, "_sqlite_batch_failed", False)
        should_commit = commit and not batch_failed
        results = []
        try:
            for connection_id, connection in connections.items():
                label = labels.get(connection_id, str(connection_id))
                try:
                    if should_commit:
                        connection.commit()
                    else:
                        connection.rollback()
                    error = "batch write failed" if batch_failed else ""
                    results.append((label, should_commit, error))
                except Exception as error:
                    try:
                        connection.rollback()
                    except Exception:
                        pass
                    results.append((label, False, str(error)))
        finally:
            self._sqlite_batch_active = False
            self._sqlite_batch_failed = False
            self._sqlite_batch_connections = {}
        return results

    def _get_schema_path(self, db_type: str = "news") -> Path:
        """
        获取 schema.sql 文件路径

        Args:
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            schema 文件路径
        """
        if db_type == "rss":
            return Path(__file__).parent / "rss_schema.sql"
        return Path(__file__).parent / "schema.sql"

    def _get_ai_filter_schema_path(self) -> Path:
        """获取 AI 筛选 schema 文件路径"""
        return Path(__file__).parent / "ai_filter_schema.sql"

    def _init_tables(self, conn: sqlite3.Connection, db_type: str = "news") -> None:
        """
        从 schema.sql 初始化数据库表结构

        Args:
            conn: 数据库连接
            db_type: 数据库类型 ("news" 或 "rss")
        """
        schema_path = self._get_schema_path(db_type)

        if schema_path.exists():
            with open(schema_path, "r", encoding="utf-8") as f:
                schema_sql = f.read()
            conn.executescript(schema_sql)
        else:
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        # news 库额外加载 AI 筛选表结构
        if db_type == "news":
            ai_filter_schema = self._get_ai_filter_schema_path()
            if ai_filter_schema.exists():
                with open(ai_filter_schema, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())

        if db_type == "rss":
            self._migrate_rss_schema(conn)

        conn.commit()

    def _migrate_rss_schema(self, conn: sqlite3.Connection) -> None:
        """迁移 rss_items 表结构（为已有数据库添加 guid 列）"""
        cursor = conn.execute("PRAGMA table_info(rss_items)")
        columns = {row[1] for row in cursor.fetchall()}
        if "guid" not in columns:
            conn.execute("ALTER TABLE rss_items ADD COLUMN guid TEXT DEFAULT ''")
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_rss_guid_feed
                ON rss_items(guid, feed_id) WHERE guid != ''
            """)
