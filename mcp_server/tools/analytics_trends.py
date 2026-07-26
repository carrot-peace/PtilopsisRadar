"""MCP activity, lifecycle, viral, and prediction analytics."""

from .analytics_common import (
    Counter,
    DataNotFoundError,
    Dict,
    List,
    MCPError,
    Optional,
    SequenceMatcher,
    Union,
    defaultdict,
    datetime,
    re,
    timedelta,
    validate_date_range,
    validate_keyword,
    validate_limit,
    validate_threshold,
)


class AnalyticsTrendsMixin:
    def get_platform_activity_stats(
        self,
        date_range: Optional[Union[Dict[str, str], str]] = None
    ) -> Dict:
        """
        平台活跃度统计 - 统计各平台的发布频率和活跃时间段

        Args:
            date_range: 日期范围（可选）

        Returns:
            平台活跃度统计结果

        Examples:
            用户询问示例：
            - "统计各平台今天的活跃度"
            - "看看哪个平台更新最频繁"
            - "分析各平台的发布时间规律"

            代码调用示例：
            >>> # 查看各平台活跃度（假设今天是 2025-11-17）
            >>> result = tools.get_platform_activity_stats(
            ...     date_range={"start": "2025-11-08", "end": "2025-11-17"}
            ... )
            >>> print(result['platform_activity'])
        """
        try:
            # 参数验证
            date_range_tuple = validate_date_range(date_range)

            # 确定日期范围
            if date_range_tuple:
                start_date, end_date = date_range_tuple
            else:
                start_date = end_date = datetime.now()

            # 统计各平台活跃度
            platform_activity = defaultdict(lambda: {
                "total_updates": 0,
                "days_active": set(),
                "news_count": 0,
                "hourly_distribution": Counter()
            })

            # 遍历日期范围
            current_date = start_date
            while current_date <= end_date:
                try:
                    all_titles, id_to_name, timestamps = self.analytics_service.read_news(
                        date=current_date
                    )

                    for platform_id, titles in all_titles.items():
                        platform_name = id_to_name.get(platform_id, platform_id)

                        platform_activity[platform_name]["news_count"] += len(titles)
                        platform_activity[platform_name]["days_active"].add(current_date.strftime("%Y-%m-%d"))

                        # 统计更新次数（基于文件数量）
                        platform_activity[platform_name]["total_updates"] += len(timestamps)

                        # 统计时间分布（基于文件名中的时间）
                        for filename in timestamps.keys():
                            # 解析文件名中的小时（格式：HHMM.txt）
                            match = re.match(r'(\d{2})(\d{2})\.txt', filename)
                            if match:
                                hour = int(match.group(1))
                                platform_activity[platform_name]["hourly_distribution"][hour] += 1

                except DataNotFoundError:
                    pass

                current_date += timedelta(days=1)

            # 转换为可序列化的格式
            result_activity = {}
            for platform, stats in platform_activity.items():
                days_count = len(stats["days_active"])
                avg_news_per_day = stats["news_count"] / days_count if days_count > 0 else 0

                # 找出最活跃的时间段
                most_active_hours = stats["hourly_distribution"].most_common(3)

                result_activity[platform] = {
                    "total_updates": stats["total_updates"],
                    "news_count": stats["news_count"],
                    "days_active": days_count,
                    "avg_news_per_day": round(avg_news_per_day, 2),
                    "most_active_hours": [
                        {"hour": f"{hour:02d}:00", "count": count}
                        for hour, count in most_active_hours
                    ],
                    "activity_score": round(stats["news_count"] / max(days_count, 1), 2)
                }

            # 按活跃度排序
            sorted_platforms = sorted(
                result_activity.items(),
                key=lambda x: x[1]["activity_score"],
                reverse=True
            )

            return {
                "success": True,
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                },
                "platform_activity": dict(sorted_platforms),
                "most_active_platform": sorted_platforms[0][0] if sorted_platforms else None,
                "total_platforms": len(result_activity)
            }

        except MCPError as e:
            return {
                "success": False,
                "error": e.to_dict()
            }
        except Exception as e:
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    def analyze_topic_lifecycle(
        self,
        topic: str,
        date_range: Optional[Union[Dict[str, str], str]] = None
    ) -> Dict:
        """
        话题生命周期分析 - 追踪话题从出现到消失的完整周期

        Args:
            topic: 话题关键词
            date_range: 日期范围（可选）
                       - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                       - **默认**: 不指定时默认分析最近7天

        Returns:
            话题生命周期分析结果

        Examples:
            用户询问示例：
            - "分析'人工智能'这个话题的生命周期"
            - "看看'iPhone'话题是昙花一现还是持续热点"
            - "追踪'比特币'话题的热度变化"

            代码调用示例：
            >>> # 分析话题生命周期（假设今天是 2025-11-17）
            >>> result = tools.analyze_topic_lifecycle(
            ...     topic="人工智能",
            ...     date_range={"start": "2025-10-19", "end": "2025-11-17"}
            ... )
            >>> print(result['lifecycle_stage'])
        """
        try:
            # 参数验证
            topic = validate_keyword(topic)

            # 处理日期范围（不指定时默认最近7天）
            if date_range:
                from ..utils.validators import validate_date_range
                date_range_tuple = validate_date_range(date_range)
                start_date, end_date = date_range_tuple
            else:
                # 默认最近7天
                end_date = datetime.now()
                start_date = end_date - timedelta(days=6)

            # 收集话题历史数据
            lifecycle_data = []
            current_date = start_date
            while current_date <= end_date:
                try:
                    all_titles, _, _ = self.analytics_service.read_news(
                        date=current_date
                    )

                    # 统计该日的话题出现次数
                    count = 0
                    for _, titles in all_titles.items():
                        for title in titles.keys():
                            if topic.lower() in title.lower():
                                count += 1

                    lifecycle_data.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "count": count
                    })

                except DataNotFoundError:
                    lifecycle_data.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "count": 0
                    })

                current_date += timedelta(days=1)

            # 计算分析天数
            total_days = (end_date - start_date).days + 1

            # 分析生命周期阶段
            counts = [item["count"] for item in lifecycle_data]

            if not any(counts):
                time_desc = f"{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
                raise DataNotFoundError(
                    f"在 {time_desc} 内未找到话题 '{topic}'",
                    suggestion="请尝试其他话题或扩大时间范围"
                )

            # 找到首次出现和最后出现
            first_appearance = next((item["date"] for item in lifecycle_data if item["count"] > 0), None)
            last_appearance = next((item["date"] for item in reversed(lifecycle_data) if item["count"] > 0), None)

            # 计算峰值
            max_count = max(counts)
            peak_index = counts.index(max_count)
            peak_date = lifecycle_data[peak_index]["date"]

            # 计算平均值和标准差（简单实现）
            non_zero_counts = [c for c in counts if c > 0]
            avg_count = sum(non_zero_counts) / len(non_zero_counts) if non_zero_counts else 0

            # 判断生命周期阶段
            recent_counts = counts[-3:]  # 最近3天
            early_counts = counts[:3]    # 前3天

            if sum(recent_counts) > sum(early_counts):
                lifecycle_stage = "上升期"
            elif sum(recent_counts) < sum(early_counts) * 0.5:
                lifecycle_stage = "衰退期"
            elif max_count in recent_counts:
                lifecycle_stage = "爆发期"
            else:
                lifecycle_stage = "稳定期"

            # 分类：昙花一现 vs 持续热点
            active_days = sum(1 for c in counts if c > 0)

            if active_days <= 2 and max_count > avg_count * 2:
                topic_type = "昙花一现"
            elif active_days >= total_days * 0.6:
                topic_type = "持续热点"
            else:
                topic_type = "周期性热点"

            return {
                "success": True,
                "topic": topic,
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d"),
                    "total_days": total_days
                },
                "lifecycle_data": lifecycle_data,
                "analysis": {
                    "first_appearance": first_appearance,
                    "last_appearance": last_appearance,
                    "peak_date": peak_date,
                    "peak_count": max_count,
                    "active_days": active_days,
                    "avg_daily_mentions": round(avg_count, 2),
                    "lifecycle_stage": lifecycle_stage,
                    "topic_type": topic_type
                }
            }

        except MCPError as e:
            return {
                "success": False,
                "error": e.to_dict()
            }
        except Exception as e:
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    def detect_viral_topics(
        self,
        threshold: float = 3.0,
        time_window: int = 24
    ) -> Dict:
        """
        异常热度检测 - 自动识别突然爆火的话题

        Args:
            threshold: 热度突增倍数阈值
            time_window: 检测时间窗口（小时）

        Returns:
            爆火话题列表

        Examples:
            用户询问示例：
            - "检测今天有哪些突然爆火的话题"
            - "看看有没有热度异常的新闻"
            - "预警可能的重大事件"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> result = tools.detect_viral_topics(
            ...     threshold=3.0,
            ...     time_window=24
            ... )
            >>> print(result['viral_topics'])
        """
        try:
            # 参数验证
            threshold = validate_threshold(threshold, default=3.0, min_value=1.0, max_value=100.0)
            time_window = validate_limit(time_window, default=24, max_limit=72)

            # 读取当前和之前的数据
            current_all_titles, _, _ = self.analytics_service.read_news()

            # 读取昨天的数据作为基准
            yesterday = datetime.now() - timedelta(days=1)
            try:
                previous_all_titles, _, _ = self.analytics_service.read_news(
                    date=yesterday
                )
            except DataNotFoundError:
                previous_all_titles = {}

            # 统计当前的关键词频率
            current_keywords = Counter()
            current_keyword_titles = defaultdict(list)

            for _, titles in current_all_titles.items():
                for title in titles.keys():
                    keywords = self._extract_keywords(title)
                    current_keywords.update(keywords)

                    for kw in keywords:
                        current_keyword_titles[kw].append(title)

            # 统计之前的关键词频率
            previous_keywords = Counter()

            for _, titles in previous_all_titles.items():
                for title in titles.keys():
                    keywords = self._extract_keywords(title)
                    previous_keywords.update(keywords)

            # 检测异常热度
            viral_topics = []

            for keyword, current_count in current_keywords.items():
                previous_count = previous_keywords.get(keyword, 0)

                # 计算增长倍数
                if previous_count == 0:
                    # 新出现的话题
                    if current_count >= 5:  # 至少出现5次才认为是爆火
                        growth_rate = float('inf')
                        is_viral = True
                    else:
                        continue
                else:
                    growth_rate = current_count / previous_count
                    is_viral = growth_rate >= threshold

                if is_viral:
                    viral_topics.append({
                        "keyword": keyword,
                        "current_count": current_count,
                        "previous_count": previous_count,
                        "growth_rate": round(growth_rate, 2) if growth_rate != float('inf') else "新话题",
                        "sample_titles": current_keyword_titles[keyword][:3],
                        "alert_level": "高" if growth_rate > threshold * 2 else "中"
                    })

            # 按增长率排序
            viral_topics.sort(
                key=lambda x: x["current_count"] if x["growth_rate"] == "新话题" else x["growth_rate"],
                reverse=True
            )

            if not viral_topics:
                return {
                    "success": True,
                    "summary": {
                        "description": "异常热度检测结果",
                        "total": 0,
                        "threshold": threshold,
                        "time_window": time_window
                    },
                    "data": [],
                    "message": f"未检测到热度增长超过 {threshold} 倍的话题"
                }

            return {
                "success": True,
                "summary": {
                    "description": "异常热度检测结果",
                    "total": len(viral_topics),
                    "threshold": threshold,
                    "time_window": time_window,
                    "detection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                "data": viral_topics
            }

        except MCPError as e:
            return {
                "success": False,
                "error": e.to_dict()
            }
        except Exception as e:
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    def predict_trending_topics(
        self,
        lookahead_hours: int = 6,
        confidence_threshold: float = 0.7
    ) -> Dict:
        """
        话题预测 - 基于历史数据预测未来可能的热点

        Args:
            lookahead_hours: 预测未来多少小时
            confidence_threshold: 置信度阈值

        Returns:
            预测的潜力话题列表

        Examples:
            用户询问示例：
            - "预测接下来6小时可能的热点话题"
            - "有哪些话题可能会火起来"
            - "早期发现潜力话题"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> result = tools.predict_trending_topics(
            ...     lookahead_hours=6,
            ...     confidence_threshold=0.7
            ... )
            >>> print(result['predicted_topics'])
        """
        try:
            # 参数验证
            lookahead_hours = validate_limit(lookahead_hours, default=6, max_limit=48)
            confidence_threshold = validate_threshold(
                confidence_threshold,
                default=0.7,
                min_value=0.0,
                max_value=1.0,
                param_name="confidence_threshold"
            )

            # 收集最近3天的数据用于预测
            keyword_trends = defaultdict(list)

            for days_ago in range(3, 0, -1):
                date = datetime.now() - timedelta(days=days_ago)

                try:
                    all_titles, _, _ = self.analytics_service.read_news(
                        date=date
                    )

                    # 统计关键词
                    keywords_count = Counter()
                    for _, titles in all_titles.items():
                        for title in titles.keys():
                            keywords = self._extract_keywords(title)
                            keywords_count.update(keywords)

                    # 记录每个关键词的历史数据
                    for keyword, count in keywords_count.items():
                        keyword_trends[keyword].append(count)

                except DataNotFoundError:
                    pass

            # 添加今天的数据
            try:
                all_titles, _, _ = self.analytics_service.read_news()

                keywords_count = Counter()
                keyword_titles = defaultdict(list)

                for _, titles in all_titles.items():
                    for title in titles.keys():
                        keywords = self._extract_keywords(title)
                        keywords_count.update(keywords)

                        for kw in keywords:
                            keyword_titles[kw].append(title)

                for keyword, count in keywords_count.items():
                    keyword_trends[keyword].append(count)

            except DataNotFoundError:
                raise DataNotFoundError(
                    "未找到今天的数据",
                    suggestion="请等待爬虫任务完成"
                )

            # 预测潜力话题
            predicted_topics = []

            for keyword, trend_data in keyword_trends.items():
                if len(trend_data) < 2:
                    continue

                # 简单的线性趋势预测
                # 计算增长率
                recent_value = trend_data[-1]
                previous_value = trend_data[-2] if len(trend_data) >= 2 else 0

                if previous_value == 0:
                    if recent_value >= 3:
                        growth_rate = 1.0
                    else:
                        continue
                else:
                    growth_rate = (recent_value - previous_value) / previous_value

                # 判断是否是上升趋势
                if growth_rate > 0.3:  # 增长超过30%
                    # 计算置信度（基于趋势的稳定性）
                    if len(trend_data) >= 3:
                        # 检查是否连续增长
                        is_consistent = all(
                            trend_data[i] <= trend_data[i+1]
                            for i in range(len(trend_data)-1)
                        )
                        confidence = 0.9 if is_consistent else 0.7
                    else:
                        confidence = 0.6

                    if confidence >= confidence_threshold:
                        predicted_topics.append({
                            "keyword": keyword,
                            "current_count": recent_value,
                            "growth_rate": round(growth_rate * 100, 2),
                            "confidence": round(confidence, 2),
                            "trend_data": trend_data,
                            "prediction": "上升趋势，可能成为热点",
                            "sample_titles": keyword_titles.get(keyword, [])[:3]
                        })

            # 按置信度和增长率排序
            predicted_topics.sort(
                key=lambda x: (x["confidence"], x["growth_rate"]),
                reverse=True
            )

            return {
                "success": True,
                "summary": {
                    "description": "热点话题预测结果",
                    "total": len(predicted_topics),
                    "returned": min(20, len(predicted_topics)),
                    "lookahead_hours": lookahead_hours,
                    "confidence_threshold": confidence_threshold,
                    "prediction_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                "data": predicted_topics[:20],  # 返回TOP 20
                "note": "预测基于历史趋势，实际结果可能有偏差"
            }

        except MCPError as e:
            return {
                "success": False,
                "error": e.to_dict()
            }
        except Exception as e:
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    # ==================== 辅助方法 ====================

    def _extract_keywords(self, title: str, min_length: int = 2) -> List[str]:
        """
        从标题中提取关键词（简单实现）

        Args:
            title: 标题文本
            min_length: 最小关键词长度

        Returns:
            关键词列表
        """
        # 移除URL和特殊字符
        title = re.sub(r'http[s]?://\S+', '', title)
        title = re.sub(r'[^\w\s]', ' ', title)

        # 简单分词（按空格和常见分隔符）
        words = re.split(r'[\s，。！？、]+', title)

        # 过滤停用词和短词
        stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}

        keywords = [
            word.strip() for word in words
            if word.strip() and len(word.strip()) >= min_length and word.strip() not in stopwords
        ]

        return keywords

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的相似度

        Args:
            text1: 文本1
            text2: 文本2

        Returns:
            相似度分数（0-1之间）
        """
        # 使用 SequenceMatcher 计算相似度
        return SequenceMatcher(None, text1, text2).ratio()

    def _find_unique_topics(self, platform_stats: Dict) -> Dict[str, List[str]]:
        """
        找出各平台独有的热点话题

        Args:
            platform_stats: 平台统计数据

        Returns:
            各平台独有话题字典
        """
        unique_topics = {}

        # 获取每个平台的TOP关键词
        platform_keywords = {}
        for platform, stats in platform_stats.items():
            top_keywords = set([kw for kw, _ in stats["top_keywords"].most_common(10)])
            platform_keywords[platform] = top_keywords

        # 找出独有关键词
        for platform, keywords in platform_keywords.items():
            # 找出其他平台的所有关键词
            other_keywords = set()
            for other_platform, other_kws in platform_keywords.items():
                if other_platform != platform:
                    other_keywords.update(other_kws)

            # 找出独有的
            unique = keywords - other_keywords
            if unique:
                unique_topics[platform] = list(unique)[:5]  # 最多5个

        return unique_topics

    # ==================== 跨平台聚合工具 ====================
