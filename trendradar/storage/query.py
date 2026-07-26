"""Read-only SQLite query repository shared by runtime-adjacent consumers."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


Snapshot = Tuple[Dict, Dict, Dict]


class SQLiteQueryRepository:
    """Read news/RSS snapshots without exposing SQL to MCP services."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)

    def database_path(
        self,
        date: str,
        db_type: str = "news",
    ) -> Optional[Path]:
        path = self.data_dir / db_type / f"{date}.db"
        return path if path.exists() else None

    def read_snapshot(
        self,
        date: str,
        source_ids: Optional[List[str]] = None,
        db_type: str = "news",
    ) -> Optional[Snapshot]:
        path = self.database_path(date, db_type)
        if path is None:
            return None

        connection = None
        try:
            connection = sqlite3.connect(str(path))
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            if db_type == "news":
                return self._read_news(cursor, source_ids)
            if db_type == "rss":
                return self._read_rss(cursor, source_ids)
            raise ValueError(f"Unsupported database type: {db_type}")
        except Exception as exc:
            print(f"Warning: 从 SQLite 读取数据失败: {exc}")
            return None
        finally:
            if connection is not None:
                connection.close()

    def _read_news(self, cursor, source_ids) -> Optional[Snapshot]:
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='news_items'
            """
        )
        if not cursor.fetchone():
            return None

        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            cursor.execute(
                f"""
                SELECT n.id, n.platform_id, p.name as platform_name, n.title,
                       n.rank, n.url, n.mobile_url,
                       n.first_crawl_time, n.last_crawl_time, n.crawl_count
                FROM news_items n
                LEFT JOIN platforms p ON n.platform_id = p.id
                WHERE n.platform_id IN ({placeholders})
                """,
                source_ids,
            )
        else:
            cursor.execute(
                """
                SELECT n.id, n.platform_id, p.name as platform_name, n.title,
                       n.rank, n.url, n.mobile_url,
                       n.first_crawl_time, n.last_crawl_time, n.crawl_count
                FROM news_items n
                LEFT JOIN platforms p ON n.platform_id = p.id
                """
            )

        rows = cursor.fetchall()
        news_ids = [row["id"] for row in rows]
        rank_history = {}
        if news_ids:
            placeholders = ",".join("?" for _ in news_ids)
            cursor.execute(
                f"""
                SELECT news_item_id, rank FROM rank_history
                WHERE news_item_id IN ({placeholders})
                ORDER BY news_item_id, crawl_time
                """,
                news_ids,
            )
            for row in cursor.fetchall():
                rank_history.setdefault(row["news_item_id"], []).append(
                    row["rank"]
                )

        all_titles = {}
        id_to_name = {}
        for row in rows:
            source_id = row["platform_id"]
            id_to_name.setdefault(
                source_id,
                row["platform_name"] or source_id,
            )
            all_titles.setdefault(source_id, {})[row["title"]] = {
                "ranks": rank_history.get(row["id"], [row["rank"]]),
                "url": row["url"] or "",
                "mobileUrl": row["mobile_url"] or "",
                "first_time": row["first_crawl_time"] or "",
                "last_time": row["last_crawl_time"] or "",
                "count": row["crawl_count"] or 1,
            }

        if not all_titles:
            return None
        return all_titles, id_to_name, self._read_timestamps(
            cursor,
            table="crawl_records",
        )

    def _read_rss(self, cursor, source_ids) -> Optional[Snapshot]:
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='rss_items'
            """
        )
        if not cursor.fetchone():
            return None

        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            cursor.execute(
                f"""
                SELECT i.feed_id, f.name as feed_name, i.title,
                       i.url, i.published_at, i.summary, i.author,
                       i.first_crawl_time, i.last_crawl_time, i.crawl_count
                FROM rss_items i
                LEFT JOIN rss_feeds f ON i.feed_id = f.id
                WHERE i.feed_id IN ({placeholders})
                ORDER BY i.published_at DESC
                """,
                source_ids,
            )
        else:
            cursor.execute(
                """
                SELECT i.feed_id, f.name as feed_name, i.title,
                       i.url, i.published_at, i.summary, i.author,
                       i.first_crawl_time, i.last_crawl_time, i.crawl_count
                FROM rss_items i
                LEFT JOIN rss_feeds f ON i.feed_id = f.id
                ORDER BY i.published_at DESC
                """
            )

        all_items = {}
        id_to_name = {}
        for row in cursor.fetchall():
            feed_id = row["feed_id"]
            id_to_name.setdefault(feed_id, row["feed_name"] or feed_id)
            all_items.setdefault(feed_id, {})[row["title"]] = {
                "url": row["url"] or "",
                "published_at": row["published_at"] or "",
                "summary": row["summary"] or "",
                "author": row["author"] or "",
                "first_time": row["first_crawl_time"] or "",
                "last_time": row["last_crawl_time"] or "",
                "count": row["crawl_count"] or 1,
            }

        if not all_items:
            return None
        return all_items, id_to_name, self._read_timestamps(
            cursor,
            table="rss_crawl_records",
        )

    @staticmethod
    def _read_timestamps(cursor, *, table: str) -> Dict[str, float]:
        cursor.execute(
            f"""
            SELECT crawl_time, created_at FROM {table}
            ORDER BY crawl_time
            """
        )
        timestamps = {}
        for row in cursor.fetchall():
            try:
                timestamp = datetime.strptime(
                    row["created_at"],
                    "%Y-%m-%d %H:%M:%S",
                ).timestamp()
            except (ValueError, TypeError):
                timestamp = datetime.now().timestamp()
            timestamps[f"{row['crawl_time']}.db"] = timestamp
        return timestamps

    def available_dates(self, db_type: str = "news") -> List[str]:
        directory = self.data_dir / db_type
        if not directory.exists():
            return []
        dates = [
            path.stem
            for path in directory.glob("*.db")
            if self._is_date(path.stem)
        ]
        return sorted(dates, reverse=True)

    @staticmethod
    def _is_date(value: str) -> bool:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return False
        return parsed.strftime("%Y-%m-%d") == value
