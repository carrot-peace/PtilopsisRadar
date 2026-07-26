"""
Ptilopsis Radar MCP Server - FastMCP 2.0 实现

使用 FastMCP 2.0 提供生产级 MCP 工具服务器。
支持 stdio 和 HTTP 两种传输模式。
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Union

from fastmcp import FastMCP

from .context import MCPContext, get_request_tools
from .features.query import register_query_features


logger = logging.getLogger(__name__)

# Tool and resource handlers are registered once, then mounted into each
# application instance created by create_server().
_surface = FastMCP("trendradar-news-surface")
register_query_features(_surface)


def _get_tools():
    return get_request_tools()


def create_server(
    *,
    project_root: Optional[str] = None,
    context: Optional[MCPContext] = None,
) -> FastMCP:
    """Create an isolated MCP application and its dependency lifecycle."""
    if project_root is not None and context is not None:
        raise ValueError("project_root and context are mutually exclusive")

    application_context = context or MCPContext.create(project_root)

    @asynccontextmanager
    async def lifespan(_server):
        yield application_context

    server = FastMCP(
        "trendradar-news",
        lifespan=lifespan,
        mask_error_details=True,
    )
    server.mount(_surface, as_proxy=False)
    return server


# ==================== 高级数据分析工具 ====================

@_surface.tool
async def analyze_topic_trend(
    topic: str,
    analysis_type: str = "trend",
    date_range: Optional[Union[Dict[str, str], str]] = None,
    granularity: str = "day",
    spike_threshold: float = 3.0,
    time_window: int = 24,
    lookahead_hours: int = 6,
    confidence_threshold: float = 0.7
) -> str:
    """
    统一话题趋势分析工具 - 整合多种趋势分析模式

    建议：使用自然语言日期时，先调用 resolve_date_range 获取精确日期范围。

    Args:
        topic: 话题关键词（必需）
        analysis_type: 分析类型
            - "trend": 热度趋势分析（默认）
            - "lifecycle": 生命周期分析
            - "viral": 异常热度检测
            - "predict": 话题预测
        date_range: 日期范围，格式 {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}，默认最近7天
        granularity: 时间粒度，默认"day"
        spike_threshold: 热度突增倍数阈值（viral模式），默认3.0
        time_window: 检测时间窗口小时数（viral模式），默认24
        lookahead_hours: 预测未来小时数（predict模式），默认6
        confidence_threshold: 置信度阈值（predict模式），默认0.7

    Returns:
        JSON格式的趋势分析结果

    Examples:
        - analyze_topic_trend(topic="AI", date_range={"start": "2025-01-01", "end": "2025-01-07"})
        - analyze_topic_trend(topic="特斯拉", analysis_type="lifecycle")
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['analytics'].analyze_topic_trend_unified,
        topic=topic,
        analysis_type=analysis_type,
        date_range=date_range,
        granularity=granularity,
        threshold=spike_threshold,
        time_window=time_window,
        lookahead_hours=lookahead_hours,
        confidence_threshold=confidence_threshold
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def analyze_data_insights(
    insight_type: str = "platform_compare",
    topic: Optional[str] = None,
    date_range: Optional[Union[Dict[str, str], str]] = None,
    min_frequency: int = 3,
    top_n: int = 20
) -> str:
    """
    统一数据洞察分析工具 - 整合多种数据分析模式

    Args:
        insight_type: 洞察类型，可选值：
            - "platform_compare": 平台对比分析（对比不同平台对话题的关注度）
            - "platform_activity": 平台活跃度统计（统计各平台发布频率和活跃时间）
            - "keyword_cooccur": 关键词共现分析（分析关键词同时出现的模式）
        topic: 话题关键词（可选，platform_compare模式适用）
        date_range: **【对象类型】** 日期范围（可选）
                    - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                    - **示例**: {"start": "2025-01-01", "end": "2025-01-07"}
                    - **重要**: 必须是对象格式，不能传递整数
        min_frequency: 最小共现频次（keyword_cooccur模式），默认3
        top_n: 返回TOP N结果（keyword_cooccur模式），默认20

    Returns:
        JSON格式的数据洞察分析结果

    Examples:
        - analyze_data_insights(insight_type="platform_compare", topic="人工智能")
        - analyze_data_insights(insight_type="platform_activity", date_range={"start": "2025-01-01", "end": "2025-01-07"})
        - analyze_data_insights(insight_type="keyword_cooccur", min_frequency=5, top_n=15)
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['analytics'].analyze_data_insights_unified,
        insight_type=insight_type,
        topic=topic,
        date_range=date_range,
        min_frequency=min_frequency,
        top_n=top_n
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def analyze_sentiment(
    topic: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    date_range: Optional[Union[Dict[str, str], str]] = None,
    limit: int = 50,
    sort_by_weight: bool = True,
    include_url: bool = False
) -> str:
    """
    分析新闻的情感倾向和热度趋势

    建议：使用自然语言日期时，先调用 resolve_date_range 获取精确日期范围。

    Args:
        topic: 话题关键词（可选）
        platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
        date_range: 日期范围，格式 {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}，默认今天
        limit: 返回新闻数量，默认50，最大100（会对标题去重）
        sort_by_weight: 是否按热度权重排序，默认True
        include_url: 是否包含URL链接，默认False（节省token）

    Returns:
        JSON格式的分析结果，包含情感分布、热度趋势和相关新闻

    Examples:
        - analyze_sentiment(topic="AI", date_range={"start": "2025-01-01", "end": "2025-01-07"})
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['analytics'].analyze_sentiment,
        topic=topic,
        platforms=platforms,
        date_range=date_range,
        limit=limit,
        sort_by_weight=sort_by_weight,
        include_url=include_url
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def find_related_news(
    reference_title: str,
    date_range: Optional[Union[Dict[str, str], str]] = None,
    threshold: float = 0.5,
    limit: int = 50,
    include_url: bool = False
) -> str:
    """
    查找与指定新闻标题相关的其他新闻（支持当天和历史数据）

    Args:
        reference_title: 参考新闻标题（完整或部分）
        date_range: 日期范围（可选）
            - 不指定: 只查询今天的数据
            - "today", "yesterday", "last_week", "last_month": 预设值
            - {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}: 自定义范围
        threshold: 相似度阈值，0-1之间，默认0.5（越高匹配越严格）
        limit: 返回条数限制，默认50
        include_url: 是否包含URL链接，默认False（节省token）

    Returns:
        JSON格式的相关新闻列表，按相似度排序

    Examples:
        - find_related_news(reference_title="特斯拉降价")
        - find_related_news(reference_title="AI突破", date_range="last_week")
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['search'].find_related_news_unified,
        reference_title=reference_title,
        date_range=date_range,
        threshold=threshold,
        limit=limit,
        include_url=include_url
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def generate_summary_report(
    report_type: str = "daily",
    date_range: Optional[Union[Dict[str, str], str]] = None
) -> str:
    """
    每日/每周摘要生成器 - 自动生成热点摘要报告

    Args:
        report_type: 报告类型（daily/weekly）
        date_range: **【对象类型】** 自定义日期范围（可选）
                    - **格式**: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
                    - **示例**: {"start": "2025-01-01", "end": "2025-01-07"}
                    - **重要**: 必须是对象格式，不能传递整数

    Returns:
        JSON格式的摘要报告，包含Markdown格式内容
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['analytics'].generate_summary_report,
        report_type=report_type,
        date_range=date_range
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def aggregate_news(
    date_range: Optional[Union[Dict[str, str], str]] = None,
    platforms: Optional[List[str]] = None,
    similarity_threshold: float = 0.7,
    limit: int = 50,
    include_url: bool = False
) -> str:
    """
    跨平台新闻聚合 - 对相似新闻进行去重合并

    将不同平台报道的同一事件合并为一条聚合新闻，显示跨平台覆盖情况和综合热度。

    Args:
        date_range: 日期范围，不指定则查询今天
        platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
        similarity_threshold: 相似度阈值，0.3-1.0，默认0.7（越高越严格）
        limit: 返回聚合新闻数量，默认50
        include_url: 是否包含URL链接，默认False

    Returns:
        JSON格式的聚合结果，包含去重统计、聚合新闻列表和平台覆盖统计

    Examples:
        - aggregate_news()
        - aggregate_news(similarity_threshold=0.8)
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['analytics'].aggregate_news,
        date_range=date_range,
        platforms=platforms,
        similarity_threshold=similarity_threshold,
        limit=limit,
        include_url=include_url
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def compare_periods(
    period1: Union[Dict[str, str], str],
    period2: Union[Dict[str, str], str],
    topic: Optional[str] = None,
    compare_type: str = "overview",
    platforms: Optional[List[str]] = None,
    top_n: int = 10
) -> str:
    """
    时期对比分析 - 比较两个时间段的新闻数据

    对比不同时期的热点话题、平台活跃度、新闻数量等维度。

    **使用场景：**
    - 对比本周和上周的热点变化
    - 分析某个话题在两个时期的热度差异
    - 查看各平台活跃度的周期性变化

    Args:
        period1: 第一个时间段（基准期）
            - {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}: 日期范围
            - "today", "yesterday", "this_week", "last_week", "this_month", "last_month": 预设值
        period2: 第二个时间段（对比期，格式同 period1）
        topic: 可选的话题关键词（聚焦特定话题的对比）
        compare_type: 对比类型
            - "overview": 总体概览（默认）- 新闻数量、关键词变化、TOP新闻
            - "topic_shift": 话题变化分析 - 上升话题、下降话题、新出现话题
            - "platform_activity": 平台活跃度对比 - 各平台新闻数量变化
        platforms: 平台过滤列表，如 ['zhihu', 'weibo']
        top_n: 返回 TOP N 结果，默认10

    Returns:
        JSON格式的对比分析结果，包含：
        - periods: 两个时期的日期范围
        - compare_type: 对比类型
        - overview/topic_shift/platform_comparison: 具体对比结果（根据类型）

    Examples:
        - compare_periods(period1="last_week", period2="this_week")  # 周环比
        - compare_periods(period1="last_month", period2="this_month", compare_type="topic_shift")
        - compare_periods(
            period1={"start": "2025-01-01", "end": "2025-01-07"},
            period2={"start": "2025-01-08", "end": "2025-01-14"},
            topic="人工智能"
          )
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['analytics'].compare_periods,
        period1=period1,
        period2=period2,
        topic=topic,
        compare_type=compare_type,
        platforms=platforms,
        top_n=top_n
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 智能检索工具 ====================

