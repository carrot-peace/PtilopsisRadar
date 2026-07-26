# coding=utf-8
"""Domain-specific SQLite repository implementation."""

from typing import Any, Dict, List, Optional

from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.storage.results import ItemFailure, WriteResult
from trendradar.utils.url import normalize_url

class SQLiteRSSRepositoryMixin:
    def _save_rss_data_impl(
        self,
        data: RSSData,
        log_prefix: str = "[存储]",
    ) -> WriteResult:
        """
        保存 RSS 数据到 SQLite（以 URL 为唯一标识）

        Args:
            data: RSS 数据
            log_prefix: 日志前缀

        Returns:
            Atomic write outcome and counters.
        """
        try:
            conn = self._get_connection(data.date, db_type="rss")
            with self._unit_of_work(conn) as cursor:
                now_str = self._get_configured_time().strftime("%Y-%m-%d %H:%M:%S")

                for feed_id, feed_name in data.id_to_name.items():
                    cursor.execute("""
                        INSERT INTO rss_feeds (id, name, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name = excluded.name,
                            updated_at = excluded.updated_at
                    """, (feed_id, feed_name, now_str))

                new_count = 0
                updated_count = 0

                for feed_id, rss_list in data.items.items():
                    for item in rss_list:
                        item_guid = getattr(item, "guid", "") or ""
                        existing = None

                        if item_guid:
                            cursor.execute("""
                                SELECT id, title FROM rss_items
                                WHERE guid = ? AND feed_id = ?
                            """, (item_guid, feed_id))
                            existing = cursor.fetchone()

                        if not existing and item.url:
                            cursor.execute("""
                                SELECT id, title FROM rss_items
                                WHERE url = ? AND feed_id = ?
                            """, (item.url, feed_id))
                            existing = cursor.fetchone()

                        if existing:
                            existing_id = existing[0]
                            existing_title = existing[1]
                            update_title = item.title
                            if (
                                update_title
                                and update_title.strip().startswith(("http://", "https://", "//"))
                                and existing_title
                                and not existing_title.strip().startswith(("http://", "https://", "//"))
                            ):
                                update_title = existing_title
                            cursor.execute("""
                                UPDATE rss_items SET
                                    title = ?,
                                    url = CASE WHEN ? != '' THEN ? ELSE url END,
                                    guid = CASE WHEN ? != '' THEN ? ELSE guid END,
                                    published_at = ?,
                                    summary = ?,
                                    author = ?,
                                    last_crawl_time = ?,
                                    crawl_count = crawl_count + 1,
                                    updated_at = ?
                                WHERE id = ?
                            """, (
                                update_title,
                                item.url,
                                item.url,
                                item_guid,
                                item_guid,
                                item.published_at,
                                item.summary,
                                item.author,
                                data.crawl_time,
                                now_str,
                                existing_id,
                            ))
                            updated_count += 1
                        elif item.url or item_guid:
                            cursor.execute("""
                                INSERT INTO rss_items
                                (title, feed_id, url, guid, published_at, summary, author,
                                 first_crawl_time, last_crawl_time, crawl_count,
                                 created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                            """, (
                                item.title,
                                feed_id,
                                item.url,
                                item_guid,
                                item.published_at,
                                item.summary,
                                item.author,
                                data.crawl_time,
                                data.crawl_time,
                                now_str,
                                now_str,
                            ))
                            new_count += 1

                total_items = new_count + updated_count
                cursor.execute("""
                    INSERT OR REPLACE INTO rss_crawl_records
                    (crawl_time, total_items, created_at)
                    VALUES (?, ?, ?)
                """, (data.crawl_time, total_items, now_str))
                cursor.execute("""
                    SELECT id FROM rss_crawl_records WHERE crawl_time = ?
                """, (data.crawl_time,))
                record_row = cursor.fetchone()
                if record_row:
                    crawl_record_id = record_row[0]
                    for feed_id in data.items.keys():
                        cursor.execute("""
                            INSERT OR REPLACE INTO rss_crawl_status
                            (crawl_record_id, feed_id, status)
                            VALUES (?, ?, 'success')
                        """, (crawl_record_id, feed_id))

                    for failed_id in data.failed_ids:
                        cursor.execute("""
                            INSERT OR IGNORE INTO rss_feeds (id, name, updated_at)
                            VALUES (?, ?, ?)
                        """, (failed_id, failed_id, now_str))
                        cursor.execute("""
                            INSERT OR REPLACE INTO rss_crawl_status
                            (crawl_record_id, feed_id, status)
                            VALUES (?, ?, 'failed')
                        """, (crawl_record_id, failed_id))

            return WriteResult(
                committed=True,
                inserted=new_count,
                updated=updated_count,
            )

        except Exception as e:
            print(f"{log_prefix} 保存 RSS 数据失败: {e}")
            return WriteResult(
                committed=False,
                failures=(
                    ItemFailure(
                        identity=data.crawl_time,
                        operation="save_rss_data",
                        error_code=type(e).__name__,
                        message=str(e),
                    ),
                ),
            )

    def _get_rss_data_impl(self, date: Optional[str] = None) -> Optional[RSSData]:
        """
        获取指定日期的所有 RSS 数据

        Args:
            date: 日期字符串（YYYY-MM-DD），默认为今天

        Returns:
            RSSData 对象，如果没有数据返回 None
        """
        try:
            conn = self._get_connection(date, db_type="rss")
            cursor = conn.cursor()

            # 获取所有 RSS 数据
            cursor.execute("""
                SELECT i.id, i.title, i.feed_id, f.name as feed_name,
                       i.url, i.published_at, i.summary, i.author,
                       i.first_crawl_time, i.last_crawl_time, i.crawl_count
                FROM rss_items i
                LEFT JOIN rss_feeds f ON i.feed_id = f.id
                ORDER BY i.published_at DESC
            """)

            rows = cursor.fetchall()
            if not rows:
                return None

            items: Dict[str, List[RSSItem]] = {}
            id_to_name: Dict[str, str] = {}
            crawl_date = self._format_date_folder(date)

            for row in rows:
                feed_id = row[2]
                feed_name = row[3] or feed_id

                id_to_name[feed_id] = feed_name

                if feed_id not in items:
                    items[feed_id] = []

                items[feed_id].append(RSSItem(
                    title=row[1],
                    feed_id=feed_id,
                    feed_name=feed_name,
                    url=row[4] or "",
                    published_at=row[5] or "",
                    summary=row[6] or "",
                    author=row[7] or "",
                    crawl_time=row[9],
                    first_time=row[8],
                    last_time=row[9],
                    count=row[10],
                ))

            # 获取最新的抓取时间
            cursor.execute("""
                SELECT crawl_time FROM rss_crawl_records
                ORDER BY crawl_time DESC
                LIMIT 1
            """)
            time_row = cursor.fetchone()
            crawl_time = time_row[0] if time_row else self._format_time_filename()

            # 获取失败的源
            cursor.execute("""
                SELECT DISTINCT cs.feed_id
                FROM rss_crawl_status cs
                JOIN rss_crawl_records cr ON cs.crawl_record_id = cr.id
                WHERE cs.status = 'failed'
            """)
            failed_ids = [row[0] for row in cursor.fetchall()]

            return RSSData(
                date=crawl_date,
                crawl_time=crawl_time,
                items=items,
                id_to_name=id_to_name,
                failed_ids=failed_ids,
            )

        except Exception as e:
            print(f"[存储] 读取 RSS 数据失败: {e}")
            return None

    def _detect_new_rss_items_impl(self, current_data: RSSData) -> Dict[str, List[RSSItem]]:
        """
        检测新增的 RSS 条目（增量模式）

        该方法比较当前抓取数据与历史数据，找出新增的 RSS 条目。
        关键逻辑：只有在历史批次中从未出现过的 URL 才算新增。

        Args:
            current_data: 当前抓取的 RSS 数据

        Returns:
            新增的 RSS 条目 {feed_id: [RSSItem, ...]}
        """
        try:
            # 获取历史数据
            historical_data = self._get_rss_data_impl(current_data.date)

            if not historical_data:
                # 没有历史数据，所有都是新的
                return current_data.items.copy()

            # 获取当前批次时间
            current_time = current_data.crawl_time

            # 收集历史 URL（first_time < current_time 的条目）
            historical_urls: Dict[str, set] = {}
            for feed_id, rss_list in historical_data.items.items():
                historical_urls[feed_id] = set()
                for item in rss_list:
                    first_time = item.first_time or item.crawl_time
                    if first_time < current_time:
                        if item.url:
                            historical_urls[feed_id].add(item.url)

            # 检查是否有早于当前批次的历史数据
            has_historical_data = any(len(urls) > 0 for urls in historical_urls.values())
            if not has_historical_data:
                # 当天第一次抓取，所有条目都是新增
                return current_data.items.copy()

            # 检测新增
            new_items: Dict[str, List[RSSItem]] = {}
            for feed_id, rss_list in current_data.items.items():
                hist_set = historical_urls.get(feed_id, set())
                for item in rss_list:
                    # 通过 URL 判断是否新增
                    if item.url and item.url not in hist_set:
                        if feed_id not in new_items:
                            new_items[feed_id] = []
                        new_items[feed_id].append(item)

            return new_items

        except Exception as e:
            print(f"[存储] 检测新 RSS 条目失败: {e}")
            return {}

    def _get_latest_rss_data_impl(self, date: Optional[str] = None) -> Optional[RSSData]:
        """
        获取最新一次抓取的 RSS 数据（当前榜单模式）

        Args:
            date: 日期字符串（YYYY-MM-DD），默认为今天

        Returns:
            最新抓取的 RSS 数据，如果没有数据返回 None
        """
        try:
            conn = self._get_connection(date, db_type="rss")
            cursor = conn.cursor()

            # 获取最新的抓取时间
            cursor.execute("""
                SELECT crawl_time FROM rss_crawl_records
                ORDER BY crawl_time DESC
                LIMIT 1
            """)

            time_row = cursor.fetchone()
            if not time_row:
                return None

            latest_time = time_row[0]

            # 获取该时间的 RSS 数据
            cursor.execute("""
                SELECT i.id, i.title, i.feed_id, f.name as feed_name,
                       i.url, i.published_at, i.summary, i.author,
                       i.first_crawl_time, i.last_crawl_time, i.crawl_count
                FROM rss_items i
                LEFT JOIN rss_feeds f ON i.feed_id = f.id
                WHERE i.last_crawl_time = ?
                ORDER BY i.published_at DESC
            """, (latest_time,))

            rows = cursor.fetchall()
            if not rows:
                return None

            items: Dict[str, List[RSSItem]] = {}
            id_to_name: Dict[str, str] = {}
            crawl_date = self._format_date_folder(date)

            for row in rows:
                feed_id = row[2]
                feed_name = row[3] or feed_id

                id_to_name[feed_id] = feed_name

                if feed_id not in items:
                    items[feed_id] = []

                items[feed_id].append(RSSItem(
                    title=row[1],
                    feed_id=feed_id,
                    feed_name=feed_name,
                    url=row[4] or "",
                    published_at=row[5] or "",
                    summary=row[6] or "",
                    author=row[7] or "",
                    crawl_time=row[9],
                    first_time=row[8],
                    last_time=row[9],
                    count=row[10],
                ))

            # 获取失败的源（针对最新一次抓取）
            cursor.execute("""
                SELECT cs.feed_id
                FROM rss_crawl_status cs
                JOIN rss_crawl_records cr ON cs.crawl_record_id = cr.id
                WHERE cr.crawl_time = ? AND cs.status = 'failed'
            """, (latest_time,))

            failed_ids = [row[0] for row in cursor.fetchall()]

            return RSSData(
                date=crawl_date,
                crawl_time=latest_time,
                items=items,
                id_to_name=id_to_name,
                failed_ids=failed_ids,
            )

        except Exception as e:
            print(f"[存储] 获取最新 RSS 数据失败: {e}")
            return None

    def _get_all_rss_ids_impl(self, date: Optional[str] = None) -> List[Dict]:
        """获取当日所有 RSS 条目的 id 和标题（用于 AI 筛选分类）"""
        try:
            conn = self._get_connection(date, db_type="rss")
            cursor = conn.cursor()

            cursor.execute("""
                SELECT i.id, i.title, i.feed_id, f.name as feed_name, i.published_at
                FROM rss_items i
                LEFT JOIN rss_feeds f ON i.feed_id = f.id
                ORDER BY i.id
            """)

            return [
                {
                    "id": row[0], "title": row[1],
                    "source_id": row[2], "source_name": row[3] or row[2],
                    "published_at": row[4] or "",
                }
                for row in cursor.fetchall()
            ]
        except Exception as e:
            print(f"[AI筛选] 获取 RSS 列表失败: {e}")
            return []
