"""MCP insight, topic, platform, co-occurrence, and sentiment analytics."""

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
    defaultdict,
    datetime,
    timedelta,
    validate_date_range,
    validate_keyword,
    validate_limit,
    validate_platforms,
    validate_threshold,
    validate_top_n,
)


class AnalyticsInsightsMixin:
    def analyze_data_insights_unified(
        self,
        insight_type: str = "platform_compare",
        topic: Optional[str] = None,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        min_frequency: int = 3,
        top_n: int = 20
    ) -> Dict:
        """
        统一数据洞察分析工具 - 整合多种数据分析模式

        Args:
            insight_type: 洞察类型，可选值：
                - "platform_compare": 平台对比分析（对比不同平台对话题的关注度）
                - "platform_activity": 平台活跃度统计（统计各平台发布频率和活跃时间）
                - "keyword_cooccur": 关键词共现分析（分析关键词同时出现的模式）
            topic: 话题关键词（可选，platform_compare模式适用）
            date_range: 日期范围，格式: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
            min_frequency: 最小共现频次（keyword_cooccur模式），默认3
            top_n: 返回TOP N结果（keyword_cooccur模式），默认20

        Returns:
            数据洞察分析结果字典

        Examples:
            - analyze_data_insights_unified(insight_type="platform_compare", topic="人工智能")
            - analyze_data_insights_unified(insight_type="platform_activity", date_range={...})
            - analyze_data_insights_unified(insight_type="keyword_cooccur", min_frequency=5)
        """
        try:
            # 参数验证
            if insight_type not in ["platform_compare", "platform_activity", "keyword_cooccur"]:
                raise InvalidParameterError(
                    f"无效的洞察类型: {insight_type}",
                    suggestion="支持的类型: platform_compare, platform_activity, keyword_cooccur"
                )

            # 根据洞察类型调用相应方法
            if insight_type == "platform_compare":
                return self.compare_platforms(
                    topic=topic,
                    date_range=date_range
                )
            elif insight_type == "platform_activity":
                return self.get_platform_activity_stats(
                    date_range=date_range
                )
            else:  # keyword_cooccur
                return self.analyze_keyword_cooccurrence(
                    min_frequency=min_frequency,
                    top_n=top_n
                )

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

    def analyze_topic_trend_unified(
        self,
        topic: str,
        analysis_type: str = "trend",
        date_range: Optional[Union[Dict[str, str], str]] = None,
        granularity: str = "day",
        threshold: float = 3.0,
        time_window: int = 24,
        lookahead_hours: int = 6,
        confidence_threshold: float = 0.7
    ) -> Dict:
        """
        统一话题趋势分析工具 - 整合多种趋势分析模式

        Args:
            topic: 话题关键词（必需）
            analysis_type: 分析类型，可选值：
                - "trend": 热度趋势分析（追踪话题的热度变化）
                - "lifecycle": 生命周期分析（从出现到消失的完整周期）
                - "viral": 异常热度检测（识别突然爆火的话题）
                - "predict": 话题预测（预测未来可能的热点）
            date_range: 日期范围（trend和lifecycle模式），可选
                       - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                       - **默认**: 不指定时默认分析最近7天
            granularity: 时间粒度（trend模式），默认"day"（hour/day）
            threshold: 热度突增倍数阈值（viral模式），默认3.0
            time_window: 检测时间窗口小时数（viral模式），默认24
            lookahead_hours: 预测未来小时数（predict模式），默认6
            confidence_threshold: 置信度阈值（predict模式），默认0.7

        Returns:
            趋势分析结果字典

        Examples (假设今天是 2025-11-17):
            - 用户："分析AI最近7天的趋势" → analyze_topic_trend_unified(topic="人工智能", analysis_type="trend", date_range={"start": "2025-11-11", "end": "2025-11-17"})
            - 用户："看看特斯拉本月的热度" → analyze_topic_trend_unified(topic="特斯拉", analysis_type="lifecycle", date_range={"start": "2025-11-01", "end": "2025-11-17"})
            - analyze_topic_trend_unified(topic="比特币", analysis_type="viral", threshold=3.0)
            - analyze_topic_trend_unified(topic="ChatGPT", analysis_type="predict", lookahead_hours=6)
        """
        try:
            # 参数验证
            topic = validate_keyword(topic)

            if analysis_type not in ["trend", "lifecycle", "viral", "predict"]:
                raise InvalidParameterError(
                    f"无效的分析类型: {analysis_type}",
                    suggestion="支持的类型: trend, lifecycle, viral, predict"
                )

            # 根据分析类型调用相应方法
            if analysis_type == "trend":
                return self.get_topic_trend_analysis(
                    topic=topic,
                    date_range=date_range,
                    granularity=granularity
                )
            elif analysis_type == "lifecycle":
                return self.analyze_topic_lifecycle(
                    topic=topic,
                    date_range=date_range
                )
            elif analysis_type == "viral":
                return self.detect_viral_topics(
                    topic=topic,
                    threshold=threshold,
                    time_window=time_window
                )
            else:  # predict
                return self.predict_trending_topics(
                    topic=topic,
                    lookahead_hours=lookahead_hours,
                    confidence_threshold=confidence_threshold
                )

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

    def get_topic_trend_analysis(
        self,
        topic: str,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        granularity: str = "day"
    ) -> Dict:
        """
        热度趋势分析 - 追踪特定话题的热度变化趋势

        Args:
            topic: 话题关键词
            date_range: 日期范围（可选）
                       - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                       - **默认**: 不指定时默认分析最近7天
            granularity: 时间粒度，仅支持 day（天）

        Returns:
            趋势分析结果字典

        Examples:
            用户询问示例：
            - "帮我分析一下'人工智能'这个话题最近一周的热度趋势"
            - "查看'比特币'过去一周的热度变化"
            - "看看'iPhone'最近7天的趋势如何"
            - "分析'特斯拉'最近一个月的热度趋势"
            - "查看'ChatGPT'2024年12月的趋势变化"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> # 分析7天趋势（假设今天是 2025-11-17）
            >>> result = tools.get_topic_trend_analysis(
            ...     topic="人工智能",
            ...     date_range={"start": "2025-11-11", "end": "2025-11-17"},
            ...     granularity="day"
            ... )
            >>> # 分析历史月份趋势
            >>> result = tools.get_topic_trend_analysis(
            ...     topic="特斯拉",
            ...     date_range={"start": "2024-12-01", "end": "2024-12-31"},
            ...     granularity="day"
            ... )
            >>> print(result['trend_data'])
        """
        try:
            # 验证参数
            topic = validate_keyword(topic)

            # 验证粒度参数（只支持day）
            if granularity != "day":
                from ..utils.errors import InvalidParameterError
                raise InvalidParameterError(
                    f"不支持的粒度参数: {granularity}",
                    suggestion="当前仅支持 'day' 粒度，因为底层数据按天聚合"
                )

            # 处理日期范围（不指定时默认最近7天）
            if date_range:
                from ..utils.validators import validate_date_range
                date_range_tuple = validate_date_range(date_range)
                start_date, end_date = date_range_tuple
            else:
                # 默认最近7天
                end_date = datetime.now()
                start_date = end_date - timedelta(days=6)

            # 收集趋势数据
            trend_data = []
            current_date = start_date

            while current_date <= end_date:
                try:
                    all_titles, _, _ = self.analytics_service.read_news(
                        date=current_date
                    )

                    # 统计该时间点的话题出现次数
                    count = 0
                    matched_titles = []

                    for _, titles in all_titles.items():
                        for title in titles.keys():
                            if topic.lower() in title.lower():
                                count += 1
                                matched_titles.append(title)

                    trend_data.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "count": count,
                        "sample_titles": matched_titles[:3]  # 只保留前3个样本
                    })

                except DataNotFoundError:
                    trend_data.append({
                        "date": current_date.strftime("%Y-%m-%d"),
                        "count": 0,
                        "sample_titles": []
                    })

                # 按天增加时间
                current_date += timedelta(days=1)

            # 计算趋势指标
            counts = [item["count"] for item in trend_data]
            total_days = (end_date - start_date).days + 1

            if len(counts) >= 2:
                # 计算涨跌幅度
                first_non_zero = next((c for c in counts if c > 0), 0)
                last_count = counts[-1]

                if first_non_zero > 0:
                    change_rate = ((last_count - first_non_zero) / first_non_zero) * 100
                else:
                    change_rate = 0

                # 找到峰值时间
                max_count = max(counts)
                peak_index = counts.index(max_count)
                peak_time = trend_data[peak_index]["date"]
            else:
                change_rate = 0
                peak_time = None
                max_count = 0

            return {
                "success": True,
                "summary": {
                    "description": f"话题「{topic}」的热度趋势分析",
                    "topic": topic,
                    "date_range": {
                        "start": start_date.strftime("%Y-%m-%d"),
                        "end": end_date.strftime("%Y-%m-%d"),
                        "total_days": total_days
                    },
                    "granularity": granularity,
                    "total_mentions": sum(counts),
                    "average_mentions": round(sum(counts) / len(counts), 2) if counts else 0,
                    "peak_count": max_count,
                    "peak_time": peak_time,
                    "change_rate": round(change_rate, 2),
                    "trend_direction": "上升" if change_rate > 10 else "下降" if change_rate < -10 else "稳定"
                },
                "data": trend_data
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

    def compare_platforms(
        self,
        topic: Optional[str] = None,
        date_range: Optional[Union[Dict[str, str], str]] = None
    ) -> Dict:
        """
        平台对比分析 - 对比不同平台对同一话题的关注度

        Args:
            topic: 话题关键词（可选，不指定则对比整体活跃度）
            date_range: 日期范围，格式: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}

        Returns:
            平台对比分析结果

        Examples:
            用户询问示例：
            - "对比一下各个平台对'人工智能'话题的关注度"
            - "看看知乎和微博哪个平台更关注科技新闻"
            - "分析各平台今天的热点分布"

            代码调用示例：
            >>> # 对比各平台（假设今天是 2025-11-17）
            >>> result = tools.compare_platforms(
            ...     topic="人工智能",
            ...     date_range={"start": "2025-11-08", "end": "2025-11-17"}
            ... )
            >>> print(result['platform_stats'])
        """
        try:
            # 参数验证
            if topic:
                topic = validate_keyword(topic)
            date_range_tuple = validate_date_range(date_range)

            # 确定日期范围
            if date_range_tuple:
                start_date, end_date = date_range_tuple
            else:
                start_date = end_date = datetime.now()

            # 收集各平台数据
            platform_stats = defaultdict(lambda: {
                "total_news": 0,
                "topic_mentions": 0,
                "unique_titles": set(),
                "top_keywords": Counter()
            })

            # 遍历日期范围
            current_date = start_date
            while current_date <= end_date:
                try:
                    all_titles, id_to_name, _ = self.analytics_service.read_news(
                        date=current_date
                    )

                    for platform_id, titles in all_titles.items():
                        platform_name = id_to_name.get(platform_id, platform_id)

                        for title in titles.keys():
                            platform_stats[platform_name]["total_news"] += 1
                            platform_stats[platform_name]["unique_titles"].add(title)

                            # 如果指定了话题，统计包含话题的新闻
                            if topic and topic.lower() in title.lower():
                                platform_stats[platform_name]["topic_mentions"] += 1

                            # 提取关键词（简单分词）
                            keywords = self._extract_keywords(title)
                            platform_stats[platform_name]["top_keywords"].update(keywords)

                except DataNotFoundError:
                    pass

                current_date += timedelta(days=1)

            # 转换为可序列化的格式
            result_stats = {}
            for platform, stats in platform_stats.items():
                coverage_rate = 0
                if stats["total_news"] > 0:
                    coverage_rate = (stats["topic_mentions"] / stats["total_news"]) * 100

                result_stats[platform] = {
                    "total_news": stats["total_news"],
                    "topic_mentions": stats["topic_mentions"],
                    "unique_titles": len(stats["unique_titles"]),
                    "coverage_rate": round(coverage_rate, 2),
                    "top_keywords": [
                        {"keyword": k, "count": v}
                        for k, v in stats["top_keywords"].most_common(5)
                    ]
                }

            # 找出各平台独有的热点
            unique_topics = self._find_unique_topics(platform_stats)

            return {
                "success": True,
                "topic": topic,
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                },
                "platform_stats": result_stats,
                "unique_topics": unique_topics,
                "total_platforms": len(result_stats)
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

    def analyze_keyword_cooccurrence(
        self,
        min_frequency: int = 3,
        top_n: int = 20
    ) -> Dict:
        """
        关键词共现分析 - 分析哪些关键词经常同时出现

        Args:
            min_frequency: 最小共现频次
            top_n: 返回TOP N关键词对

        Returns:
            关键词共现分析结果

        Examples:
            用户询问示例：
            - "分析一下哪些关键词经常一起出现"
            - "看看'人工智能'经常和哪些词一起出现"
            - "找出今天新闻中的关键词关联"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> result = tools.analyze_keyword_cooccurrence(
            ...     min_frequency=5,
            ...     top_n=15
            ... )
            >>> print(result['cooccurrence_pairs'])
        """
        try:
            # 参数验证
            min_frequency = validate_limit(min_frequency, default=3, max_limit=100)
            top_n = validate_top_n(top_n, default=20)

            # 读取今天的数据
            all_titles, _, _ = self.analytics_service.read_news()

            # 关键词共现统计
            cooccurrence = Counter()
            keyword_titles = defaultdict(list)

            for platform_id, titles in all_titles.items():
                for title in titles.keys():
                    # 提取关键词
                    keywords = self._extract_keywords(title)

                    # 记录每个关键词出现的标题
                    for kw in keywords:
                        keyword_titles[kw].append(title)

                    # 计算两两共现
                    if len(keywords) >= 2:
                        for i, kw1 in enumerate(keywords):
                            for kw2 in keywords[i+1:]:
                                # 统一排序，避免重复
                                pair = tuple(sorted([kw1, kw2]))
                                cooccurrence[pair] += 1

            # 过滤低频共现
            filtered_pairs = [
                (pair, count) for pair, count in cooccurrence.items()
                if count >= min_frequency
            ]

            # 排序并取TOP N
            top_pairs = sorted(filtered_pairs, key=lambda x: x[1], reverse=True)[:top_n]

            # 构建结果
            result_pairs = []
            for (kw1, kw2), count in top_pairs:
                # 找出同时包含两个关键词的标题样本
                titles_with_both = [
                    title for title in keyword_titles[kw1]
                    if kw2 in self._extract_keywords(title)
                ]

                result_pairs.append({
                    "keyword1": kw1,
                    "keyword2": kw2,
                    "cooccurrence_count": count,
                    "sample_titles": titles_with_both[:3]
                })

            return {
                "success": True,
                "summary": {
                    "description": "关键词共现分析结果",
                    "total": len(result_pairs),
                    "min_frequency": min_frequency,
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                "data": result_pairs
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

    def analyze_sentiment(
        self,
        topic: Optional[str] = None,
        platforms: Optional[List[str]] = None,
        date_range: Optional[Union[Dict[str, str], str]] = None,
        limit: int = 50,
        sort_by_weight: bool = True,
        include_url: bool = False
    ) -> Dict:
        """
        情感倾向分析 - 生成用于 AI 情感分析的结构化提示词

        本工具收集新闻数据并生成优化的 AI 提示词，你可以将其发送给 AI 进行深度情感分析。

        Args:
            topic: 话题关键词（可选），只分析包含该关键词的新闻
            platforms: 平台过滤列表（可选），如 ['zhihu', 'weibo']
            date_range: 日期范围（可选），格式: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                       不指定则默认查询今天的数据
            limit: 返回新闻数量限制，默认50，最大100
            sort_by_weight: 是否按权重排序，默认True（推荐）
            include_url: 是否包含URL链接，默认False（节省token）

        Returns:
            包含 AI 提示词和新闻数据的结构化结果

        Examples:
            用户询问示例：
            - "分析一下今天新闻的情感倾向"
            - "看看'特斯拉'相关新闻是正面还是负面的"
            - "分析各平台对'人工智能'的情感态度"
            - "看看'特斯拉'相关新闻是正面还是负面的，请选择一周内的前10条新闻来分析"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> # 分析今天的特斯拉新闻，返回前10条
            >>> result = tools.analyze_sentiment(
            ...     topic="特斯拉",
            ...     limit=10
            ... )
            >>> # 分析一周内的特斯拉新闻（假设今天是 2025-11-17）
            >>> result = tools.analyze_sentiment(
            ...     topic="特斯拉",
            ...     date_range={"start": "2025-11-11", "end": "2025-11-17"},
            ...     limit=10
            ... )
            >>> print(result['ai_prompt'])  # 获取生成的提示词
        """
        try:
            # 参数验证
            if topic:
                topic = validate_keyword(topic)
            platforms = validate_platforms(platforms)
            limit = validate_limit(limit, default=50)

            # 处理日期范围
            if date_range:
                date_range_tuple = validate_date_range(date_range)
                start_date, end_date = date_range_tuple
            else:
                # 默认今天
                start_date = end_date = datetime.now()

            # 收集新闻数据（支持多天）
            all_news_items = []
            current_date = start_date

            while current_date <= end_date:
                try:
                    all_titles, id_to_name, _ = self.analytics_service.read_news(
                        date=current_date,
                        platforms=platforms
                    )

                    # 收集该日期的新闻
                    for platform_id, titles in all_titles.items():
                        platform_name = id_to_name.get(platform_id, platform_id)
                        for title, info in titles.items():
                            # 如果指定了话题，只收集包含话题的标题
                            if topic and topic.lower() not in title.lower():
                                continue

                            news_item = {
                                "platform": platform_name,
                                "title": title,
                                "ranks": info.get("ranks", []),
                                "count": len(info.get("ranks", [])),
                                "date": current_date.strftime("%Y-%m-%d")
                            }

                            # 条件性添加 URL 字段
                            if include_url:
                                news_item["url"] = info.get("url", "")
                                news_item["mobileUrl"] = info.get("mobileUrl", "")

                            all_news_items.append(news_item)

                except DataNotFoundError:
                    # 该日期没有数据，继续下一天
                    pass

                # 下一天
                current_date += timedelta(days=1)

            if not all_news_items:
                time_desc = "今天" if start_date == end_date else f"{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"
                raise DataNotFoundError(
                    f"未找到相关新闻（{time_desc}）",
                    suggestion="请尝试其他话题、日期范围或平台"
                )

            # 去重（同一标题只保留一次）
            unique_news = {}
            for item in all_news_items:
                key = f"{item['platform']}::{item['title']}"
                if key not in unique_news:
                    unique_news[key] = item
                else:
                    # 合并 ranks（如果同一新闻在多天出现）
                    existing = unique_news[key]
                    existing["ranks"].extend(item["ranks"])
                    existing["count"] = len(existing["ranks"])

            deduplicated_news = list(unique_news.values())

            # 按权重排序（如果启用）
            if sort_by_weight:
                deduplicated_news.sort(
                    key=lambda x: calculate_news_weight(x),
                    reverse=True
                )

            # 限制返回数量
            selected_news = deduplicated_news[:limit]

            # 生成 AI 提示词
            ai_prompt = self._create_sentiment_analysis_prompt(
                news_data=selected_news,
                topic=topic
            )

            # 构建时间范围描述
            if start_date == end_date:
                time_range_desc = start_date.strftime("%Y-%m-%d")
            else:
                time_range_desc = f"{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"

            result = {
                "success": True,
                "method": "ai_prompt_generation",
                "summary": {
                    "description": "情感分析数据和AI提示词",
                    "total_found": len(deduplicated_news),
                    "returned": len(selected_news),
                    "requested_limit": limit,
                    "duplicates_removed": len(all_news_items) - len(deduplicated_news),
                    "topic": topic,
                    "time_range": time_range_desc,
                    "platforms": list(set(item["platform"] for item in selected_news)),
                    "sorted_by_weight": sort_by_weight
                },
                "ai_prompt": ai_prompt,
                "data": selected_news,
                "usage_note": "请将 ai_prompt 字段的内容发送给 AI 进行情感分析"
            }

            # 如果返回数量少于请求数量，增加提示
            if len(selected_news) < limit and len(deduplicated_news) >= limit:
                result["note"] = "返回数量少于请求数量是因为去重逻辑（同一标题在不同平台只保留一次）"
            elif len(deduplicated_news) < limit:
                result["note"] = f"在指定时间范围内仅找到 {len(deduplicated_news)} 条匹配的新闻"

            return result

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

    def _create_sentiment_analysis_prompt(
        self,
        news_data: List[Dict],
        topic: Optional[str]
    ) -> str:
        """
        创建情感分析的 AI 提示词

        Args:
            news_data: 新闻数据列表（已排序和限制数量）
            topic: 话题关键词

        Returns:
            格式化的 AI 提示词
        """
        # 按平台分组
        platform_news = defaultdict(list)
        for item in news_data:
            platform_news[item["platform"]].append({
                "title": item["title"],
                "date": item.get("date", "")
            })

        # 构建提示词
        prompt_parts = []

        # 1. 任务说明
        if topic:
            prompt_parts.append(f"请分析以下关于「{topic}」的新闻标题的情感倾向。")
        else:
            prompt_parts.append("请分析以下新闻标题的情感倾向。")

        prompt_parts.append("")
        prompt_parts.append("分析要求：")
        prompt_parts.append("1. 识别每条新闻的情感倾向（正面/负面/中性）")
        prompt_parts.append("2. 统计各情感类别的数量和百分比")
        prompt_parts.append("3. 分析不同平台的情感差异")
        prompt_parts.append("4. 总结整体情感趋势")
        prompt_parts.append("5. 列举典型的正面和负面新闻样本")
        prompt_parts.append("")

        # 2. 数据概览
        prompt_parts.append(f"数据概览：")
        prompt_parts.append(f"- 总新闻数：{len(news_data)}")
        prompt_parts.append(f"- 覆盖平台：{len(platform_news)}")

        # 时间范围
        dates = set(item.get("date", "") for item in news_data if item.get("date"))
        if dates:
            date_list = sorted(dates)
            if len(date_list) == 1:
                prompt_parts.append(f"- 时间范围：{date_list[0]}")
            else:
                prompt_parts.append(f"- 时间范围：{date_list[0]} 至 {date_list[-1]}")

        prompt_parts.append("")

        # 3. 按平台展示新闻
        prompt_parts.append("新闻列表（按平台分类，已按重要性排序）：")
        prompt_parts.append("")

        for platform, items in sorted(platform_news.items()):
            prompt_parts.append(f"【{platform}】({len(items)} 条)")
            for i, item in enumerate(items, 1):
                title = item["title"]
                date_str = f" [{item['date']}]" if item.get("date") else ""
                prompt_parts.append(f"{i}. {title}{date_str}")
            prompt_parts.append("")

        # 4. 输出格式说明
        prompt_parts.append("请按以下格式输出分析结果：")
        prompt_parts.append("")
        prompt_parts.append("## 情感分布统计")
        prompt_parts.append("- 正面：XX条 (XX%)")
        prompt_parts.append("- 负面：XX条 (XX%)")
        prompt_parts.append("- 中性：XX条 (XX%)")
        prompt_parts.append("")
        prompt_parts.append("## 平台情感对比")
        prompt_parts.append("[各平台的情感倾向差异]")
        prompt_parts.append("")
        prompt_parts.append("## 整体情感趋势")
        prompt_parts.append("[总体分析和关键发现]")
        prompt_parts.append("")
        prompt_parts.append("## 典型样本")
        prompt_parts.append("正面新闻样本：")
        prompt_parts.append("[列举3-5条]")
        prompt_parts.append("")
        prompt_parts.append("负面新闻样本：")
        prompt_parts.append("[列举3-5条]")

        return "\n".join(prompt_parts)