@_surface.tool
async def search_news(
    query: str,
    search_mode: str = "keyword",
    date_range: Optional[Union[Dict[str, str], str]] = None,
    platforms: Optional[List[str]] = None,
    limit: int = 50,
    sort_by: str = "relevance",
    threshold: float = 0.6,
    include_url: bool = False,
    include_rss: bool = False,
    rss_limit: int = 20
) -> str:
    """
    统一搜索接口，支持多种搜索模式，可同时搜索热榜和RSS

    建议：使用自然语言日期时，先调用 resolve_date_range 获取精确日期范围。

    Args:
        query: 搜索关键词或内容片段
        search_mode: 搜索模式
            - "keyword": 精确关键词匹配（默认）
            - "fuzzy": 模糊内容匹配
            - "entity": 实体名称搜索（人物/地点/机构）
        date_range: 日期范围，格式 {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}，默认今天
        platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
        limit: 热榜返回条数限制，默认50
        sort_by: 排序方式 - "relevance"（相关度）/ "weight"（权重）/ "date"（日期）
        threshold: 相似度阈值（仅fuzzy模式），0-1，默认0.6
        include_url: 是否包含URL链接，默认False
        include_rss: 是否同时搜索RSS数据，默认False
        rss_limit: RSS返回条数限制，默认20

    Returns:
        JSON格式的搜索结果，包含热榜新闻列表和可选的RSS结果

    Examples:
        - search_news(query="AI")
        - search_news(query="AI", include_rss=True)
        - search_news(query="特斯拉", date_range={"start": "2025-01-01", "end": "2025-01-07"})
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['search'].search_news_unified,
        query=query,
        search_mode=search_mode,
        date_range=date_range,
        platforms=platforms,
        limit=limit,
        sort_by=sort_by,
        threshold=threshold,
        include_url=include_url,
        include_rss=include_rss,
        rss_limit=rss_limit
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 配置与系统管理工具 ====================

@_surface.tool
async def get_current_config(
    section: str = "all"
) -> str:
    """
    获取当前系统配置

    Args:
        section: 配置节，可选值：
            - "all": 所有配置（默认）
            - "crawler": 爬虫配置
            - "keywords": 关键词配置
            - "weights": 权重配置

    Returns:
        JSON格式的配置信息
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['config'].get_current_config, section=section)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def get_system_status() -> str:
    """
    获取系统运行状态和健康检查信息

    返回系统版本、数据统计、缓存状态等信息

    Returns:
        JSON格式的系统状态信息
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['system'].get_system_status)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def check_version(
    proxy_url: Optional[str] = None
) -> str:
    """
    检查版本更新（同时检查 Ptilopsis Radar 和 MCP Server）

    比较本地版本与 GitHub 远程版本，判断是否需要更新。

    Args:
        proxy_url: 可选的代理URL，用于访问 GitHub（如 http://127.0.0.1:7890）

    Returns:
        JSON格式的版本检查结果，包含两个组件的版本对比和是否需要更新

    Examples:
        - check_version()
        - check_version(proxy_url="http://127.0.0.1:7890")
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['system'].check_version, proxy_url=proxy_url)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def trigger_crawl(
    platforms: Optional[List[str]] = None,
    save_to_local: bool = False,
    include_url: bool = False
) -> str:
    """
    手动触发一次爬取任务（可选持久化）

    Args:
        platforms: 平台ID列表，如 ['zhihu', 'weibo']，不指定则使用所有平台
        save_to_local: 是否保存到本地 output 目录，默认 False
        include_url: 是否包含URL链接，默认False（节省token）

    Returns:
        JSON格式的任务状态信息，包含成功/失败平台列表和新闻数据

    Examples:
        - trigger_crawl(platforms=['zhihu'])
        - trigger_crawl(save_to_local=True)
    """
    tools = _get_tools()
    result = await asyncio.to_thread(
        tools['system'].trigger_crawl,
        platforms=platforms, save_to_local=save_to_local, include_url=include_url
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 存储同步工具 ====================

@_surface.tool
async def sync_from_remote(
    days: int = 7
) -> str:
    """
    从远程存储拉取数据到本地

    用于 MCP Server 等场景：爬虫存到远程云存储（如 Cloudflare R2），
    MCP Server 拉取到本地进行分析查询。

    Args:
        days: 拉取最近 N 天的数据，默认 7 天
              - 0: 不拉取
              - 7: 拉取最近一周的数据
              - 30: 拉取最近一个月的数据

    Returns:
        JSON格式的同步结果，包含：
        - success: 是否成功
        - synced_files: 成功同步的文件数量
        - synced_dates: 成功同步的日期列表
        - skipped_dates: 跳过的日期（本地已存在）
        - failed_dates: 失败的日期及错误信息
        - message: 操作结果描述

    Examples:
        - sync_from_remote()  # 拉取最近7天
        - sync_from_remote(days=30)  # 拉取最近30天

    Note:
        需要在 config/config.yaml 中配置远程存储（storage.remote）或设置环境变量：
        - S3_ENDPOINT_URL: 服务端点
        - S3_BUCKET_NAME: 存储桶名称
        - S3_ACCESS_KEY_ID: 访问密钥 ID
        - S3_SECRET_ACCESS_KEY: 访问密钥
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['storage'].sync_from_remote, days=days)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def get_storage_status() -> str:
    """
    获取存储配置和状态

    查看当前存储后端配置、本地和远程存储的状态信息。

    Returns:
        JSON格式的存储状态信息，包含本地/远程存储状态和拉取配置
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['storage'].get_storage_status)
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def list_available_dates(
    source: str = "both"
) -> str:
    """
    列出本地/远程可用的日期范围

    查看本地和远程存储中有哪些日期的数据可用。

    Args:
        source: 数据来源
            - "local": 仅本地
            - "remote": 仅远程
            - "both": 同时列出并对比（默认）

    Returns:
        JSON格式的日期列表，包含各来源的日期信息和对比结果

    Examples:
        - list_available_dates()
        - list_available_dates(source="local")
    """
    tools = _get_tools()
    result = await asyncio.to_thread(tools['storage'].list_available_dates, source=source)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 文章内容读取工具 ====================

