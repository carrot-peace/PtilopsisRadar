"""Shared imports and news-weight policy for MCP analytics tools.

Kept separate so each analytics responsibility module remains cohesive.
"""

import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
from difflib import SequenceMatcher

import yaml

from trendradar.core.analyzer import calculate_news_weight as _calculate_news_weight

from ..utils.validators import (
    validate_platforms,
    validate_limit,
    validate_keyword,
    validate_top_n,
    validate_date_range,
    validate_threshold
)
from ..utils.errors import MCPError, InvalidParameterError, DataNotFoundError


# 权重配置 mtime 缓存（避免重复读取同一配置文件）
_weight_config_cache: Optional[Dict] = None
_weight_config_mtime: float = 0.0
_weight_config_path: Optional[str] = None

_WEIGHT_DEFAULT_CONFIG = {
    "RANK_WEIGHT": 0.6,
    "FREQUENCY_WEIGHT": 0.3,
    "HOTNESS_WEIGHT": 0.1,
}


def _get_weight_config() -> Dict:
    """
    从 config.yaml 读取权重配置（带 mtime 缓存）

    仅当配置文件被修改时才重新读取，避免循环内重复 IO。

    Returns:
        权重配置字典，包含 RANK_WEIGHT, FREQUENCY_WEIGHT, HOTNESS_WEIGHT
    """
    global _weight_config_cache, _weight_config_mtime, _weight_config_path

    try:
        # 首次调用时计算路径（之后复用）
        if _weight_config_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            _weight_config_path = os.path.normpath(
                os.path.join(current_dir, "..", "..", "config", "config.yaml")
            )

        current_mtime = os.path.getmtime(_weight_config_path)

        # 文件未修改且缓存有效，直接返回
        if _weight_config_cache is not None and current_mtime == _weight_config_mtime:
            return _weight_config_cache

        # 文件已修改或首次读取，重新解析
        with open(_weight_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            weight = config.get('advanced', {}).get('weight', {})
            _weight_config_cache = {
                "RANK_WEIGHT": weight.get('rank', 0.6),
                "FREQUENCY_WEIGHT": weight.get('frequency', 0.3),
                "HOTNESS_WEIGHT": weight.get('hotness', 0.1),
            }
            _weight_config_mtime = current_mtime
            return _weight_config_cache
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return _WEIGHT_DEFAULT_CONFIG


def calculate_news_weight(news_data: Dict, rank_threshold: int = 5) -> float:
    """
    计算新闻权重（用于排序）

    复用 trendradar.core.analyzer.calculate_news_weight 实现，
    权重配置从 config.yaml 的 advanced.weight 读取。

    Args:
        news_data: 新闻数据字典，包含 ranks 和 count 字段
        rank_threshold: 高排名阈值，默认5

    Returns:
        权重分数（0-100之间的浮点数）
    """
    return _calculate_news_weight(news_data, rank_threshold, _get_weight_config())
