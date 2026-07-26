"""MCP news aggregation and period-comparison analytics."""

from .analytics_common import (
    Counter,
    DataNotFoundError,
    Dict,
    InvalidParameterError,
    List,
    MCPError,
    Optional,
    Union,
    calculate_news_weight,
    datetime,
    re,
    timedelta,
    validate_date_range,
    validate_limit,
    validate_platforms,
    validate_threshold,
    validate_top_n,
)


class AnalyticsAggregationMixin:
    def aggregate_news(
        self,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        platforms: Optional[List[str]] = None,
        similarity_threshold: float = 0.7,
        limit: int = 50,
        include_url: bool = False
    ) -> Dict:
        """
        跨平台新闻聚合 - 对相似新闻进行去重合并

        将不同平台报道的同一事件合并为一条聚合新闻，
        显示该新闻在各平台的覆盖情况和综合热度。

        Args:
            date_range: 日期范围（可选）
                - 不指定: 查询今天
                - {\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\"}: 日期范围
            platforms: 平台过滤列表，如 ['zhihu', 'weibo']
            similarity_threshold: 相似度阈值，0-1之间，默认0.7
            limit: 返回聚合新闻数量，默认50
            include_url: 是否包含URL链接，默认False

        Returns:
            聚合结果字典，包含：
            - aggregated_news: 聚合后的新闻列表
            - statistics: 聚合统计信息
        """
        try:
            # 参数验证
            platforms = validate_platforms(platforms)
            similarity_threshold = validate_threshold(
                similarity_threshold, default=0.7, min_value=0.3, max_value=1.0
            )
            limit = validate_limit(limit, default=50)

            # 处理日期范围
            if date_range:
                date_range_tuple = validate_date_range(date_range)
                start_date, end_date = date_range_tuple
            else:
                start_date = end_date = datetime.now()

            # 收集所有新闻
            all_news = []
            current_date = start_date

            while current_date <= end_date:
                try:
                    all_titles, id_to_name, _ = self.analytics_service.read_news(
                        date=current_date,
                        platforms=platforms
                    )

                    for platform_id, titles in all_titles.items():
                        platform_name = id_to_name.get(platform_id, platform_id)

                        for title, info in titles.items():
                            news_item = {
                                "title": title,
                                "platform": platform_id,
                                "platform_name": platform_name,
                                "date": current_date.strftime("%Y-%m-%d"),
                                "ranks": info.get("ranks", []),
                                "count": len(info.get("ranks", [])),
                                "rank": info["ranks"][0] if info["ranks"] else 999
                            }

                            if include_url:
                                news_item["url"] = info.get("url", "")
                                news_item["mobileUrl"] = info.get("mobileUrl", "")

                            # 计算权重
                            news_item["weight"] = calculate_news_weight(news_item)
                            all_news.append(news_item)

                except DataNotFoundError:
                    pass

                current_date += timedelta(days=1)

            if not all_news:
                return {
                    "success": True,
                    "summary": {
                        "description": "跨平台新闻聚合结果",
                        "total": 0,
                        "returned": 0
                    },
                    "data": [],
                    "message": "未找到新闻数据"
                }

            # 执行聚合
            aggregated = self._aggregate_similar_news(
                all_news, similarity_threshold, include_url
            )

            # 按综合权重排序
            aggregated.sort(key=lambda x: x["aggregate_weight"], reverse=True)

            # 限制返回数量
            results = aggregated[:limit]

            # 统计信息
            total_original = len(all_news)
            total_aggregated = len(aggregated)
            dedup_rate = 1 - (total_aggregated / total_original) if total_original > 0 else 0

            platform_coverage = Counter()
            for item in aggregated:
                for p in item["platforms"]:
                    platform_coverage[p] += 1

            return {
                "success": True,
                "summary": {
                    "description": "跨平台新闻聚合结果",
                    "original_count": total_original,
                    "aggregated_count": total_aggregated,
                    "returned": len(results),
                    "deduplication_rate": f"{dedup_rate * 100:.1f}%",
                    "similarity_threshold": similarity_threshold,
                    "date_range": {
                        "start": start_date.strftime("%Y-%m-%d"),
                        "end": end_date.strftime("%Y-%m-%d")
                    }
                },
                "data": results,
                "statistics": {
                    "platform_coverage": dict(platform_coverage),
                    "multi_platform_news": len([a for a in aggregated if len(a["platforms"]) > 1]),
                    "single_platform_news": len([a for a in aggregated if len(a["platforms"]) == 1])
                }
            }

        except MCPError as e:
            return {"success": False, "error": e.to_dict()}
        except Exception as e:
            return {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}}

    def _aggregate_similar_news(
        self,
        news_list: List[Dict],
        threshold: float,
        include_url: bool
    ) -> List[Dict]:
        """
        对新闻列表进行相似度聚合

        使用双层过滤策略：先用 Jaccard 快速粗筛，再用 SequenceMatcher 精确计算

        Args:
            news_list: 新闻列表
            threshold: 相似度阈值
            include_url: 是否包含URL

        Returns:
            聚合后的新闻列表
        """
        if not news_list:
            return []

        # 预计算字符集合用于快速过滤
        prepared_news = []
        for news in news_list:
            char_set = set(news["title"])
            prepared_news.append({
                "data": news,
                "char_set": char_set,
                "set_len": len(char_set)
            })

        # 按权重排序
        sorted_items = sorted(prepared_news, key=lambda x: x["data"].get("weight", 0), reverse=True)

        aggregated = []
        used_indices = set()
        PRE_FILTER_RATIO = 0.5  # 粗筛阈值系数

        for i, item in enumerate(sorted_items):
            if i in used_indices:
                continue

            news = item["data"]
            base_set = item["char_set"]
            base_len = item["set_len"]

            group = {
                "representative_title": news["title"],
                "platforms": [news["platform_name"]],
                "platform_ids": [news["platform"]],
                "dates": [news["date"]],
                "best_rank": news["rank"],
                "total_count": news["count"],
                "aggregate_weight": news.get("weight", 0),
                "sources": [{
                    "platform": news["platform_name"],
                    "rank": news["rank"],
                    "date": news["date"]
                }]
            }

            if include_url and news.get("url"):
                group["urls"] = [{
                    "platform": news["platform_name"],
                    "url": news.get("url", ""),
                    "mobileUrl": news.get("mobileUrl", "")
                }]

            used_indices.add(i)

            # 查找相似新闻
            for j in range(i + 1, len(sorted_items)):
                if j in used_indices:
                    continue

                compare_item = sorted_items[j]
                compare_set = compare_item["char_set"]
                compare_len = compare_item["set_len"]

                # 快速粗筛：长度检查
                if base_len == 0 or compare_len == 0:
                    continue

                # 快速粗筛：长度比例检查
                if min(base_len, compare_len) / max(base_len, compare_len) < (threshold * PRE_FILTER_RATIO):
                    continue

                # 快速粗筛：Jaccard 相似度
                intersection = len(base_set & compare_set)
                union = len(base_set | compare_set)
                jaccard_sim = intersection / union if union > 0 else 0

                if jaccard_sim < (threshold * PRE_FILTER_RATIO):
                    continue

                # 精确计算：SequenceMatcher
                other_news = compare_item["data"]
                real_similarity = self._calculate_similarity(news["title"], other_news["title"])

                if real_similarity >= threshold:
                    # 合并到当前组
                    if other_news["platform_name"] not in group["platforms"]:
                        group["platforms"].append(other_news["platform_name"])
                        group["platform_ids"].append(other_news["platform"])

                    if other_news["date"] not in group["dates"]:
                        group["dates"].append(other_news["date"])

                    group["best_rank"] = min(group["best_rank"], other_news["rank"])
                    group["total_count"] += other_news["count"]
                    group["aggregate_weight"] += other_news.get("weight", 0) * 0.5  # 额外权重

                    group["sources"].append({
                        "platform": other_news["platform_name"],
                        "rank": other_news["rank"],
                        "date": other_news["date"]
                    })

                    if include_url and other_news.get("url"):
                        if "urls" not in group:
                            group["urls"] = []
                        group["urls"].append({
                            "platform": other_news["platform_name"],
                            "url": other_news.get("url", ""),
                            "mobileUrl": other_news.get("mobileUrl", "")
                        })

                    used_indices.add(j)

            # 添加聚合信息
            group["platform_count"] = len(group["platforms"])
            group["is_cross_platform"] = len(group["platforms"]) > 1

            aggregated.append(group)

        return aggregated

    # ==================== 时期对比分析工具 ====================

    def compare_periods(
        self,
        period1: Union[Dict[str, str], str],
        period2: Union[Dict[str, str], str],
        topic: Optional[str] = None,
        compare_type: str = "overview",
        platforms: Optional[List[str]] = None,
        top_n: int = 10
    ) -> Dict:
        """
        时期对比分析 - 比较两个时间段的新闻数据

        支持多种对比维度：热度对比、话题变化、平台活跃度等。

        Args:
            period1: 第一个时间段
                - {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}: 日期范围
                - "today", "yesterday", "last_week", "last_month": 预设值
            period2: 第二个时间段（格式同 period1）
            topic: 可选的话题关键词（聚焦特定话题的对比）
            compare_type: 对比类型
                - "overview": 总体概览（默认）
                - "topic_shift": 话题变化分析
                - "platform_activity": 平台活跃度对比
            platforms: 平台过滤列表
            top_n: 返回 TOP N 结果，默认10

        Returns:
            对比分析结果字典
        """
        try:
            # 参数验证
            platforms = validate_platforms(platforms)
            top_n = validate_top_n(top_n, default=10)

            if compare_type not in ["overview", "topic_shift", "platform_activity"]:
                raise InvalidParameterError(
                    f"不支持的对比类型: {compare_type}",
                    suggestion="支持的类型: overview, topic_shift, platform_activity"
                )

            # 解析时间段
            date_range1 = self._parse_period(period1)
            date_range2 = self._parse_period(period2)

            if not date_range1 or not date_range2:
                raise InvalidParameterError(
                    "无效的时间段格式",
                    suggestion="使用 {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'} 或预设值如 'last_week'"
                )

            # 收集两个时期的数据
            data1 = self._collect_period_data(date_range1, platforms, topic)
            data2 = self._collect_period_data(date_range2, platforms, topic)

            # 根据对比类型执行不同的分析
            if compare_type == "overview":
                analysis_result = self._compare_overview(data1, data2, date_range1, date_range2, top_n)
            elif compare_type == "topic_shift":
                analysis_result = self._compare_topic_shift(data1, data2, date_range1, date_range2, top_n)
            else:  # platform_activity
                analysis_result = self._compare_platform_activity(data1, data2, date_range1, date_range2)

            result = {
                "success": True,
                "summary": {
                    "description": f"时期对比分析（{compare_type}）",
                    "compare_type": compare_type,
                    "periods": {
                        "period1": {
                            "start": date_range1[0].strftime("%Y-%m-%d"),
                            "end": date_range1[1].strftime("%Y-%m-%d")
                        },
                        "period2": {
                            "start": date_range2[0].strftime("%Y-%m-%d"),
                            "end": date_range2[1].strftime("%Y-%m-%d")
                        }
                    }
                },
                "data": analysis_result
            }

            if topic:
                result["summary"]["topic_filter"] = topic

            return result

        except MCPError as e:
            return {"success": False, "error": e.to_dict()}
        except Exception as e:
            return {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}}

    def _parse_period(self, period: Union[Dict[str, str], str]) -> Optional[tuple]:
        """解析时间段为日期范围元组"""
        today = datetime.now()

        if isinstance(period, str):
            if period == "today":
                return (today, today)
            elif period == "yesterday":
                yesterday = today - timedelta(days=1)
                return (yesterday, yesterday)
            elif period == "last_week":
                return (today - timedelta(days=7), today - timedelta(days=1))
            elif period == "this_week":
                # 本周一到今天
                days_since_monday = today.weekday()
                monday = today - timedelta(days=days_since_monday)
                return (monday, today)
            elif period == "last_month":
                return (today - timedelta(days=30), today - timedelta(days=1))
            elif period == "this_month":
                first_of_month = today.replace(day=1)
                return (first_of_month, today)
            else:
                return None
        elif isinstance(period, dict):
            try:
                start = datetime.strptime(period["start"], "%Y-%m-%d")
                end = datetime.strptime(period["end"], "%Y-%m-%d")
                return (start, end)
            except (KeyError, ValueError):
                return None
        return None

    def _collect_period_data(
        self,
        date_range: tuple,
        platforms: Optional[List[str]],
        topic: Optional[str]
    ) -> Dict:
        """收集指定时期的新闻数据"""
        start_date, end_date = date_range
        all_news = []
        all_keywords = Counter()
        platform_stats = Counter()

        current_date = start_date
        while current_date <= end_date:
            try:
                all_titles, id_to_name, _ = self.analytics_service.read_news(
                    date=current_date,
                    platforms=platforms
                )

                for platform_id, titles in all_titles.items():
                    platform_name = id_to_name.get(platform_id, platform_id)

                    for title, info in titles.items():
                        # 如果指定了话题，过滤不相关的新闻
                        if topic and topic.lower() not in title.lower():
                            continue

                        news_item = {
                            "title": title,
                            "platform": platform_id,
                            "platform_name": platform_name,
                            "date": current_date.strftime("%Y-%m-%d"),
                            "ranks": info.get("ranks", []),
                            "rank": info["ranks"][0] if info["ranks"] else 999
                        }
                        news_item["weight"] = calculate_news_weight(news_item)
                        all_news.append(news_item)

                        # 统计平台
                        platform_stats[platform_name] += 1

                        # 提取关键词
                        keywords = self._extract_keywords(title)
                        all_keywords.update(keywords)

            except DataNotFoundError:
                pass

            current_date += timedelta(days=1)

        return {
            "news": all_news,
            "news_count": len(all_news),
            "keywords": all_keywords,
            "platform_stats": platform_stats,
            "date_range": date_range
        }

    def _compare_overview(
        self,
        data1: Dict,
        data2: Dict,
        range1: tuple,
        range2: tuple,
        top_n: int
    ) -> Dict:
        """总体概览对比"""
        # 计算变化
        count_change = data2["news_count"] - data1["news_count"]
        count_change_pct = (count_change / data1["news_count"] * 100) if data1["news_count"] > 0 else 0

        # TOP 关键词对比
        top_kw1 = [kw for kw, _ in data1["keywords"].most_common(top_n)]
        top_kw2 = [kw for kw, _ in data2["keywords"].most_common(top_n)]

        new_keywords = [kw for kw in top_kw2 if kw not in top_kw1]
        disappeared_keywords = [kw for kw in top_kw1 if kw not in top_kw2]
        persistent_keywords = [kw for kw in top_kw1 if kw in top_kw2]

        # TOP 新闻对比
        top_news1 = sorted(data1["news"], key=lambda x: x.get("weight", 0), reverse=True)[:top_n]
        top_news2 = sorted(data2["news"], key=lambda x: x.get("weight", 0), reverse=True)[:top_n]

        return {
            "overview": {
                "period1_count": data1["news_count"],
                "period2_count": data2["news_count"],
                "count_change": count_change,
                "count_change_percent": f"{count_change_pct:+.1f}%"
            },
            "keyword_analysis": {
                "new_keywords": new_keywords[:5],
                "disappeared_keywords": disappeared_keywords[:5],
                "persistent_keywords": persistent_keywords[:5]
            },
            "top_news": {
                "period1": [{"title": n["title"], "platform": n["platform_name"]} for n in top_news1],
                "period2": [{"title": n["title"], "platform": n["platform_name"]} for n in top_news2]
            }
        }

    def _compare_topic_shift(
        self,
        data1: Dict,
        data2: Dict,
        range1: tuple,
        range2: tuple,
        top_n: int
    ) -> Dict:
        """话题变化分析"""
        kw1 = data1["keywords"]
        kw2 = data2["keywords"]

        # 计算热度变化
        all_keywords = set(kw1.keys()) | set(kw2.keys())
        keyword_changes = []

        for kw in all_keywords:
            count1 = kw1.get(kw, 0)
            count2 = kw2.get(kw, 0)
            change = count2 - count1

            if count1 > 0:
                change_pct = (change / count1) * 100
            elif count2 > 0:
                change_pct = 100  # 新出现
            else:
                change_pct = 0

            keyword_changes.append({
                "keyword": kw,
                "period1_count": count1,
                "period2_count": count2,
                "change": change,
                "change_percent": round(change_pct, 1)
            })

        # 按变化幅度排序
        rising = sorted([k for k in keyword_changes if k["change"] > 0],
                       key=lambda x: x["change"], reverse=True)[:top_n]
        falling = sorted([k for k in keyword_changes if k["change"] < 0],
                        key=lambda x: x["change"])[:top_n]
        new_topics = [k for k in keyword_changes if k["period1_count"] == 0 and k["period2_count"] > 0][:top_n]

        return {
            "rising_topics": rising,
            "falling_topics": falling,
            "new_topics": new_topics,
            "total_keywords": {
                "period1": len(kw1),
                "period2": len(kw2)
            }
        }

    def _compare_platform_activity(
        self,
        data1: Dict,
        data2: Dict,
        range1: tuple,
        range2: tuple
    ) -> Dict:
        """平台活跃度对比"""
        ps1 = data1["platform_stats"]
        ps2 = data2["platform_stats"]

        all_platforms = set(ps1.keys()) | set(ps2.keys())
        platform_changes = []

        for platform in all_platforms:
            count1 = ps1.get(platform, 0)
            count2 = ps2.get(platform, 0)
            change = count2 - count1

            if count1 > 0:
                change_pct = (change / count1) * 100
            elif count2 > 0:
                change_pct = 100
            else:
                change_pct = 0

            platform_changes.append({
                "platform": platform,
                "period1_count": count1,
                "period2_count": count2,
                "change": change,
                "change_percent": round(change_pct, 1)
            })

        # 按变化排序
        platform_changes.sort(key=lambda x: x["change"], reverse=True)

        return {
            "platform_comparison": platform_changes,
            "most_active_growth": platform_changes[0] if platform_changes else None,
            "least_active_growth": platform_changes[-1] if platform_changes else None,
            "total_activity": {
                "period1": sum(ps1.values()),
                "period2": sum(ps2.values())
            }
        }