@_surface.tool
async def read_article(
    url: str,
    timeout: int = 30
) -> str:
    """
    读取指定 URL 的文章内容，返回 LLM 友好的 Markdown 格式

    通过 Jina AI Reader 将网页转换为干净的 Markdown，自动去除广告、导航栏等噪音内容。
    适合用于：阅读新闻正文、获取文章详情、分析文章内容。

    **典型使用流程：**
    1. 先用 search_news(include_url=True) 搜索新闻获取链接
    2. 再用 read_article(url=链接) 读取正文内容
    3. AI 对 Markdown 正文进行分析、摘要、翻译等

    Args:
        url: 文章链接（必需），以 http:// 或 https:// 开头
        timeout: 请求超时时间（秒），默认 30，最大 60

    Returns:
        JSON格式的文章内容，包含完整 Markdown 正文

    Examples:
        - read_article(url="https://example.com/news/123")

    Note:
        - 使用 Jina AI Reader 免费服务（100 RPM 限制）
        - 每次请求间隔 5 秒（内置速率控制）
        - 部分付费墙/登录墙页面可能无法完整获取
    """
    tools = _get_tools()
    timeout = min(max(timeout, 10), 60)
    result = await asyncio.to_thread(
        tools['article'].read_article,
        url=url, timeout=timeout
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@_surface.tool
async def read_articles_batch(
    urls: List[str],
    timeout: int = 30
) -> str:
    """
    批量读取多篇文章内容（最多 5 篇，间隔 5 秒）

    逐篇请求文章内容，每篇之间自动间隔 5 秒以遵守速率限制。

    **典型使用流程：**
    1. 先用 search_news(include_url=True) 搜索新闻获取多个链接
    2. 再用 read_articles_batch(urls=[...]) 批量读取正文
    3. AI 对多篇文章进行对比分析、综合报告

    Args:
        urls: 文章链接列表（必需），最多处理 5 篇
        timeout: 每篇的请求超时时间（秒），默认 30

    Returns:
        JSON格式的批量读取结果，包含每篇的完整内容和状态

    Examples:
        - read_articles_batch(urls=["https://a.com/1", "https://b.com/2"])

    Note:
        - 单次最多读取 5 篇，超出部分会被跳过
        - 5 篇约需 25-30 秒（每篇间隔 5 秒）
        - 单篇失败不影响其他篇的读取
    """
    tools = _get_tools()
    timeout = min(max(timeout, 10), 60)
    result = await asyncio.to_thread(
        tools['article'].read_articles_batch,
        urls=urls, timeout=timeout
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ==================== 启动入口 ====================

mcp = create_server()


def run_server(
    project_root: Optional[str] = None,
    transport: str = 'stdio',
    host: str = '0.0.0.0',
    port: int = 3333
):
    """
    启动 MCP 服务器

    Args:
        project_root: 项目根目录路径
        transport: 传输模式，'stdio' 或 'http'
        host: HTTP模式的监听地址，默认 0.0.0.0
        port: HTTP模式的监听端口，默认 3333
    """
    if transport not in {"stdio", "http"}:
        raise ValueError(f"不支持的传输模式: {transport}")

    server = mcp if project_root is None else create_server(
        project_root=project_root
    )
    logger.info(
        "Starting Ptilopsis Radar MCP server transport=%s root=%s",
        transport,
        project_root or "<default>",
    )

    if transport == 'stdio':
        server.run(transport='stdio')
    else:
        server.run(
            transport='http',
            host=host,
            port=port,
            path='/mcp'  # HTTP 端点路径
        )


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Ptilopsis Radar MCP Server - 新闻热点聚合 MCP 工具服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
详细配置教程请查看: README-Cherry-Studio.md
        """
    )
    parser.add_argument(
        '--transport',
        choices=['stdio', 'http'],
        default='stdio',
        help='传输模式：stdio (默认) 或 http (生产环境)'
    )
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='HTTP模式的监听地址，默认 0.0.0.0'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=3333,
        help='HTTP模式的监听端口，默认 3333'
    )
    parser.add_argument(
        '--project-root',
        help='项目根目录路径'
    )

    args = parser.parse_args()

    run_server(
        project_root=args.project_root,
        transport=args.transport,
        host=args.host,
        port=args.port
    )
