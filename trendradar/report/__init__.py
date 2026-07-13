# coding=utf-8
"""
报告生成模块

提供现行报告的数据准备、HTML 生成与盘面渲染功能。

模块结构：
- generator: 报告生成器
- newsletter: current/incremental 完整报告渲染器
- dashboard: 轻量当前盘面与发布摘要
- daily_v2: daily artifact 模型与渲染器
"""

from trendradar.report.generator import (
    prepare_report_data,
    generate_html_report,
)
from trendradar.report.dashboard import (
    render_current_dashboard_html,
    build_dashboard_state,
    write_dashboard,
)
from trendradar.report.daily_v2 import (
    DailyReportV2,
    build_daily_report_v2,
    render_daily_report_v2,
)

__all__ = [
    # 报告生成器
    "prepare_report_data",
    "generate_html_report",
    # Current Dashboard
    "render_current_dashboard_html",
    "build_dashboard_state",
    "write_dashboard",
    # Daily Report v2 (artifact-only)
    "DailyReportV2",
    "build_daily_report_v2",
    "render_daily_report_v2",
]
