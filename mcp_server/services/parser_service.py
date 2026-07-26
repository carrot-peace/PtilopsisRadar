"""
数据解析服务

v2.0.0: 仅支持 SQLite 数据库，移除 TXT 文件支持
新存储结构：output/{type}/{date}.db
"""

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

import yaml

from trendradar.storage.query import SQLiteQueryRepository

from ..utils.errors import FileParseError, DataNotFoundError
from .cache_service import get_cache


class ParserService:
    """数据解析服务类"""

    def __init__(self, project_root: str = None, query_repository=None):
        """
        初始化解析服务

        Args:
            project_root: 项目根目录，默认为当前目录的父目录
        """
        if project_root is None:
            current_file = Path(__file__)
            self.project_root = current_file.parent.parent.parent.resolve()
        else:
            self.project_root = Path(project_root).expanduser().resolve()

        self.cache = get_cache()
        self._cache_namespace = hashlib.sha256(
            str(self.project_root).encode("utf-8")
        ).hexdigest()[:16]
        self.query_repository = query_repository or SQLiteQueryRepository(
            self.project_root / "output"
        )

        # frequency_words.txt mtime 缓存
        self._freq_words_cache: Optional[List[Dict]] = None
        self._freq_words_mtime: float = 0.0

    @staticmethod
    def clean_title(title: str) -> str:
        """清理标题文本"""
        title = re.sub(r'\s+', ' ', title)
        title = title.strip()
        return title

    def get_date_folder_name(self, date: datetime = None) -> str:
        """
        获取日期字符串（ISO 格式）

        Args:
            date: 日期对象，默认为今天

        Returns:
            日期字符串（YYYY-MM-DD）
        """
        if date is None:
            date = datetime.now()
        return date.strftime("%Y-%m-%d")

    def cache_key(self, key: str) -> str:
        """Scope a shared-cache key to this project root."""
        return f"project:{self._cache_namespace}:{key}"

    def _get_db_path(
        self,
        date: datetime = None,
        db_type: str = "news",
    ) -> Optional[Path]:
        """
        获取数据库文件路径

        新结构：output/{type}/{date}.db

        Args:
            date: 日期对象，默认为今天
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            数据库文件路径，如果不存在则返回 None
        """
        date_str = self.get_date_folder_name(date)
        return self.query_repository.database_path(date_str, db_type)

    def _read_from_sqlite(
        self,
        date: datetime = None,
        platform_ids: Optional[List[str]] = None,
        db_type: str = "news",
    ) -> Optional[Tuple[Dict, Dict, Dict]]:
        """Delegate snapshot reads to the shared storage query repository."""
        return self.query_repository.read_snapshot(
            self.get_date_folder_name(date),
            source_ids=platform_ids,
            db_type=db_type,
        )

    def read_all_titles_for_date(
        self,
        date: datetime = None,
        platform_ids: Optional[List[str]] = None,
        db_type: str = "news"
    ) -> Tuple[Dict, Dict, Dict]:
        """
        读取指定日期的所有数据（带缓存）

        Args:
            date: 日期对象，默认为今天
            platform_ids: 平台/Feed ID列表，None表示所有
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            (all_titles, id_to_name, all_timestamps) 元组

        Raises:
            DataNotFoundError: 数据不存在
        """
        date_str = self.get_date_folder_name(date)
        platform_key = ','.join(sorted(platform_ids)) if platform_ids else 'all'
        cache_key = self.cache_key(
            f"read_all:{db_type}:{date_str}:{platform_key}"
        )

        is_today = (date is None) or (date.date() == datetime.now().date())
        ttl = 900 if is_today else 900

        cached = self.cache.get(cache_key, ttl=ttl)
        if cached:
            return cached

        result = self._read_from_sqlite(date, platform_ids, db_type)
        if result:
            self.cache.set(cache_key, result)
            return result

        raise DataNotFoundError(
            f"未找到 {date_str} 的 {db_type} 数据",
            suggestion="请先运行爬虫或检查日期是否正确"
        )

    def parse_yaml_config(self, config_path: str = None) -> dict:
        """
        解析YAML配置文件

        Args:
            config_path: 配置文件路径，默认为 config/config.yaml

        Returns:
            配置字典

        Raises:
            FileParseError: 配置文件解析错误
        """
        if config_path is None:
            config_path = self.project_root / "config" / "config.yaml"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            raise FileParseError(str(config_path), "配置文件不存在")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            return config_data
        except Exception as e:
            raise FileParseError(str(config_path), str(e))

    def parse_frequency_words(self, words_file: str = None) -> List[Dict]:
        """
        解析关键词配置文件（带 mtime 缓存）

        仅当 frequency_words.txt 被修改时才重新解析，避免循环内重复 IO。

        复用 trendradar.core.frequency 的解析逻辑，支持：
        - # 开头的注释行
        - 空行分隔词组
        - [组别名] 作为词组第一行，给整组指定别名
        - +前缀必须词、!前缀过滤词、@数量限制
        - /pattern/ 正则表达式语法
        - => 别名 显示名称语法
        - [GLOBAL_FILTER] 全局过滤区域

        显示名称优先级：组别名 > 行别名拼接 > 关键词拼接

        Args:
            words_file: 关键词文件路径，默认为 config/frequency_words.txt

        Returns:
            词组列表

        Raises:
            FileParseError: 文件解析错误
        """
        import os
        from trendradar.core.frequency import load_frequency_words

        if words_file is None:
            words_file = str(
                self.project_root / "config" / "frequency_words.txt"
            )
        else:
            words_file = str(words_file)

        try:
            current_mtime = os.path.getmtime(words_file)

            if (
                self._freq_words_cache is not None
                and current_mtime == self._freq_words_mtime
            ):
                return self._freq_words_cache

            word_groups, filter_words, global_filters = load_frequency_words(
                words_file
            )
            self._freq_words_cache = word_groups
            self._freq_words_mtime = current_mtime
            return word_groups
        except FileNotFoundError:
            return []
        except Exception as e:
            raise FileParseError(words_file, str(e))

    def get_available_dates(self, db_type: str = "news") -> List[str]:
        """
        获取可用的日期列表

        Args:
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            日期字符串列表（YYYY-MM-DD 格式，降序排列）
        """
        return self.query_repository.available_dates(db_type)

    def get_available_date_range(
        self,
        db_type: str = "news",
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        获取可用的日期范围

        Args:
            db_type: 数据库类型 ("news" 或 "rss")

        Returns:
            (最早日期, 最新日期) 元组，如果没有数据则返回 (None, None)
        """
        dates = self.get_available_dates(db_type)
        if not dates:
            return (None, None)

        earliest = datetime.strptime(dates[-1], "%Y-%m-%d")
        latest = datetime.strptime(dates[0], "%Y-%m-%d")
        return (earliest, latest)
