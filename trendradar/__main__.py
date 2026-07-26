# coding=utf-8
"""
Ptilopsis Radar 主程序

热点新闻聚合与分析工具
支持: python -m trendradar
"""

import logging
import os
import re
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Tuple, Optional

import requests


logger = logging.getLogger(__name__)

from trendradar.context import AppContext
from trendradar import __version__
from trendradar.core import load_config
from trendradar.core.analyzer import strip_background_groups
from trendradar.crawler import DataFetcher
from trendradar.utils.time import DEFAULT_TIMEZONE, is_within_days, calculate_days_old
from trendradar.ai import AIAnalyzer, AIAnalysisResult
from trendradar.core.scheduler import ResolvedSchedule
from trendradar.core.cdn import fetch_with_fallback

if TYPE_CHECKING:
    from trendradar.application.run_plan import RunPlan
    from trendradar.application.run_state import (
        AnalysisOutcome,
        AnalysisRequest,
    )

try:
    from trendradar.versioning import compare_version_tuple, parse_version_tuple
except ModuleNotFoundError:
    def parse_version_tuple(version_str: str) -> Tuple[int, int, int]:
        if not isinstance(version_str, str):
            return 0, 0, 0
        match = re.match(
            r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?\s*$",
            version_str,
        )
        if not match:
            return 0, 0, 0
        return int(match.group(1)), int(match.group(2)), int(match.group(3))

    def compare_version_tuple(local: str, remote: str) -> int:
        local_tuple = parse_version_tuple(local)
        remote_tuple = parse_version_tuple(remote)
        if local_tuple < remote_tuple:
            return -1
        if local_tuple > remote_tuple:
            return 1
        return 0


def _parse_version(version_str: str) -> Tuple[int, int, int]:
    """解析版本号字符串为元组，支持 x.y.z-suffix 展示版本。"""
    return parse_version_tuple(version_str)


def _compare_version(local: str, remote: str) -> str:
    """比较版本号，返回状态文字"""
    cmp = compare_version_tuple(local, remote)
    if cmp < 0:
        return "[警告] 需要更新"
    elif cmp > 0:
        return "[超前] 本地版本高于远端版本"
    else:
        return "[成功] 已是最新"


def _fetch_remote_version(version_url: str, proxy_url: Optional[str] = None) -> Optional[str]:
    """获取远程版本号（支持 CDN 多源回退）"""
    return fetch_with_fallback(version_url, proxy_url)


def _parse_config_versions(content: str) -> Dict[str, str]:
    """解析配置文件版本内容为字典"""
    versions = {}
    try:
        if not content:
            return versions
        for line in content.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            name, version = line.split("=", 1)
            versions[name.strip()] = version.strip()
    except Exception as e:
        print(f"[版本检查] 解析配置版本失败: {e}")
    return versions


