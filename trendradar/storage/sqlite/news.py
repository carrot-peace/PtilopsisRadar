# coding=utf-8
"""Domain-specific SQLite repository implementation."""

from typing import Any, Dict, List, Optional

from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.storage.results import ItemFailure, WriteResult
from trendradar.utils.url import normalize_url

class SQLiteNewsRepositoryMixin:
    def _save_news_data_impl(
        self,
        data: NewsData,
        log_prefix: str = "[存储]",
    ) -> WriteResult:
        """
        保存新闻数据到 SQLite（核心实现）

        Args:
            data: 新闻数据
            log_prefix: 日志前缀

        Returns:
            Atomic write outcome and counters.
        """
        try:
            conn = self._get_connection(data.date)
            with self._unit_of_work(conn) as cursor:
                now_str = self._get_configured_time().strftime("%Y-%m-%d %H:%M:%S")

                for source_id, source_name in data.id_to_name.items():
                    cursor.execute("""
                        INSERT INTO platforms (id, name, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name = excluded.name,
                            updated_at = excluded.updated_at
                    """, (source_id, source_name, now_str))

                new_count = 0
                updated_count = 0
                title_changed_count = 0
                success_sources = []

                for source_id, news_list in data.items.items():
                    success_sources.append(source_id)

                    for item in news_list:
                        normalized_url = normalize_url(item.url, source_id) if item.url else ""

                        if normalized_url:
                            cursor.execute("""
                                SELECT id, title FROM news_items
                                WHERE url = ? AND platform_id = ?
                            """, (normalized_url, source_id))
                            existing = cursor.fetchone()

                            if existing:
                                existing_id, existing_title = existing
                                update_title = item.title
                                if (
                                    update_title
                                    and update_title.strip().startswith(("http://", "https://", "//"))
                                    and existing_title
                                    and not existing_title.strip().startswith(("http://", "https://", "//"))
                                ):
                                    update_title = existing_title

                                if existing_title != update_title:
                                    cursor.execute("""
                                        INSERT INTO title_changes
                                        (news_item_id, old_title, new_title, changed_at)
                                        VALUES (?, ?, ?, ?)
                                    """, (existing_id, existing_title, update_title, now_str))
                                    title_changed_count += 1

                                cursor.execute("""
                                    INSERT INTO rank_history
                                    (news_item_id, rank, crawl_time, created_at)
                                    VALUES (?, ?, ?, ?)
                                """, (existing_id, item.rank, data.crawl_time, now_str))
                                cursor.execute("""
                                    UPDATE news_items SET
                                        title = ?,
                                        rank = ?,
                                        mobile_url = ?,
                                        last_crawl_time = ?,
                                        crawl_count = crawl_count + 1,
                                        updated_at = ?
                                    WHERE id = ?
                                """, (
                                    update_title,
                                    item.rank,
                                    item.mobile_url,
                                    data.crawl_time,
                                    now_str,
                                    existing_id,
                                ))
                                updated_count += 1
                            else:
                                cursor.execute("""
                                    INSERT INTO news_items
                                    (title, platform_id, rank, url, mobile_url,
                                     first_crawl_time, last_crawl_time, crawl_count,
                                     created_at, updated_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                                """, (
                                    item.title,
                                    source_id,
                                    item.rank,
                                    normalized_url,
                                    item.mobile_url,
                                    data.crawl_time,
                                    data.crawl_time,
                                    now_str,
                                    now_str,
                                ))
                                new_id = cursor.lastrowid
                                cursor.execute("""
                                    INSERT INTO rank_history
                                    (news_item_id, rank, crawl_time, created_at)
                                    VALUES (?, ?, ?, ?)
                                """, (new_id, item.rank, data.crawl_time, now_str))
                                new_count += 1
                        else:
                            cursor.execute("""
                                INSERT INTO news_items
                                (title, platform_id, rank, url, mobile_url,
                                 first_crawl_time, last_crawl_time, crawl_count,
                                 created_at, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                            """, (
                                item.title,
                                source_id,
                                item.rank,
                                "",
                                item.mobile_url,
                                data.crawl_time,
                                data.crawl_time,
                                now_str,
                                now_str,
                            ))
                            new_id = cursor.lastrowid
                            cursor.execute("""
                                INSERT INTO rank_history
                                (news_item_id, rank, crawl_time, created_at)
                                VALUES (?, ?, ?, ?)
                            """, (new_id, item.rank, data.crawl_time, now_str))
                            new_count += 1

                total_items = new_count + updated_count
                off_list_count = 0

                cursor.execute("""
                    SELECT crawl_time FROM crawl_records
                    WHERE crawl_time < ?
                    ORDER BY crawl_time DESC
                    LIMIT 1
                """, (data.crawl_time,))
                prev_record = cursor.fetchone()

                if prev_record:
                    prev_crawl_time = prev_record[0]
                    for source_id in success_sources:
                        current_urls = {
                            normalize_url(item.url, source_id)
                            for item in data.items.get(source_id, [])
                            if item.url
                        }
                        cursor.execute("""
                            SELECT id, url FROM news_items
                            WHERE platform_id = ?
                              AND last_crawl_time = ?
                              AND url != ''
                        """, (source_id, prev_crawl_time))

                        for row in cursor.fetchall():
                            news_id, url = row[0], row[1]
                            if url not in current_urls:
                                cursor.execute("""
                                    INSERT INTO rank_history
                                    (news_item_id, rank, crawl_time, created_at)
                                    VALUES (?, 0, ?, ?)
                                """, (news_id, data.crawl_time, now_str))
                                off_list_count += 1

                cursor.execute("""
                    INSERT OR REPLACE INTO crawl_records
                    (crawl_time, total_items, created_at)
                    VALUES (?, ?, ?)
                """, (data.crawl_time, total_items, now_str))
                cursor.execute("""
                    SELECT id FROM crawl_records WHERE crawl_time = ?
                """, (data.crawl_time,))
                record_row = cursor.fetchone()
                if record_row:
                    crawl_record_id = record_row[0]
                    for source_id in success_sources:
                        cursor.execute("""
                            INSERT OR REPLACE INTO crawl_source_status
                            (crawl_record_id, platform_id, status)
                            VALUES (?, ?, 'success')
                        """, (crawl_record_id, source_id))

                    for failed_id in data.failed_ids:
                        cursor.execute("""
                            INSERT OR IGNORE INTO platforms (id, name, updated_at)
                            VALUES (?, ?, ?)
                        """, (failed_id, failed_id, now_str))
                        cursor.execute("""
                            INSERT OR REPLACE INTO crawl_source_status
                            (crawl_record_id, platform_id, status)
                            VALUES (?, ?, 'failed')
                        """, (crawl_record_id, failed_id))

            return WriteResult(
                committed=True,
                inserted=new_count,
                updated=updated_count,
                title_changed=title_changed_count,
                off_list=off_list_count,
            )

        except Exception as e:
            print(f"{log_prefix} 保存失败: {e}")
            return WriteResult(
                committed=False,
                failures=(
                    ItemFailure(
                        identity=data.crawl_time,
                        operation="save_news_data",
                        error_code=type(e).__name__,
                        message=str(e),
                    ),
                ),
            )

    def _get_today_all_data_impl(self, date: Optional[str] = None) -> Optional[NewsData]:
        """
        获取指定日期的所有新闻数据（合并后）

        Args:
            date: 日期字符串，默认为今天

        Returns:
            合并后的新闻数据
        """
        try:
            conn = self._get_connection(date)
            cursor = conn.cursor()

            # 获取所有新闻数据（包含 id 用于查询排名历史）
            cursor.execute("""
                SELECT n.id, n.title, n.platform_id, p.name as platform_name,
                       n.rank, n.url, n.mobile_url,
                       n.first_crawl_time, n.last_crawl_time, n.crawl_count
                FROM news_items n
                LEFT JOIN platforms p ON n.platform_id = p.id
                ORDER BY n.platform_id, n.last_crawl_time
            """)

            rows = cursor.fetchall()
            if not rows:
                return None

            # 收集所有 news_item_id
            news_ids = [row[0] for row in rows]

            # 批量查询排名历史（同时获取时间和排名）
            # 过滤逻辑：只保留 last_crawl_time 之前的脱榜记录（rank=0）
            # 这样可以避免显示新闻永久脱榜后的无意义记录
            rank_history_map: Dict[int, List[int]] = {}
            rank_timeline_map: Dict[int, List[Dict[str, Any]]] = {}
            if news_ids:
                placeholders = ",".join("?" * len(news_ids))
                cursor.execute(f"""
                    SELECT rh.news_item_id, rh.rank, rh.crawl_time
                    FROM rank_history rh
                    JOIN news_items ni ON rh.news_item_id = ni.id
                    WHERE rh.news_item_id IN ({placeholders})
                      AND NOT (rh.rank = 0 AND rh.crawl_time > ni.last_crawl_time)
                    ORDER BY rh.news_item_id, rh.crawl_time
                """, news_ids)
                for rh_row in cursor.fetchall():
                    news_id, rank, crawl_time = rh_row[0], rh_row[1], rh_row[2]

                    if not crawl_time:
                        continue

                    # 构建 ranks 列表（去重，排除脱榜记录 rank=0）
                    if news_id not in rank_history_map:
                        rank_history_map[news_id] = []
                    if rank != 0 and rank not in rank_history_map[news_id]:
                        rank_history_map[news_id].append(rank)

                    # 构建 rank_timeline 列表（完整时间线，包含脱榜）
                    if news_id not in rank_timeline_map:
                        rank_timeline_map[news_id] = []
                    # 提取时间部分（HH:MM）
                    try:
                        time_part = crawl_time.split()[1][:5] if ' ' in crawl_time else crawl_time[:5]
                    except (IndexError, AttributeError):
                        time_part = "??:??"
                    rank_timeline_map[news_id].append({
                        "time": time_part,
                        "rank": rank if rank != 0 else None  # 0 转为 None 表示脱榜
                    })

            # 按 platform_id 分组
            items: Dict[str, List[NewsItem]] = {}
            id_to_name: Dict[str, str] = {}
            crawl_date = self._format_date_folder(date)

            for row in rows:
                news_id = row[0]
                platform_id = row[2]
                title = row[1]
                platform_name = row[3] or platform_id

                id_to_name[platform_id] = platform_name

                if platform_id not in items:
                    items[platform_id] = []

                # 获取排名历史，如果没有则使用当前排名
                ranks = rank_history_map.get(news_id, [row[4]])
                rank_timeline = rank_timeline_map.get(news_id, [])

                items[platform_id].append(NewsItem(
                    title=title,
                    source_id=platform_id,
                    source_name=platform_name,
                    rank=row[4],
                    url=row[5] or "",
                    mobile_url=row[6] or "",
                    crawl_time=row[8],  # last_crawl_time
                    ranks=ranks,
                    first_time=row[7],  # first_crawl_time
                    last_time=row[8],   # last_crawl_time
                    count=row[9],       # crawl_count
                    rank_timeline=rank_timeline,
                ))

            final_items = items

            # 获取失败的来源
            cursor.execute("""
                SELECT DISTINCT css.platform_id
                FROM crawl_source_status css
                JOIN crawl_records cr ON css.crawl_record_id = cr.id
                WHERE css.status = 'failed'
            """)
            failed_ids = [row[0] for row in cursor.fetchall()]

            # 获取最新的抓取时间
            cursor.execute("""
                SELECT crawl_time FROM crawl_records
                ORDER BY crawl_time DESC
                LIMIT 1
            """)

            time_row = cursor.fetchone()
            crawl_time = time_row[0] if time_row else self._format_time_filename()

            return NewsData(
                date=crawl_date,
                crawl_time=crawl_time,
                items=final_items,
                id_to_name=id_to_name,
                failed_ids=failed_ids,
            )

        except Exception as e:
            print(f"[存储] 读取数据失败: {e}")
            return None

    def _get_latest_crawl_data_impl(self, date: Optional[str] = None) -> Optional[NewsData]:
        """
        获取最新一次抓取的数据

        Args:
            date: 日期字符串，默认为今天

        Returns:
            最新抓取的新闻数据
        """
        try:
            conn = self._get_connection(date)
            cursor = conn.cursor()

            # 获取最新的抓取时间
            cursor.execute("""
                SELECT crawl_time FROM crawl_records
                ORDER BY crawl_time DESC
                LIMIT 1
            """)

            time_row = cursor.fetchone()
            if not time_row:
                return None

            latest_time = time_row[0]

            # 获取该时间的新闻数据（包含 id 用于查询排名历史）
            cursor.execute("""
                SELECT n.id, n.title, n.platform_id, p.name as platform_name,
                       n.rank, n.url, n.mobile_url,
                       n.first_crawl_time, n.last_crawl_time, n.crawl_count
                FROM news_items n
                LEFT JOIN platforms p ON n.platform_id = p.id
                WHERE n.last_crawl_time = ?
            """, (latest_time,))

            rows = cursor.fetchall()
            if not rows:
                return None

            # 收集所有 news_item_id
            news_ids = [row[0] for row in rows]

            # 批量查询排名历史（同时获取时间和排名）
            # 过滤逻辑：只保留 last_crawl_time 之前的脱榜记录（rank=0）
            # 这样可以避免显示新闻永久脱榜后的无意义记录
            rank_history_map: Dict[int, List[int]] = {}
            rank_timeline_map: Dict[int, List[Dict[str, Any]]] = {}
            if news_ids:
                placeholders = ",".join("?" * len(news_ids))
                cursor.execute(f"""
                    SELECT rh.news_item_id, rh.rank, rh.crawl_time
                    FROM rank_history rh
                    JOIN news_items ni ON rh.news_item_id = ni.id
                    WHERE rh.news_item_id IN ({placeholders})
                      AND NOT (rh.rank = 0 AND rh.crawl_time > ni.last_crawl_time)
                    ORDER BY rh.news_item_id, rh.crawl_time
                """, news_ids)
                for rh_row in cursor.fetchall():
                    news_id, rank, crawl_time = rh_row[0], rh_row[1], rh_row[2]

                    if not crawl_time:
                        continue

                    # 构建 ranks 列表（去重，排除脱榜记录 rank=0）
                    if news_id not in rank_history_map:
                        rank_history_map[news_id] = []
                    if rank != 0 and rank not in rank_history_map[news_id]:
                        rank_history_map[news_id].append(rank)

                    # 构建 rank_timeline 列表（完整时间线，包含脱榜）
                    if news_id not in rank_timeline_map:
                        rank_timeline_map[news_id] = []
                    # 提取时间部分（HH:MM）
                    try:
                        time_part = crawl_time.split()[1][:5] if ' ' in crawl_time else crawl_time[:5]
                    except (IndexError, AttributeError):
                        time_part = "??:??"
                    rank_timeline_map[news_id].append({
                        "time": time_part,
                        "rank": rank if rank != 0 else None  # 0 转为 None 表示脱榜
                    })

            items: Dict[str, List[NewsItem]] = {}
            id_to_name: Dict[str, str] = {}
            crawl_date = self._format_date_folder(date)

            for row in rows:
                news_id = row[0]
                platform_id = row[2]
                platform_name = row[3] or platform_id
                id_to_name[platform_id] = platform_name

                if platform_id not in items:
                    items[platform_id] = []

                # 获取排名历史，如果没有则使用当前排名
                ranks = rank_history_map.get(news_id, [row[4]])
                rank_timeline = rank_timeline_map.get(news_id, [])

                items[platform_id].append(NewsItem(
                    title=row[1],
                    source_id=platform_id,
                    source_name=platform_name,
                    rank=row[4],
                    url=row[5] or "",
                    mobile_url=row[6] or "",
                    crawl_time=row[8],  # last_crawl_time
                    ranks=ranks,
                    first_time=row[7],  # first_crawl_time
                    last_time=row[8],   # last_crawl_time
                    count=row[9],       # crawl_count
                    rank_timeline=rank_timeline,
                ))

            # 获取失败的来源（针对最新一次抓取）
            cursor.execute("""
                SELECT css.platform_id
                FROM crawl_source_status css
                JOIN crawl_records cr ON css.crawl_record_id = cr.id
                WHERE cr.crawl_time = ? AND css.status = 'failed'
            """, (latest_time,))

            failed_ids = [row[0] for row in cursor.fetchall()]

            return NewsData(
                date=crawl_date,
                crawl_time=latest_time,
                items=items,
                id_to_name=id_to_name,
                failed_ids=failed_ids,
            )

        except Exception as e:
            print(f"[存储] 获取最新数据失败: {e}")
            return None

    def _detect_new_titles_impl(self, current_data: NewsData) -> Dict[str, Dict]:
        """
        检测新增的标题

        该方法比较当前抓取数据与历史数据，找出新增的标题。
        关键逻辑：只有在历史批次中从未出现过的标题才算新增。

        Args:
            current_data: 当前抓取的数据

        Returns:
            新增的标题数据 {source_id: {title: NewsItem}}
        """
        try:
            # 获取历史数据
            historical_data = self._get_today_all_data_impl(current_data.date)

            if not historical_data:
                # 没有历史数据，所有都是新的
                new_titles = {}
                for source_id, news_list in current_data.items.items():
                    new_titles[source_id] = {item.title: item for item in news_list}
                return new_titles

            # 获取当前批次时间
            current_time = current_data.crawl_time

            # 收集历史标题（first_time < current_time 的标题）
            # 这样可以正确处理同一标题因 URL 变化而产生多条记录的情况
            historical_titles: Dict[str, set] = {}
            for source_id, news_list in historical_data.items.items():
                historical_titles[source_id] = set()
                for item in news_list:
                    first_time = item.first_time or item.crawl_time
                    if first_time < current_time:
                        historical_titles[source_id].add(item.title)

            # 检查是否有历史数据
            has_historical_data = any(len(titles) > 0 for titles in historical_titles.values())
            if not has_historical_data:
                # 第一次抓取，没有"新增"概念
                return {}

            # 检测新增
            new_titles = {}
            for source_id, news_list in current_data.items.items():
                hist_set = historical_titles.get(source_id, set())
                for item in news_list:
                    if item.title not in hist_set:
                        if source_id not in new_titles:
                            new_titles[source_id] = {}
                        new_titles[source_id][item.title] = item

            return new_titles

        except Exception as e:
            print(f"[存储] 检测新标题失败: {e}")
            return {}

    def _is_first_crawl_today_impl(self, date: Optional[str] = None) -> bool:
        """
        检查是否是当天第一次抓取

        Args:
            date: 日期字符串，默认为今天

        Returns:
            是否是第一次抓取
        """
        try:
            conn = self._get_connection(date)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) as count FROM crawl_records
            """)

            row = cursor.fetchone()
            count = row[0] if row else 0

            # 如果只有一条或没有记录，视为第一次抓取
            return count <= 1

        except Exception as e:
            print(f"[存储] 检查首次抓取失败: {e}")
            return True

    def _get_crawl_times_impl(self, date: Optional[str] = None) -> List[str]:
        """
        获取指定日期的所有抓取时间列表

        Args:
            date: 日期字符串，默认为今天

        Returns:
            抓取时间列表（按时间排序）
        """
        try:
            conn = self._get_connection(date)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT crawl_time FROM crawl_records
                ORDER BY crawl_time
            """)

            rows = cursor.fetchall()
            return [row[0] for row in rows]

        except Exception as e:
            print(f"[存储] 获取抓取时间列表失败: {e}")
            return []

    def _get_all_news_ids_impl(self, date: Optional[str] = None) -> List[Dict]:
        """获取当日所有新闻的 id 和标题（用于 AI 筛选分类）"""
        try:
            conn = self._get_connection(date)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT n.id, n.title, n.platform_id, p.name as platform_name
                FROM news_items n
                LEFT JOIN platforms p ON n.platform_id = p.id
                ORDER BY n.id
            """)

            return [
                {
                    "id": row[0], "title": row[1],
                    "source_id": row[2], "source_name": row[3] or row[2],
                }
                for row in cursor.fetchall()
            ]
        except Exception as e:
            print(f"[AI筛选] 获取新闻列表失败: {e}")
            return []
