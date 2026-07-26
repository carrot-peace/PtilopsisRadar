# coding=utf-8
"""Domain-specific SQLite repository implementation."""

from typing import Any, Dict, List, Optional

from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.storage.results import ItemFailure, WriteResult
from trendradar.utils.url import normalize_url

class SQLiteScheduleRepositoryMixin:
    def _has_period_executed_impl(self, date_str: str, period_key: str, action: str) -> bool:
        """
        检查指定时间段的某个 action 今天是否已执行

        Args:
            date_str: 日期字符串 YYYY-MM-DD
            period_key: 时间段 key
            action: 动作标识（当前为 analyze）

        Returns:
            是否已执行
        """
        try:
            conn = self._get_connection(date_str)
            cursor = conn.cursor()

            # 先检查表是否存在
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='period_executions'
            """)
            if not cursor.fetchone():
                return False

            cursor.execute("""
                SELECT 1 FROM period_executions
                WHERE execution_date = ? AND period_key = ? AND action = ?
            """, (date_str, period_key, action))

            return cursor.fetchone() is not None

        except Exception as e:
            print(f"[存储] 检查时间段执行记录失败: {e}")
            return False

    def _record_period_execution_impl(self, date_str: str, period_key: str, action: str) -> bool:
        """
        记录时间段的 action 执行

        Args:
            date_str: 日期字符串 YYYY-MM-DD
            period_key: 时间段 key
            action: 动作标识（当前为 analyze）

        Returns:
            是否记录成功
        """
        try:
            conn = self._get_connection(date_str)
            with self._unit_of_work(conn) as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS period_executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        execution_date TEXT NOT NULL,
                        period_key TEXT NOT NULL,
                        action TEXT NOT NULL,
                        executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(execution_date, period_key, action)
                    )
                """)
                now_str = self._get_configured_time().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    INSERT OR IGNORE INTO period_executions
                    (execution_date, period_key, action, executed_at)
                    VALUES (?, ?, ?, ?)
                """, (date_str, period_key, action, now_str))
            return True

        except Exception as e:
            print(f"[存储] 记录时间段执行失败: {e}")
            return False