def check_all_versions(
    version_url: str,
    configs_version_url: Optional[str] = None,
    proxy_url: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    统一版本检查：程序版本 + 配置文件版本

    Args:
        version_url: 远程程序版本检查 URL
        configs_version_url: 远程配置文件版本检查 URL (返回格式: filename=version)
        proxy_url: 代理 URL

    Returns:
        (need_update, remote_version): 程序是否需要更新及远程版本号
    """
    # 获取远程版本
    remote_version = _fetch_remote_version(version_url, proxy_url)

    # 获取远程配置版本（如果有提供 URL）
    remote_config_versions = {}
    if configs_version_url:
        content = _fetch_remote_version(configs_version_url, proxy_url)
        if content:
            remote_config_versions = _parse_config_versions(content)

    print("=" * 60)
    print("版本检查")
    print("=" * 60)

    if remote_version:
        print(f"远程程序版本: {remote_version}")
    else:
        print("远程程序版本: 获取失败")

    if configs_version_url:
        if remote_config_versions:
            print(f"远程配置清单: 获取成功 ({len(remote_config_versions)} 个文件)")
        else:
            print("远程配置清单: 获取失败或为空")

    print("-" * 60)

    program_status = _compare_version(__version__, remote_version) if remote_version else "(无法比较)"
    print(f"  主程序版本: {__version__} {program_status}")

    config_files = [
        Path("config/config.yaml"),
        Path("config/timeline.yaml"),
        Path("config/frequency_words.txt"),
        Path("config/ai_interests.txt"),
        Path("config/ai_translation_prompt.txt"),
    ]

    version_pattern = re.compile(r"Version:\s*(\d+\.\d+\.\d+)", re.IGNORECASE)

    for config_file in config_files:
        if not config_file.exists():
            print(f"  {config_file.name}: 文件不存在")
            continue

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                local_version = None
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    match = version_pattern.search(line)
                    if match:
                        local_version = match.group(1)
                        break

                # 获取该文件的远程版本
                target_remote_version = remote_config_versions.get(config_file.name)

                if local_version:
                    if target_remote_version:
                        status = _compare_version(local_version, target_remote_version)
                        print(f"  {config_file.name}: {local_version} {status}")
                    else:
                        print(f"  {config_file.name}: {local_version} (未找到远程版本)")
                else:
                    print(f"  {config_file.name}: 未找到本地版本号")
        except Exception as e:
            print(f"  {config_file.name}: 读取失败 - {e}")

    print("=" * 60)

    # 返回程序版本的更新状态
    if remote_version:
        need_update = _parse_version(__version__) < _parse_version(remote_version)
        return need_update, remote_version if need_update else None
    return False, None


# === 主分析器 ===
class NewsAnalyzer:
    """新闻分析器"""

    # 模式策略定义
    MODE_STRATEGIES = {
        "incremental": {
            "mode_name": "增量模式",
            "description": "增量模式（只关注新增新闻，生成 artifact）",
            "report_type": "增量分析",
        },
        "current": {
            "mode_name": "当前榜单模式",
            "description": "当前榜单模式（当前榜单匹配新闻 + 新增新闻区域，生成 artifact）",
            "report_type": "当前榜单",
        },
        "daily": {
            "mode_name": "全天汇总模式",
            "description": "全天汇总模式（所有匹配新闻 + 新增新闻区域，生成 artifact）",
            "report_type": "全天汇总",
        },
    }

    def _new_run_state(self):
        from trendradar.application.run_state import RunState

        hotlist_ids = {
            str(platform.get("id", ""))
            for platform in getattr(self.ctx, "platforms", [])
            if platform.get("id")
        }
        rss_ids = {
            str(feed.get("id", ""))
            for feed in getattr(self.ctx, "rss_feeds", [])
            if (
                getattr(self.ctx, "rss_enabled", False)
                and feed.get("id")
                and feed.get("url")
                and feed.get("enabled", True)
            )
        }
        return RunState.create(
            hotlist_configured_ids=hotlist_ids,
            rss_configured_ids=rss_ids,
        )

    def _ensure_run_state(self):
        state = getattr(self, "run_state", None)
        if state is None:
            state = self._new_run_state()
            self.run_state = state
        return state

    @property
    def _rss_source_total(self):
        return self._ensure_run_state().rss_source_total

    @_rss_source_total.setter
    def _rss_source_total(self, value):
        self._ensure_run_state().rss_source_total = value

    @property
    def _rss_source_failed(self):
        return self._ensure_run_state().rss_source_failed

    @_rss_source_failed.setter
    def _rss_source_failed(self, value):
        self._ensure_run_state().rss_source_failed = value

    @property
    def _rss_total_count(self):
        return self._ensure_run_state().rss_total_count

    @_rss_total_count.setter
    def _rss_total_count(self, value):
        self._ensure_run_state().rss_total_count = value

    @property
    def _rss_matched_count(self):
        return self._ensure_run_state().rss_matched_count

    @_rss_matched_count.setter
    def _rss_matched_count(self, value):
        self._ensure_run_state().rss_matched_count = value

    @property
    def _hotlist_total_count(self):
        return self._ensure_run_state().hotlist_total_count

    @_hotlist_total_count.setter
    def _hotlist_total_count(self, value):
        self._ensure_run_state().hotlist_total_count = value

    @property
    def _cr_raw_rss_items(self):
        return self._ensure_run_state().raw_rss_items

    @_cr_raw_rss_items.setter
    def _cr_raw_rss_items(self, value):
        self._ensure_run_state().raw_rss_items = value

    @property
    def _cr_hotlist_configured_ids(self):
        return self._ensure_run_state().hotlist.configured_ids

    @_cr_hotlist_configured_ids.setter
    def _cr_hotlist_configured_ids(self, value):
        self._ensure_run_state().hotlist.configured_ids = frozenset(value)

    @property
    def _cr_hotlist_successful_ids(self):
        return self._ensure_run_state().hotlist.successful_ids

    @_cr_hotlist_successful_ids.setter
    def _cr_hotlist_successful_ids(self, value):
        self._ensure_run_state().hotlist.successful_ids = set(value)

    @property
    def _cr_hotlist_failed_ids(self):
        return self._ensure_run_state().hotlist.failed_ids

    @_cr_hotlist_failed_ids.setter
    def _cr_hotlist_failed_ids(self, value):
        self._ensure_run_state().hotlist.failed_ids = set(value)

    @property
    def _cr_rss_configured_ids(self):
        return self._ensure_run_state().rss.configured_ids

    @_cr_rss_configured_ids.setter
    def _cr_rss_configured_ids(self, value):
        self._ensure_run_state().rss.configured_ids = frozenset(value)

    @property
    def _cr_rss_successful_ids(self):
        return self._ensure_run_state().rss.successful_ids

    @_cr_rss_successful_ids.setter
    def _cr_rss_successful_ids(self, value):
        self._ensure_run_state().rss.successful_ids = set(value)

    @property
    def _cr_rss_failed_ids(self):
        return self._ensure_run_state().rss.failed_ids

    @_cr_rss_failed_ids.setter
    def _cr_rss_failed_ids(self, value):
        self._ensure_run_state().rss.failed_ids = set(value)

    @property
    def _cr_observed_item_identities(self):
        return self._ensure_run_state().observed_item_identities

    @_cr_observed_item_identities.setter
    def _cr_observed_item_identities(self, value):
        self._ensure_run_state().observed_item_identities = set(value)

    @property
    def _cr_input_snapshot_generated_at(self):
        return self._ensure_run_state().input_snapshot_generated_at

    @_cr_input_snapshot_generated_at.setter
    def _cr_input_snapshot_generated_at(self, value):
        self._ensure_run_state().input_snapshot_generated_at = value

    @property
    def _cr_historical_data_reused(self):
        return self._ensure_run_state().historical_data_reused

    @_cr_historical_data_reused.setter
    def _cr_historical_data_reused(self, value):
        self._ensure_run_state().historical_data_reused = bool(value)

    @property
    def _cr_rss_historical_data_reused(self):
        return self._ensure_run_state().rss_historical_data_reused

    @_cr_rss_historical_data_reused.setter
    def _cr_rss_historical_data_reused(self, value):
        self._ensure_run_state().rss_historical_data_reused = bool(value)

    def __init__(self, config: Optional[Dict] = None):
        # 使用传入的配置或加载新配置
        if config is None:
            print("正在加载配置...")
            config = load_config()
        print(f"Ptilopsis Radar v{__version__} 配置加载完成")
        print(f"监控平台数量: {len(config['PLATFORMS'])}")
        print(f"时区: {config.get('TIMEZONE', DEFAULT_TIMEZONE)}")

        # 创建应用上下文
        self.ctx = AppContext(config)

        self.request_interval = self.ctx.config["REQUEST_INTERVAL"]
        self.report_mode = self.ctx.config["REPORT_MODE"]
        self.frequency_file = None
        self.filter_method = None  # None=使用全局配置 ctx.filter_method
        self.interests_file = None  # None=使用全局配置 ai_filter.interests_file
        self.rank_threshold = self.ctx.rank_threshold
        self.is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        self.is_docker_container = self._detect_docker_environment()
        self.update_info = None
        self.proxy_url = None
        self._setup_proxy()
        self.data_fetcher = DataFetcher(
            self.proxy_url,
            api_url=self.ctx.config.get("PLATFORMS_API_URL") or None,
            max_retries=self.ctx.config.get("MAX_RETRIES", 4),
        )

        # RSS/平台元数据（用于报告头部展示）
        self._rss_source_total = 0
        self._rss_source_failed = 0
        self._rss_total_count = 0
        self._rss_matched_count = 0
        # Full RSS for the run, made available to the CR cross-evidence
        # admission path (set in _execute_mode_strategy, read in
        # _run_analysis_pipeline).  See trendradar/cr/cross_evidence_ingest.
        self._cr_raw_rss_items = None
        self._hotlist_total_count = 0
        self._cr_hotlist_configured_ids = {
            str(p.get("id", "")) for p in self.ctx.platforms if p.get("id")
        }
        self._cr_hotlist_successful_ids: set[str] = set()
        self._cr_hotlist_failed_ids: set[str] = set()
        self._cr_rss_configured_ids = {
            str(feed.get("id", ""))
            for feed in self.ctx.rss_feeds
            if (
                self.ctx.rss_enabled
                and feed.get("id")
                and feed.get("url")
                and feed.get("enabled", True)
            )
        }
        self._cr_rss_successful_ids: set[str] = set()
        self._cr_rss_failed_ids: set[str] = set()
        self._cr_observed_item_identities: set[str] = set()
        self._cr_input_snapshot_generated_at: str | None = None
        self._cr_historical_data_reused = False
        self._cr_rss_historical_data_reused = False

        # 初始化存储管理器（使用 AppContext）
        self._init_storage_manager()
        # 注意：update_info 由 main() 函数设置，避免重复请求远程版本

    def _init_storage_manager(self) -> None:
        """初始化存储管理器（使用 AppContext）"""
        self.storage_manager = self.ctx.get_storage_manager()
        active_backend = self.storage_manager.backend_name

        # 获取数据保留天数（支持环境变量覆盖）
        env_retention = os.environ.get("STORAGE_RETENTION_DAYS", "").strip()
        if env_retention:
            active_backend = self.ctx.set_retention_days_for_active_backend(
                int(env_retention)
            )

        print(f"存储后端: {self.storage_manager.backend_name}")

        retention_days = (
            self.storage_manager.remote_retention_days
            if active_backend == "remote"
            else self.storage_manager.local_retention_days
        )
        if retention_days > 0:
            print(f"数据保留天数: {retention_days} 天")

    def _detect_docker_environment(self) -> bool:
        """检测是否运行在 Docker 容器中"""
        try:
            if os.environ.get("DOCKER_CONTAINER") == "true":
                return True

            if os.path.exists("/.dockerenv"):
                return True

            return False
        except Exception:
            return False

    def _should_open_browser(self) -> bool:
        """判断是否应该打开浏览器"""
        return not self.is_github_actions and not self.is_docker_container

    def _setup_proxy(self) -> None:
        """设置代理配置"""
        if not self.is_github_actions and self.ctx.config["USE_PROXY"]:
            self.proxy_url = self.ctx.config["DEFAULT_PROXY"]
            print("本地环境，使用代理")
        elif not self.is_github_actions and not self.ctx.config["USE_PROXY"]:
            print("本地环境，未启用代理")
        else:
            print("GitHub Actions环境，不使用代理")

    def _set_update_info_from_config(self) -> None:
        """从已缓存的远程版本设置更新信息（不再重复请求）"""
        try:
            version_url = self.ctx.config.get("VERSION_CHECK_URL", "")
            if not version_url:
                return

            remote_version = _fetch_remote_version(version_url, self.proxy_url)
            if remote_version:
                need_update = _parse_version(__version__) < _parse_version(remote_version)
                if need_update:
                    self.update_info = {
                        "current_version": __version__,
                        "remote_version": remote_version,
                    }
        except Exception as e:
            print(f"版本检查出错: {e}")

    def _get_mode_strategy(self) -> Dict:
        """获取当前模式的策略配置"""
        return self.MODE_STRATEGIES.get(self.report_mode, self.MODE_STRATEGIES["daily"])

    def _resolve_run_plan(self) -> "RunPlan":
        """Resolve and apply the effective run configuration exactly once."""
        from trendradar.application.run_plan import RunPlanBuilder

        schedule = self.ctx.create_scheduler().resolve()
        run_plan = RunPlanBuilder.build(schedule, self.ctx.config)

        if run_plan.report_mode != self.report_mode:
            print(
                f"[调度] 报告模式覆盖: "
                f"{self.report_mode} -> {run_plan.report_mode}"
            )

        # Temporary compatibility mirrors.  Downstream code receives RunPlan
        # explicitly; these fields keep existing helpers stable during the
        # staged extraction of RunState/RunCoordinator.
        self.report_mode = run_plan.report_mode
        self.frequency_file = run_plan.frequency_file
        self.filter_method = run_plan.filter_method
        self.interests_file = run_plan.interests_file
        return run_plan

    def _has_valid_content(
        self, stats: List[Dict], new_titles: Optional[Dict] = None
    ) -> bool:
        """检查是否有有效的新闻内容"""
        if self.report_mode == "incremental":
            # 增量模式：只要有匹配的新闻就生成 artifact
            # count_word_frequency 已经确保只处理新增的新闻（包括当天第一次爬取的情况）
            has_matched_news = any(stat["count"] > 0 for stat in stats)
            return has_matched_news
        elif self.report_mode == "current":
            # current模式：只要stats有内容就说明有匹配的新闻
            return any(stat["count"] > 0 for stat in stats)
        else:
            # 当日汇总模式下，检查是否有匹配的频率词新闻或新增新闻
            has_matched_news = any(stat["count"] > 0 for stat in stats)
            has_new_news = bool(
                new_titles and any(len(titles) > 0 for titles in new_titles.values())
            )
            return has_matched_news or has_new_news

    def _prepare_ai_analysis_data(
        self,
        ai_mode: str,
        current_results: Optional[Dict] = None,
        current_id_to_name: Optional[Dict] = None,
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """
        为 AI 分析准备指定模式的数据

        Args:
            ai_mode: AI 分析模式 (daily/current/incremental)
            current_results: 当前抓取的结果（用于 incremental 模式）
            current_id_to_name: 当前的平台映射（用于 incremental 模式）

        Returns:
            Tuple[stats, id_to_name]: 统计数据和平台映射
        """
        try:
            word_groups, filter_words, global_filters = self.ctx.load_frequency_words(self.frequency_file)

            if ai_mode == "incremental":
                # incremental 模式：使用当前抓取的数据
                if not current_results or not current_id_to_name:
                    print("[AI] incremental 模式需要当前抓取数据，但未提供")
                    return [], None

                # 准备当前时间信息
                time_info = self.ctx.format_time()
                title_info = self._prepare_current_title_info(current_results, time_info)

                # 检测新增标题
                new_titles = self.ctx.detect_new_titles(list(current_results.keys()))

                # 统计计算
                stats, _ = self.ctx.count_frequency(
                    current_results,
                    word_groups,
                    filter_words,
                    current_id_to_name,
                    title_info,
                    new_titles,
                    mode="incremental",
                    global_filters=global_filters,
                    quiet=True,
                )

                return stats, current_id_to_name

            elif ai_mode in ["daily", "current"]:
                # 加载历史数据
                analysis_data = self._load_analysis_data(quiet=True)
                if not analysis_data:
                    print(f"[AI] 无法加载历史数据用于 {ai_mode} 模式分析")
                    return [], None

                (
                    all_results,
                    id_to_name,
                    title_info,
                    new_titles,
                    _,
                    _,
                    _,
                ) = analysis_data

                # 统计计算
                stats, _ = self.ctx.count_frequency(
                    all_results,
                    word_groups,
                    filter_words,
                    id_to_name,
                    title_info,
                    new_titles,
                    mode=ai_mode,
                    global_filters=global_filters,
                    quiet=True,
                )

                return stats, id_to_name
            else:
                print(f"[AI] 未知的 AI 模式: {ai_mode}")
                return [], None

        except Exception as e:
            print(f"[AI] 准备 {ai_mode} 模式数据时出错: {e}")
            if self.ctx.config.get("DEBUG", False):
                import traceback
                traceback.print_exc()
            return [], None

    def _run_ai_analysis(
        self,
        stats: List[Dict],
        rss_items: Optional[List[Dict]],
        mode: str,
        report_type: str,
        id_to_name: Optional[Dict],
        current_results: Optional[Dict] = None,
        schedule: ResolvedSchedule = None,
    ) -> Optional[AIAnalysisResult]:
        """Compatibility façade over the application AI analysis service."""
        from trendradar.application.services.ai import (
            AIAnalysisRequest,
            AIAnalysisService,
        )

        return AIAnalysisService(
            self.ctx,
            prepare_mode_data=getattr(
                self,
                "_prepare_ai_analysis_data",
                lambda _mode, _results, names: ([], names),
            ),
        ).run(
            AIAnalysisRequest(
                stats=stats,
                rss_items=rss_items,
                mode=mode,
                report_type=report_type,
                id_to_name=id_to_name,
                current_results=current_results,
            ),
            schedule,
        )

    def _load_analysis_data(
        self,
        quiet: bool = False,
    ) -> Optional[Tuple[Dict, Dict, Dict, Dict, List, List]]:
        """统一的数据加载和预处理，使用当前监控平台列表过滤历史数据"""
        try:
            history = self._load_history_input(quiet=quiet)
            if not history:
                return None
            all_results, id_to_name, title_info, new_titles = history
            word_groups, filter_words, global_filters = self.ctx.load_frequency_words(self.frequency_file)

            return (
                all_results,
                id_to_name,
                title_info,
                new_titles,
                word_groups,
                filter_words,
                global_filters,
            )
        except Exception as e:
            print(f"数据加载失败: {e}")
            return None

    def _load_history_input(
        self,
        quiet: bool = False,
    ) -> Optional[Tuple[Dict, Dict, Dict, Dict]]:
        """Load persisted input only; frequency configuration is a separate boundary."""
        try:
            current_platform_ids = self.ctx.platform_ids
            if not quiet:
                print(f"当前监控平台: {current_platform_ids}")

            all_results, id_to_name, title_info = self.ctx.read_today_titles(
                current_platform_ids,
                quiet=quiet,
            )
            if not all_results:
                print("没有找到当天的数据")
                return None

            total_titles = sum(len(titles) for titles in all_results.values())
            if not quiet:
                print(f"读取到 {total_titles} 个标题（已按当前监控平台过滤）")
            new_titles = self.ctx.detect_new_titles(
                current_platform_ids,
                quiet=quiet,
            )
            return all_results, id_to_name, title_info, new_titles
        except Exception as exc:
            print(f"数据加载失败: {exc}")
            return None

    def _prepare_current_title_info(self, results: Dict, time_info: str) -> Dict:
        """从当前抓取结果构建标题信息"""
        title_info = {}
        for source_id, titles_data in results.items():
            title_info[source_id] = {}
            for title, title_data in titles_data.items():
                ranks = title_data.get("ranks", [])
                url = title_data.get("url", "")
                mobile_url = title_data.get("mobileUrl", "")

                title_info[source_id][title] = {
                    "first_time": time_info,
                    "last_time": time_info,
                    "count": 1,
                    "ranks": ranks,
                    "url": url,
                    "mobileUrl": mobile_url,
                }
        return title_info

    def _run_analysis_pipeline(
        self,
        request: "AnalysisRequest",
        schedule: "RunPlan",
    ) -> "AnalysisOutcome":
        """统一的分析流水线：数据处理 → 统计计算（关键词/AI筛选）→ AI分析 → HTML生成"""
        data_source = request.results
        mode = request.mode
        new_titles = request.new_titles
        id_to_name = request.id_to_name
        failed_ids = request.failed_ids
        rss_new_items = request.rss_new_items

        from trendradar.application.services.analysis import AnalysisService

        selection = AnalysisService(self.ctx).analyze(
            request,
            filter_method=self.filter_method,
            interests_file=self.interests_file,
        )
        stats = selection.stats
        total_titles = selection.total_titles
        rss_items = selection.rss_items

        self._hotlist_total_count = total_titles

        # AI 分析（如果启用，用于 HTML 报告）
        ai_result = None
        ai_config = self.ctx.config.get("AI_ANALYSIS", {})
        if ai_config.get("ENABLED", False) and (stats or rss_items):
            # 获取模式策略来确定报告类型
            mode_strategy = self._get_mode_strategy()
            report_type = mode_strategy["report_type"]
            ai_result = self._run_ai_analysis(
                stats, rss_items, mode, report_type, id_to_name,
                current_results=data_source, schedule=schedule,
            )

        from trendradar.application.services.report import (
            ContextReportGateway,
            ReportCounters,
            ReportRequest,
            ReportService,
        )

        report_result = ReportService(
            ContextReportGateway(self.ctx)
        ).render(
            ReportRequest(
                mode=mode,
                stats=stats,
                total_titles=total_titles,
                failed_ids=failed_ids,
                new_titles=new_titles,
                id_to_name=id_to_name,
                rss_items=rss_items,
                rss_new_items=rss_new_items,
                ai_analysis=ai_result,
                update_info=self.update_info,
                frequency_file=self.frequency_file,
                counters=ReportCounters(
                    platform_total=len(self.ctx.platform_ids),
                    rss_total_count=self._rss_total_count,
                    rss_source_total=self._rss_source_total,
                    rss_source_failed=self._rss_source_failed,
                ),
            )
        )
        html_file = report_result.html_file
        rss_items = report_result.rss_items
        self._rss_matched_count = report_result.rss_matched_count

        from trendradar.application.services.notification import (
            AnalysisNotificationEvent,
            NotificationHook,
            NotificationService,
        )

        dr_dispatch_hook = getattr(self, "_run_dr_dispatch_hook", None)
        cr_dispatch_hook = getattr(self, "_run_cr_dispatch_hook", None)
        notification_event = AnalysisNotificationEvent(
            mode=mode,
            ai_result=ai_result,
            html_file=html_file,
            schedule=schedule,
        )
        NotificationService(
            error_reporter=lambda _name, exc: print(
                f"[DR] dispatch hook error (non-fatal): {exc}"
            )
        ).notify(
            notification_event,
            (
                NotificationHook(
                    name="dr",
                    predicate=lambda event: bool(
                        event.mode == "daily"
                        and event.html_file
                        and callable(dr_dispatch_hook)
                    ),
                    handler=lambda event: dr_dispatch_hook(
                        ai_result=event.ai_result,
                        html_file=event.html_file,
                        schedule=event.schedule,
                    ),
                    suppress_exceptions=True,
                ),
                NotificationHook(
                    name="cr",
                    predicate=lambda _event: callable(cr_dispatch_hook),
                    handler=lambda event: cr_dispatch_hook(
                        mode=event.mode,
                        stats=stats,
                        rss_items=rss_items,
                    ),
                ),
            ),
        )

        from trendradar.application.run_state import AnalysisOutcome

        return AnalysisOutcome(
            stats=stats,
            total_titles=total_titles,
            html_file=html_file,
            ai_result=ai_result,
            rss_items=rss_items,
            rss_matched_count=report_result.rss_matched_count,
        )

    def _run_cr_dispatch_hook(
        self,
        *,
        mode: str,
        stats: List[Dict],
        rss_items: Optional[List[Dict]],
    ):
        """Compatibility façade over the CR notification service."""
        from trendradar.application.services.cr_notification import (
            CRNotificationRequest,
            CRNotificationService,
        )

        state = self.run_state
        return CRNotificationService(
            self.ctx,
            logger=logger,
        ).run(
            CRNotificationRequest(
                mode=mode,
                hotlist_stats=stats,
                rss_stats=rss_items,
                raw_rss_items=state.raw_rss_items,
                hotlist_configured_ids=state.hotlist.configured_ids,
                hotlist_successful_ids=frozenset(
                    state.hotlist.successful_ids
                ),
                hotlist_failed_ids=frozenset(state.hotlist.failed_ids),
                rss_configured_ids=state.rss.configured_ids,
                rss_successful_ids=frozenset(state.rss.successful_ids),
                rss_failed_ids=frozenset(state.rss.failed_ids),
                observed_item_identities=frozenset(
                    state.observed_item_identities
                ),
                snapshot_generated_at=state.input_snapshot_generated_at,
                historical_data_reused=state.historical_data_reused,
            )
        )

    def _run_dr_dispatch_hook(
        self,
        *,
        ai_result: Optional[AIAnalysisResult],
        html_file: str,
        schedule: Optional[ResolvedSchedule] = None,
    ):
        """Compatibility façade over the DR notification service."""
        from trendradar.application.services.dr_notification import (
            DRNotificationService,
        )

        return DRNotificationService(self.ctx).run(
            ai_result=ai_result,
            html_file=html_file,
            schedule=schedule,
        )

    def _initialize_and_check_config(self) -> bool:
        """通用初始化和配置检查。返回 True 表示可以继续执行。"""
        now = self.ctx.get_time()
        print(f"当前北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        if not self.ctx.config["ENABLE_CRAWLER"]:
            print("爬虫功能已禁用（ENABLE_CRAWLER=False），程序退出")
            return False

        mode_strategy = self._get_mode_strategy()
        print(f"报告模式: {self.report_mode}")
        print(f"运行模式: {mode_strategy['description']}")
        return True

    def _crawl_data(self) -> Tuple[Dict, Dict, List]:
        """执行数据爬取"""
        print(
            f"配置的监控平台: {[p.get('name', p['id']) for p in self.ctx.platforms]}"
        )
        print(f"开始爬取数据，请求间隔 {self.request_interval} 毫秒")

        from trendradar.application.collectors import HotlistCollector

        batch = HotlistCollector(
            fetcher=self.data_fetcher,
            storage=self.storage_manager,
            clock=self.ctx,
        ).collect(
            platforms=self.ctx.platforms,
            request_interval=self.request_interval,
        )
        results = dict(batch.raw_results)
        id_to_name = dict(batch.id_to_name)
        failed_ids = list(batch.failed_ids)
        from trendradar.cr.input_health import input_item_identity

        self._cr_hotlist_configured_ids = batch.configured_ids
        self._cr_hotlist_failed_ids = batch.failed_ids
        self._cr_hotlist_successful_ids = batch.successful_ids
        for source_id, titles in results.items():
            if str(source_id) not in self._cr_hotlist_successful_ids:
                continue
            for title in titles:
                self._cr_observed_item_identities.add(input_item_identity(
                    source_type="hotlist", source_id=str(source_id), title=str(title),
                ))
        if self._cr_hotlist_successful_ids:
            self._cr_input_snapshot_generated_at = self.ctx.get_time().isoformat()

        if batch.saved:
            print(f"数据已保存到存储后端: {self.storage_manager.backend_name}")
        else:
            print("数据保存失败")
        if batch.snapshot_path:
            print(f"TXT 快照已保存: {batch.snapshot_path}")

        return results, id_to_name, failed_ids

    def _crawl_rss_data(
        self,
        run_plan: "RunPlan",
    ) -> Tuple[Optional[List[Dict]], Optional[List[Dict]], Optional[List[Dict]], set]:
        """
        执行 RSS 数据抓取

        Returns:
            (rss_items, rss_new_items, raw_rss_items, rss_new_urls) 元组：
            - rss_items: 统计条目列表（按模式处理，用于统计区块）
            - rss_new_items: 新增条目列表（用于新增区块）
            - raw_rss_items: 原始 RSS 条目列表（供 AI 筛选与 CR 输入使用）
            - rss_new_urls: 原始新增 RSS 条目的 URL 集合（用于 AI 模式 is_new 检测）
            如果未启用或失败返回 (None, None, None, set())
        """
        if not self.ctx.rss_enabled:
            return None, None, None, set()

        rss_feeds = self.ctx.rss_feeds
        if not rss_feeds:
            print("[RSS] 未配置任何 RSS 源")
            return None, None, None, set()

        try:
            from trendradar.crawler.rss import RSSFetcher, RSSFeedConfig

            # 构建 RSS 源配置
            feeds = []
            for feed_config in rss_feeds:
                # 读取并验证单个 feed 的 max_age_days（可选）
                max_age_days_raw = feed_config.get("max_age_days")
                max_age_days = None
                if max_age_days_raw is not None:
                    try:
                        max_age_days = int(max_age_days_raw)
                        if max_age_days < 0:
                            feed_id = feed_config.get("id", "unknown")
                            print(f"[警告] RSS feed '{feed_id}' 的 max_age_days 为负数，将使用全局默认值")
                            max_age_days = None
                    except (ValueError, TypeError):
                        feed_id = feed_config.get("id", "unknown")
                        print(f"[警告] RSS feed '{feed_id}' 的 max_age_days 格式错误：{max_age_days_raw}")
                        max_age_days = None

                feed = RSSFeedConfig(
                    id=feed_config.get("id", ""),
                    name=feed_config.get("name", ""),
                    url=feed_config.get("url", ""),
                    max_items=feed_config.get("max_items", 50),
                    enabled=feed_config.get("enabled", True),
                    max_age_days=max_age_days,  # None=使用全局，0=禁用，>0=覆盖
                    source_type=feed_config.get("source_type", "rss"),
                    link_prefixes=feed_config.get("link_prefixes"),
                )
                if feed.id and feed.url and feed.enabled:
                    feeds.append(feed)

            if not feeds:
                print("[RSS] 没有启用的 RSS 源")
                return None, None, None, set()

            # 创建抓取器
            rss_config = self.ctx.rss_config
            # RSS 代理：优先使用 RSS 专属代理，否则使用爬虫默认代理
            rss_proxy_url = rss_config.get("PROXY_URL", "") or self.proxy_url or ""
            # 获取配置的时区
            timezone = self.ctx.config.get("TIMEZONE", DEFAULT_TIMEZONE)
            # 获取新鲜度过滤配置
            freshness_config = rss_config.get("FRESHNESS_FILTER", {})
            freshness_enabled = freshness_config.get("ENABLED", True)
            default_max_age_days = freshness_config.get("MAX_AGE_DAYS", 3)

            fetcher = RSSFetcher(
                feeds=feeds,
                request_interval=rss_config.get("REQUEST_INTERVAL", 2000),
                timeout=rss_config.get("TIMEOUT", 15),
                max_retries=rss_config.get("MAX_RETRIES", 2),
                use_proxy=rss_config.get("USE_PROXY", False),
                proxy_url=rss_proxy_url,
                timezone=timezone,
                freshness_enabled=freshness_enabled,
                default_max_age_days=default_max_age_days,
            )

            from trendradar.application.collectors import RSSCollector

            batch = RSSCollector(
                fetcher=fetcher,
                storage=self.storage_manager,
            ).collect(configured_ids={feed.id for feed in feeds})
            rss_data = batch.rss_data

            self._rss_source_total = len(feeds)
            # Keep the wire-health source explicit at the compatibility façade:
            # CR input health is defined by the fetcher's RSSData contract.
            self._rss_source_failed = len(rss_data.failed_ids)
            self._cr_rss_configured_ids = batch.configured_ids
            self._cr_rss_failed_ids = {
                str(value) for value in rss_data.failed_ids
            }
            self._cr_rss_successful_ids = batch.successful_ids
            from trendradar.cr.input_health import input_item_identity

            for feed_id, items in rss_data.items.items():
                if str(feed_id) not in self._cr_rss_successful_ids:
                    continue
                for item in items:
                    self._cr_observed_item_identities.add(input_item_identity(
                        source_type="rss",
                        feed_id=str(feed_id),
                        title=item.title,
                        url=item.url,
                    ))
            if self._cr_rss_successful_ids:
                self._cr_input_snapshot_generated_at = self.ctx.get_time().isoformat()

            if batch.saved:
                print(f"[RSS] 数据已保存到存储后端")

                # 处理 RSS 数据（按模式过滤）并返回用于 artifact 生成
                return self._process_rss_data_by_mode(rss_data, run_plan)
            else:
                print(f"[RSS] 数据保存失败")
                return None, None, None, set()

        except ImportError as e:
            self._cr_rss_failed_ids = set(self._cr_rss_configured_ids)
            print(f"[RSS] 缺少依赖: {e}")
            print("[RSS] 请安装 feedparser: pip install feedparser")
            return None, None, None, set()
        except Exception as e:
            self._cr_rss_failed_ids = set(self._cr_rss_configured_ids)
            print(f"[RSS] 抓取失败: {e}")
            return None, None, None, set()

    def _process_rss_data_by_mode(
        self,
        rss_data,
        run_plan: "RunPlan",
    ) -> Tuple[Optional[List[Dict]], Optional[List[Dict]], Optional[List[Dict]], set]:
        """
        按报告模式处理 RSS 数据，返回与热榜相同格式的统计结构

        三种模式：
        - daily: 当日汇总，统计=当天所有条目，新增=本次新增条目
        - current: 当前榜单，统计=当前榜单条目，新增=本次新增条目
        - incremental: 增量模式，统计=新增条目，新增=无

        Args:
            rss_data: 当前抓取的 RSSData 对象

        Returns:
            (rss_stats, rss_new_stats, raw_rss_items, rss_new_urls) 元组：
            - rss_stats: RSS 关键词统计列表（与热榜 stats 格式一致）
            - rss_new_stats: RSS 新增关键词统计列表（与热榜 stats 格式一致）
            - raw_rss_items: 原始 RSS 条目列表（供 AI 筛选与 CR 输入使用）
            - rss_new_urls: 原始新增 RSS 条目的 URL 集合（未经关键词过滤，用于 AI 模式 is_new 检测）
        """
        from trendradar.core.analyzer import count_rss_frequency

        # 加载关键词配置
        try:
            word_groups, filter_words, global_filters = self.ctx.load_frequency_words(
                run_plan.frequency_file
            )
        except FileNotFoundError:
            word_groups, filter_words, global_filters = [], [], []

        timezone = self.ctx.timezone
        max_news_per_keyword = self.ctx.config.get("MAX_NEWS_PER_KEYWORD", 0)
        sort_by_position_first = self.ctx.config.get("SORT_BY_POSITION_FIRST", False)

        rss_stats = None
        rss_new_stats = None
        raw_rss_items = None  # 原始 RSS 条目列表（供下游分析与 CR 输入使用）
        rss_new_urls = set()  # 原始新增 RSS URLs（未经关键词过滤）

        # 1. 首先获取原始条目（供下游分析与 CR 输入使用）
        # 根据模式获取原始条目
        if run_plan.report_mode == "incremental":
            new_items_dict = self.storage_manager.detect_new_rss_items(rss_data)
            if new_items_dict:
                raw_rss_items = self._convert_rss_items_to_list(new_items_dict, rss_data.id_to_name)
        elif run_plan.report_mode == "current":
            latest_data = self.storage_manager.get_latest_rss_data(rss_data.date)
            if latest_data:
                self._cr_rss_historical_data_reused = True
                raw_rss_items = self._convert_rss_items_to_list(latest_data.items, latest_data.id_to_name)
        else:  # daily
            all_data = self.storage_manager.get_rss_data(rss_data.date)
            if all_data:
                self._cr_rss_historical_data_reused = True
                raw_rss_items = self._convert_rss_items_to_list(all_data.items, all_data.id_to_name)

        # 2. 获取新增条目（用于统计）
        new_items_dict = self.storage_manager.detect_new_rss_items(rss_data)
        new_items_list = None
        if new_items_dict:
            new_items_list = self._convert_rss_items_to_list(new_items_dict, rss_data.id_to_name)
            if new_items_list:
                print(f"[RSS] 检测到 {len(new_items_list)} 条新增")
                # 收集原始新增 URLs（未经关键词过滤，用于 AI 模式 is_new 检测）
                rss_new_urls = {item["url"] for item in new_items_list if item.get("url")}

        # 3. 根据模式获取统计条目
        if run_plan.report_mode == "incremental":
            # 增量模式：统计条目就是新增条目
            if not new_items_list:
                print("[RSS] 增量模式：没有新增 RSS 条目")
                return None, None, raw_rss_items, rss_new_urls

            rss_stats, total = count_rss_frequency(
                rss_items=new_items_list,
                word_groups=word_groups,
                filter_words=filter_words,
                global_filters=global_filters,
                new_items=new_items_list,  # 增量模式所有都是新增
                max_news_per_keyword=max_news_per_keyword,
                sort_by_position_first=sort_by_position_first,
                timezone=timezone,
                rank_threshold=self.rank_threshold,
                quiet=False,
            )
            if not rss_stats:
                print("[RSS] 增量模式：关键词匹配后没有内容")
                # 即使关键词匹配为空，也返回原始条目供下游分析使用
                return None, None, raw_rss_items, rss_new_urls

        elif run_plan.report_mode == "current":
            # 当前榜单模式：统计=当前榜单所有条目
            # raw_rss_items 已在前面获取
            if not raw_rss_items:
                print("[RSS] 当前榜单模式：没有 RSS 数据")
                return None, None, None, rss_new_urls

            rss_stats, total = count_rss_frequency(
                rss_items=raw_rss_items,
                word_groups=word_groups,
                filter_words=filter_words,
                global_filters=global_filters,
                new_items=new_items_list,  # 标记新增
                max_news_per_keyword=max_news_per_keyword,
                sort_by_position_first=sort_by_position_first,
                timezone=timezone,
                rank_threshold=self.rank_threshold,
                quiet=False,
            )
            if not rss_stats:
                print("[RSS] 当前榜单模式：关键词匹配后没有内容")
                # 即使关键词匹配为空，也返回原始条目供下游分析使用
                return None, None, raw_rss_items, rss_new_urls

            # 生成新增统计
            if new_items_list:
                rss_new_stats, _ = count_rss_frequency(
                    rss_items=new_items_list,
                    word_groups=word_groups,
                    filter_words=filter_words,
                    global_filters=global_filters,
                    new_items=new_items_list,
                    max_news_per_keyword=max_news_per_keyword,
                    sort_by_position_first=sort_by_position_first,
                    timezone=timezone,
                    rank_threshold=self.rank_threshold,
                    quiet=True,
                )

        else:
            # daily 模式：统计=当天所有条目
            # raw_rss_items 已在前面获取
            if not raw_rss_items:
                print("[RSS] 当日汇总模式：没有 RSS 数据")
                return None, None, None, rss_new_urls

            rss_stats, total = count_rss_frequency(
                rss_items=raw_rss_items,
                word_groups=word_groups,
                filter_words=filter_words,
                global_filters=global_filters,
                new_items=new_items_list,  # 标记新增
                max_news_per_keyword=max_news_per_keyword,
                sort_by_position_first=sort_by_position_first,
                timezone=timezone,
                rank_threshold=self.rank_threshold,
                quiet=False,
            )
            if not rss_stats:
                print("[RSS] 当日汇总模式：关键词匹配后没有内容")
                # 即使关键词匹配为空，也返回原始条目供下游分析使用
                return None, None, raw_rss_items, rss_new_urls

            # 生成新增统计
            if new_items_list:
                rss_new_stats, _ = count_rss_frequency(
                    rss_items=new_items_list,
                    word_groups=word_groups,
                    filter_words=filter_words,
                    global_filters=global_filters,
                    new_items=new_items_list,
                    max_news_per_keyword=max_news_per_keyword,
                    sort_by_position_first=sort_by_position_first,
                    timezone=timezone,
                    rank_threshold=self.rank_threshold,
                    quiet=True,
                )

        # 首次抓取时全部条目都是新增，清除新增统计以避免与主区域完全重复
        if rss_new_stats and rss_stats:
            main_count = sum(len(s.get("titles", [])) for s in rss_stats)
            new_count = sum(len(s.get("titles", [])) for s in rss_new_stats)
            if new_count > 0 and new_count >= main_count:
                rss_new_stats = None

        self._rss_total_count = total
        return rss_stats, rss_new_stats, raw_rss_items, rss_new_urls

    def _convert_rss_items_to_list(self, items_dict: Dict, id_to_name: Dict) -> List[Dict]:
        """将 RSS 条目字典转换为列表格式，并应用新鲜度过滤（用于 artifact 生成）"""
        rss_items = []
        filtered_count = 0
        filtered_details = []  # 用于 DEBUG 模式下的详细日志

        # 获取新鲜度过滤配置
        rss_config = self.ctx.rss_config
        freshness_config = rss_config.get("FRESHNESS_FILTER", {})
        freshness_enabled = freshness_config.get("ENABLED", True)
        default_max_age_days = freshness_config.get("MAX_AGE_DAYS", 3)
        timezone = self.ctx.config.get("TIMEZONE", DEFAULT_TIMEZONE)
        debug_mode = self.ctx.config.get("DEBUG", False)

        # 构建 feed_id -> max_age_days 的映射
        feed_max_age_map = {}
        for feed_cfg in self.ctx.rss_feeds:
            feed_id = feed_cfg.get("id", "")
            max_age = feed_cfg.get("max_age_days")
            if max_age is not None:
                try:
                    feed_max_age_map[feed_id] = int(max_age)
                except (ValueError, TypeError):
                    pass

        for feed_id, items in items_dict.items():
            # 确定此 feed 的 max_age_days
            max_days = feed_max_age_map.get(feed_id)
            if max_days is None:
                max_days = default_max_age_days

            for item in items:
                # 应用新鲜度过滤（仅在启用时）
                if freshness_enabled and max_days > 0:
                    if item.published_at and not is_within_days(item.published_at, max_days, timezone):
                        filtered_count += 1
                        # 记录详细信息用于 DEBUG 模式
                        if debug_mode:
                            days_old = calculate_days_old(item.published_at, timezone)
                            feed_name = id_to_name.get(feed_id, feed_id)
                            filtered_details.append({
                                "title": item.title[:50] + "..." if len(item.title) > 50 else item.title,
                                "feed": feed_name,
                                "days_old": days_old,
                                "max_days": max_days,
                            })
                        continue  # 跳过超过指定天数的文章

                rss_items.append({
                    "title": item.title,
                    "feed_id": feed_id,
                    "feed_name": id_to_name.get(feed_id, feed_id),
                    "url": item.url,
                    "published_at": item.published_at,
                    "summary": item.summary,
                    "author": item.author,
                })

        # 输出过滤统计
        if filtered_count > 0:
            print(f"[RSS] 新鲜度过滤：跳过 {filtered_count} 篇超过指定天数的旧文章（仍保留在数据库中）")
            # DEBUG 模式下显示详细信息
            if debug_mode and filtered_details:
                print(f"[RSS] 被过滤的文章详情（共 {len(filtered_details)} 篇）：")
                for detail in filtered_details[:10]:  # 最多显示 10 条
                    days_str = f"{detail['days_old']:.1f}" if detail['days_old'] else "未知"
                    print(f"  - [{days_str}天前] [{detail['feed']}] {detail['title']} (限制: {detail['max_days']}天)")
                if len(filtered_details) > 10:
                    print(f"  ... 还有 {len(filtered_details) - 10} 篇被过滤")

        return rss_items

    def _filter_rss_by_keywords(self, rss_items: List[Dict]) -> List[Dict]:
        """使用关键词文件过滤 RSS 条目"""
        try:
            word_groups, filter_words, global_filters = self.ctx.load_frequency_words(self.frequency_file)
            if word_groups or filter_words or global_filters:
                from trendradar.core.frequency import matches_word_groups
                filtered_items = []
                for item in rss_items:
                    title = item.get("title", "")
                    if matches_word_groups(title, word_groups, filter_words, global_filters):
                        filtered_items.append(item)

                original_count = len(rss_items)
                rss_items = filtered_items
                print(f"[RSS] 关键词过滤后剩余 {len(rss_items)}/{original_count} 条")

                if not rss_items:
                    print("[RSS] 关键词过滤后没有匹配内容")
                    return []
        except FileNotFoundError:
            # 关键词文件不存在时跳过过滤
            pass
        return rss_items

    def _execute_mode_strategy(
        self, run_plan: "RunPlan", results: Dict, id_to_name: Dict, failed_ids: List,
        rss_items: Optional[List[Dict]] = None,
        rss_new_items: Optional[List[Dict]] = None,
        raw_rss_items: Optional[List[Dict]] = None,
        rss_new_urls: Optional[set] = None,
    ) -> Optional[str]:
        """执行模式特定逻辑，支持热榜+RSS artifact 生成

        简化后的逻辑：
        - 每次运行都生成 HTML 报告（时间戳快照 + latest/{mode}.html + index.html）
        """
        # 暴露原始全量 RSS 给 CR 跨证据准入(_run_analysis_pipeline 读取)。
        self._cr_raw_rss_items = raw_rss_items

        schedule = run_plan

        current_platform_ids = self.ctx.platform_ids
        self._cr_historical_data_reused = self._cr_rss_historical_data_reused

        from trendradar.application.analysis_input import (
            AnalysisInputBuilder,
            AnalysisInputUnavailable,
        )

        builder = AnalysisInputBuilder(
            load_history=lambda: self._load_history_input(),
            prepare_current_title_info=self._prepare_current_title_info,
            detect_new_titles=lambda: self.ctx.detect_new_titles(
                current_platform_ids
            ),
            load_frequency_words=lambda: self.ctx.load_frequency_words(
                run_plan.frequency_file
            ),
            format_time=self.ctx.format_time,
        )
        try:
            request = builder.build(
                plan=run_plan,
                results=results,
                id_to_name=id_to_name,
                failed_ids=failed_ids,
                rss_items=rss_items,
                rss_new_items=rss_new_items,
                rss_new_urls=rss_new_urls,
            )
        except AnalysisInputUnavailable as exc:
            print("[失败] 严重错误：无法读取刚保存的数据文件")
            raise RuntimeError("数据一致性检查失败：保存后立即读取失败") from exc

        self._cr_historical_data_reused = (
            request.historical_data_reused
            or self._cr_rss_historical_data_reused
        )
        if run_plan.report_mode == "current" and request.historical_data_reused:
            print(
                "current模式：使用过滤后的历史数据，包含平台："
                f"{list(request.results.keys())}"
            )

        outcome = self._run_analysis_pipeline(
            request,
            schedule,
        )
        html_file = outcome.html_file

        if html_file:
            print(f"HTML报告已生成: {html_file}")
            print(f"最新报告已更新: output/html/latest/{self.report_mode}.html")

        # 打开浏览器（仅在非容器环境）
        if self._should_open_browser() and html_file:
            file_url = "file://" + str(Path(html_file).resolve())
            print(f"正在打开HTML报告: {file_url}")
            webbrowser.open(file_url)
        elif self.is_docker_container and html_file:
            print(f"HTML报告已生成（Docker环境）: {html_file}")

        return html_file

    def run(self) -> None:
        """Compatibility façade over the application run coordinator."""
        from trendradar.application.coordinator import RunCoordinator

        RunCoordinator(self).run()


def main() -> int:
    """Assemble the CLI shell from concrete application dependencies."""
    from trendradar.application.cli import CLIApplication
    from trendradar.application.diagnostics import (
        run_doctor,
        show_schedule,
    )

    return CLIApplication(
        load_config=load_config,
        analyzer_factory=NewsAnalyzer,
        check_versions=check_all_versions,
        run_doctor=run_doctor,
        show_schedule=show_schedule,
        version=__version__,
    ).run()


if __name__ == "__main__":
    raise SystemExit(main())
