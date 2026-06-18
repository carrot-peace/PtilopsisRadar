# coding=utf-8
"""
Ptilopsis Radar - 热点新闻聚合与分析工具

使用方式:
  python -m trendradar        # 模块执行
  trendradar                  # 安装后执行
"""

__version__ = "0.1.0"
__all__ = ["AppContext", "__version__"]


def __getattr__(name):
    # 惰性导出 AppContext：避免在 import 任意 trendradar.* 子模块时，
    # 因 package init 提前拉起 trendradar.context 及其依赖。
    if name == "AppContext":
        from trendradar.context import AppContext

        return AppContext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
