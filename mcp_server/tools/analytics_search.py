"""MCP similarity, entity, and summary analytics."""

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
    re,
    timedelta,
    validate_date_range,
    validate_keyword,
    validate_limit,
    validate_threshold,
)


class AnalyticsSearchMixin:
    def find_similar_news(
        self,
        reference_title: str,
        threshold: float = 0.6,
        limit: int = 50,
        include_url: bool = False
    ) -> Dict:
        """
        相似新闻查找 - 基于标题相似度查找相关新闻

        Args:
            reference_title: 参考标题
            threshold: 相似度阈值（0-1之间）
            limit: 返回条数限制，默认50
            include_url: 是否包含URL链接，默认False（节省token）

        Returns:
            相似新闻列表

        Examples:
            用户询问示例：
            - "找出和'特斯拉降价'相似的新闻"
            - "查找关于iPhone发布的类似报道"
            - "看看有没有和这条新闻相似的报道"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> result = tools.find_similar_news(
            ...     reference_title="特斯拉宣布降价",
            ...     threshold=0.6,
            ...     limit=10
            ... )
            >>> print(result['similar_news'])
        """
        try:
            # 参数验证
            reference_title = validate_keyword(reference_title)
            threshold = validate_threshold(threshold, default=0.6, min_value=0.0, max_value=1.0)
            limit = validate_limit(limit, default=50)

            # 读取数据
            all_titles, id_to_name, _ = self.analytics_service.read_news()

            # 计算相似度
            similar_items = []

            for platform_id, titles in all_titles.items():
                platform_name = id_to_name.get(platform_id, platform_id)

                for title, info in titles.items():
                    if title == reference_title:
                        continue

                    # 计算相似度
                    similarity = self._calculate_similarity(reference_title, title)

                    if similarity >= threshold:
                        news_item = {
                            "title": title,
                            "platform": platform_id,
                            "platform_name": platform_name,
                            "similarity": round(similarity, 3),
                            "rank": info["ranks"][0] if info["ranks"] else 0
                        }

                        # 条件性添加 URL 字段
                        if include_url:
                            news_item["url"] = info.get("url", "")

                        similar_items.append(news_item)

            # 按相似度排序
            similar_items.sort(key=lambda x: x["similarity"], reverse=True)

            # 限制数量
            result_items = similar_items[:limit]

            if not result_items:
                raise DataNotFoundError(
                    f"未找到相似度超过 {threshold} 的新闻",
                    suggestion="请降低相似度阈值或尝试其他标题"
                )

            result = {
                "success": True,
                "summary": {
                    "description": "相似新闻搜索结果",
                    "total_found": len(similar_items),
                    "returned": len(result_items),
                    "requested_limit": limit,
                    "threshold": threshold,
                    "reference_title": reference_title
                },
                "data": result_items
            }

            if len(similar_items) < limit:
                result["note"] = f"相似度阈值 {threshold} 下仅找到 {len(similar_items)} 条相似新闻"

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

    def search_by_entity(
        self,
        entity: str,
        entity_type: Optional[str] = None,
        limit: int = 50,
        sort_by_weight: bool = True
    ) -> Dict:
        """
        实体识别搜索 - 搜索包含特定人物/地点/机构的新闻

        Args:
            entity: 实体名称
            entity_type: 实体类型（person/location/organization），可选
            limit: 返回条数限制，默认50，最大200
            sort_by_weight: 是否按权重排序，默认True

        Returns:
            实体相关新闻列表

        Examples:
            用户询问示例：
            - "搜索马斯克相关的新闻"
            - "查找关于特斯拉公司的报道，返回前20条"
            - "看看北京有什么新闻"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> result = tools.search_by_entity(
            ...     entity="马斯克",
            ...     entity_type="person",
            ...     limit=20
            ... )
            >>> print(result['related_news'])
        """
        try:
            # 参数验证
            entity = validate_keyword(entity)
            limit = validate_limit(limit, default=50)

            if entity_type and entity_type not in ["person", "location", "organization"]:
                raise InvalidParameterError(
                    f"无效的实体类型: {entity_type}",
                    suggestion="支持的类型: person, location, organization"
                )

            # 读取数据
            all_titles, id_to_name, _ = self.analytics_service.read_news()

            # 搜索包含实体的新闻
            related_news = []
            entity_context = Counter()  # 统计实体周边的词

            for platform_id, titles in all_titles.items():
                platform_name = id_to_name.get(platform_id, platform_id)

                for title, info in titles.items():
                    if entity in title:
                        url = info.get("url", "")
                        mobile_url = info.get("mobileUrl", "")
                        ranks = info.get("ranks", [])
                        count = len(ranks)

                        related_news.append({
                            "title": title,
                            "platform": platform_id,
                            "platform_name": platform_name,
                            "url": url,
                            "mobileUrl": mobile_url,
                            "ranks": ranks,
                            "count": count,
                            "rank": ranks[0] if ranks else 999
                        })

                        # 提取实体周边的关键词
                        keywords = self._extract_keywords(title)
                        entity_context.update(keywords)

            if not related_news:
                raise DataNotFoundError(
                    f"未找到包含实体 '{entity}' 的新闻",
                    suggestion="请尝试其他实体名称"
                )

            # 移除实体本身
            if entity in entity_context:
                del entity_context[entity]

            # 按权重排序（如果启用）
            if sort_by_weight:
                related_news.sort(
                    key=lambda x: calculate_news_weight(x),
                    reverse=True
                )
            else:
                # 按排名排序
                related_news.sort(key=lambda x: x["rank"])

            # 限制返回数量
            result_news = related_news[:limit]

            return {
                "success": True,
                "summary": {
                    "description": f"实体「{entity}」相关新闻",
                    "entity": entity,
                    "entity_type": entity_type or "auto",
                    "total_found": len(related_news),
                    "returned": len(result_news),
                    "sorted_by_weight": sort_by_weight
                },
                "data": result_news,
                "related_keywords": [
                    {"keyword": k, "count": v}
                    for k, v in entity_context.most_common(10)
                ]
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

    def generate_summary_report(
        self,
        report_type: str = "daily",
        date_range: Optional[Union[Dict[str, str], str]] = None
    ) -> Dict:
        """
        每日/每周摘要生成器 - 自动生成热点摘要报告

        Args:
            report_type: 报告类型（daily/weekly）
            date_range: 自定义日期范围（可选）

        Returns:
            Markdown格式的摘要报告

        Examples:
            用户询问示例：
            - "生成今天的新闻摘要报告"
            - "给我一份本周的热点总结"
            - "生成过去7天的新闻分析报告"

            代码调用示例：
            >>> tools = AnalyticsTools()
            >>> result = tools.generate_summary_report(
            ...     report_type="daily"
            ... )
            >>> print(result['markdown_report'])
        """
        try:
            # 参数验证
            if report_type not in ["daily", "weekly"]:
                raise InvalidParameterError(
                    f"无效的报告类型: {report_type}",
                    suggestion="支持的类型: daily, weekly"
                )

            # 确定日期范围
            if date_range:
                date_range_tuple = validate_date_range(date_range)
                start_date, end_date = date_range_tuple
            else:
                if report_type == "daily":
                    start_date = end_date = datetime.now()
                else:  # weekly
                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=6)

            # 收集数据
            all_keywords = Counter()
            all_platforms_news = defaultdict(int)
            all_titles_list = []

            current_date = start_date
            while current_date <= end_date:
                try:
                    all_titles, id_to_name, _ = self.analytics_service.read_news(
                        date=current_date
                    )

                    for platform_id, titles in all_titles.items():
                        platform_name = id_to_name.get(platform_id, platform_id)
                        all_platforms_news[platform_name] += len(titles)

                        for title in titles.keys():
                            all_titles_list.append({
                                "title": title,
                                "platform": platform_name,
                                "date": current_date.strftime("%Y-%m-%d")
                            })

                            # 提取关键词
                            keywords = self._extract_keywords(title)
                            all_keywords.update(keywords)

                except DataNotFoundError:
                    pass

                current_date += timedelta(days=1)

            # 生成报告
            report_title = f"{'每日' if report_type == 'daily' else '每周'}新闻热点摘要"
            date_str = f"{start_date.strftime('%Y-%m-%d')}" if report_type == "daily" else f"{start_date.strftime('%Y-%m-%d')} 至 {end_date.strftime('%Y-%m-%d')}"

            # 构建Markdown报告
            markdown = f"""# {report_title}

**报告日期**: {date_str}
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 数据概览

- **总新闻数**: {len(all_titles_list)}
- **覆盖平台**: {len(all_platforms_news)}
- **热门关键词数**: {len(all_keywords)}

## TOP 10 热门话题

"""

            # 添加TOP 10关键词
            for i, (keyword, count) in enumerate(all_keywords.most_common(10), 1):
                markdown += f"{i}. **{keyword}** - 出现 {count} 次\n"

            # 平台分析
            markdown += "\n## 平台活跃度\n\n"
            sorted_platforms = sorted(all_platforms_news.items(), key=lambda x: x[1], reverse=True)

            for platform, count in sorted_platforms:
                markdown += f"- **{platform}**: {count} 条新闻\n"

            # 趋势变化（如果是周报）
            if report_type == "weekly":
                markdown += "\n## 趋势分析\n\n"
                markdown += "本周热度持续的话题（样本数据）：\n\n"

                # 简单的趋势分析
                top_keywords = [kw for kw, _ in all_keywords.most_common(5)]
                for keyword in top_keywords:
                    markdown += f"- **{keyword}**: 持续热门\n"

            # 添加样本新闻（按权重选择，确保确定性）
            markdown += "\n##  精选新闻样本\n\n"

            # 确定性选取：按标题的权重排序，取前5条
            # 这样相同输入总是返回相同结果
            if all_titles_list:
                # 计算每条新闻的权重分数（基于关键词出现次数）
                news_with_scores = []
                for news in all_titles_list:
                    # 简单权重：统计包含TOP关键词的次数
                    score = 0
                    title_lower = news['title'].lower()
                    for keyword, count in all_keywords.most_common(10):
                        if keyword.lower() in title_lower:
                            score += count
                    news_with_scores.append((news, score))

                # 按权重降序排序，权重相同则按标题字母顺序（确保确定性）
                news_with_scores.sort(key=lambda x: (-x[1], x[0]['title']))

                # 取前5条
                sample_news = [item[0] for item in news_with_scores[:5]]

                for news in sample_news:
                    markdown += f"- [{news['platform']}] {news['title']}\n"

            markdown += "\n---\n\n*本报告由 Ptilopsis Radar MCP 自动生成*\n"

            return {
                "success": True,
                "report_type": report_type,
                "date_range": {
                    "start": start_date.strftime("%Y-%m-%d"),
                    "end": end_date.strftime("%Y-%m-%d")
                },
                "markdown_report": markdown,
                "statistics": {
                    "total_news": len(all_titles_list),
                    "platforms_count": len(all_platforms_news),
                    "keywords_count": len(all_keywords),
                    "top_keyword": all_keywords.most_common(1)[0] if all_keywords else None
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
