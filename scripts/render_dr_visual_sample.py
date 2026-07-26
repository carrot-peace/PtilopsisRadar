#!/usr/bin/env python3
"""Generate the reproducible DR newsletter visual fixture.

Outputs are deterministic and require no network or model call:

* output/samples/dr-v2-2026-07-13-sample.html (responsive desktop artifact)
* output/samples/dr-v2-2026-07-13-mobile.html (390px QA frame)
* output/samples/dr-v2-2026-07-13-telegram.txt (Telegram skim layer)

The lightweight test bootstrap is used intentionally so the fixture can be
regenerated on a workstation without importing the optional AI runtime.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import _bootstrap  # noqa: E402


_bootstrap.load_all()
_bootstrap._ensure_pkg("trendradar.report")
_bootstrap._ensure_pkg("trendradar.dr")
daily_v2 = _bootstrap._load_file(
    "trendradar.report.daily_v2", "trendradar/report/daily_v2.py"
)
dr_formatter = _bootstrap._load_file(
    "trendradar.dr.formatter", "trendradar/dr/formatter.py"
)


FIXED_TIME = datetime(2026, 7, 13, 20, 3, 35)
SAMPLE_STEM = "dr-v2-2026-07-13"


def source(
    title: str,
    name: str,
    url: str,
    rank: int,
    tier: str = "D",
) -> dict[str, Any]:
    return {
        "title": title,
        "source": name,
        "tier": tier,
        "trend": "稳定",
        "url": url,
        "rank": rank,
        "time": "2026-07-13",
    }


def event(
    title: str,
    summary: str,
    analysis: str,
    *,
    layers: str,
    sources: list[dict[str, Any]],
    heat: str,
    status: str,
    boundary: str,
) -> dict[str, Any]:
    tiers = [part for part in layers.split("/") if part]
    source_names = {item["source"] for item in sources}
    by_tier = {
        tier: sorted({item["source"] for item in sources if item["tier"] == tier})
        for tier in tiers
    }
    return {
        "topic": title,
        "summary": summary,
        "analysis": analysis,
        "source_layers": layers,
        "platforms": "、".join(sorted(source_names)),
        "platform_count": len(source_names),
        "highest_heat": heat,
        "verification_status": status,
        "factual_boundary": boundary,
        "sentiment_flag": False,
        "evidence_detail": {
            "topic_group": title,
            "source_tiers_present": tiers,
            "sources_by_tier": by_tier,
            "d_tier_platform_count": len(by_tier.get("D", [])),
            "platform_count": len(source_names),
            "sample_titles": sources[:3],
            "source_links": sources[:5],
        },
    }


def build_fixture() -> tuple[SimpleNamespace, dict[str, Any]]:
    found = source(
        "海南陵水14岁失联女生已顺利找到",
        "今日头条",
        "https://www.toutiao.com/trending/7660841633700675647/",
        1,
    )
    flood_a = source(
        "河北宽城多个小区被淹 无失联人员",
        "今日头条",
        "https://www.toutiao.com/trending/7661880097988677170/",
        2,
    )
    flood_b = source(
        "河北宽城多地交通中断 村民出行受阻",
        "今日头条",
        "https://www.toutiao.com/trending/7661815107093007891/",
        3,
    )
    market = source(
        "三大指数均跌超2%，全市场逾170股跌停",
        "财联社热门",
        "https://www.cls.cn/detail/2424589",
        2,
        "C",
    )
    response = source(
        "A股存储一哥回应跌停",
        "微博",
        "https://s.weibo.com/weibo?q=%23A%E8%82%A1%E5%AD%98%E5%82%A8%E4%B8%80%E5%93%A5%23",
        3,
    )

    items = [
        event(
            "海南陵水14岁失联女生已找到",
            "今日头条热榜出现“海南陵水14岁失联女生已顺利找到”的标题。当前采集结果能够确认的是寻人事件出现了“已找到”的公开进展，以及该进展进入平台热榜；现有证据未包含寻回时间、地点和后续处置细节，因此摘要不作额外补写。",
            "目前只绑定今日头条一条传播文本，属于单个平台的进展信号。",
            layers="D",
            sources=[found],
            heat="今日头条 第1名",
            status="高热待核实",
            boundary="当前只能确认相关标题进入平台热榜，不能据此补充标题之外的事实。",
        ),
        event(
            "河北宽城多处被淹，交通出行受阻",
            "今日头条两条热榜标题均指向河北宽城洪涝：一条提到多个小区被淹，并称暂未发现失联人员；另一条提到多地交通中断、村民出行受阻。两条内容描述的是同一地区洪涝造成的不同影响，当前未采集到更完整的灾情通报和处置时间线。",
            "两条证据来自同一平台，可相互补充事件影响，但不构成跨平台核验。",
            layers="D",
            sources=[flood_a, flood_b],
            heat="今日头条 第2名",
            status="高热待核实",
            boundary="现阶段可确认传播内容及其平台位置，具体灾情仍以当地正式通报为准。",
        ),
        event(
            "A股三大指数跌逾2%，逾170股跌停",
            "财联社每日收评标题显示，A股三大指数当日均跌逾2%，全市场超过170只个股跌停，中药、银行等防御板块逆势走强。这里仅复述已采集收评中的指数、跌停数量和板块表现，不把同期出现的其他市场标题拼接为下跌原因。",
            "该事件目前绑定一条专业财经来源，尚缺少其他来源层级的补充。",
            layers="C",
            sources=[market],
            heat="财联社热门 第2名",
            status="中文专业来源",
            boundary="行情数字来自已采集的专业财经标题，原因判断不在现有证据范围内。",
        ),
        event(
            "A股存储公司回应跌停话题进入微博",
            "微博出现“A股存储一哥回应跌停”的热榜标题，但当前采集证据没有给出公司名称、回应原文或跌停原因。因此这里只能确认相关话题进入微博传播，不能从简短标题反推公司表态和市场波动之间的因果关系。",
            "目前仅见微博单点热榜传播，缺少专业来源正文支撑。",
            layers="D",
            sources=[response],
            heat="微博 第3名",
            status="高热待核实",
            boundary="只能确认标题传播，标题中的具体回应内容仍待来源补充。",
        ),
    ]

    noise_titles = ["BLG冠军梦碎", "HLE战胜BLG赛后数据", "MSI淘汰赛焦点战"]
    noise = [
        event(
            title,
            "",
            "",
            layers="D",
            sources=[source(title, "微博", "https://s.weibo.com/", index + 5)],
            heat=f"微博 第{index + 5}名",
            status="高热待核实",
            boundary="只能确认标题传播。",
        )
        for index, title in enumerate(noise_titles)
    ]

    ai = SimpleNamespace(
        success=True,
        report_style="environment",
        overview=(
            "今天进入正文的信号主要来自中文平台：海南失联女生寻回、河北宽城洪涝"
            "和A股市场波动分别进入热榜。它们是彼此独立的事件，摘要按各自证据范围"
            "呈现，不因同属公共安全或市场议题而合并。"
        ),
        overview_stats={
            "label_counts": {
                "cross_layer_verified": 0,
                "high_heat_unverified": 6,
                "sentiment_heavy": 0,
                "silence_gap": 0,
                "chinese_only_hot": 1,
            },
            "background_count": 2,
            "layer_distribution": {"A": 0, "B": 0, "C": 1, "D": 4},
        },
        cross_layer_verified=[],
        high_heat_unverified=[items[0], items[1], items[3], *noise],
        sentiment_heavy=[],
        chinese_only_hot=[items[2]],
        silence_gap=[],
        background_notes=["国际秩序与东亚（C）", "科技产业背景（C）"],
        method_note=(
            "社交平台热度只表示传播强度，不代表事实成立；核验状态由程序根据事件绑定"
            "的来源层级和平台覆盖生成，AI 仅用于摘要与解释。"
        ),
    )
    report_data = {
        "failed_ids": ["baidu"],
        "stats": [
            {
                "word": "公共安全线索",
                "count": 3,
                "titles": [
                    {"title": item["title"], "source_name": item["source"]}
                    for item in (found, flood_a, flood_b)
                ],
            },
            {
                "word": "市场波动",
                "count": 2,
                "titles": [
                    {"title": item["title"], "source_name": item["source"]}
                    for item in (market, response)
                ],
            },
        ],
    }
    return ai, report_data


def render(output_dir: Path) -> list[Path]:
    ai, report_data = build_fixture()
    output_dir.mkdir(parents=True, exist_ok=True)
    desktop = output_dir / f"{SAMPLE_STEM}-sample.html"
    mobile = output_dir / f"{SAMPLE_STEM}-mobile.html"
    telegram = output_dir / f"{SAMPLE_STEM}-telegram.txt"

    html = daily_v2.render_daily_report_v2(
        report_data,
        mode="daily",
        ai_analysis=ai,
        get_time_func=lambda: FIXED_TIME,
    )
    desktop.write_text(html, encoding="utf-8")
    mobile.write_text(
        """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DR mobile QA</title><style>*{box-sizing:border-box}body{margin:0;background:#ececec}
.frame{width:390px;max-width:100%;height:844px;margin:20px auto;background:#fff;box-shadow:0 4px 20px #0002}
iframe{width:100%;height:100%;border:0}</style></head><body><div class="frame">
<iframe src="dr-v2-2026-07-13-sample.html" title="DR mobile preview"></iframe>
</div></body></html>""",
        encoding="utf-8",
    )
    telegram.write_text(
        dr_formatter.render_dr_telegram_text(
            ai,
            date="2026-07-13",
            now=FIXED_TIME,
        )
        + "\n",
        encoding="utf-8",
    )
    return [desktop, mobile, telegram]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "samples",
        help="directory for deterministic sample artifacts",
    )
    args = parser.parse_args()
    for path in render(args.output_dir.resolve()):
        print(path)


if __name__ == "__main__":
    main()
