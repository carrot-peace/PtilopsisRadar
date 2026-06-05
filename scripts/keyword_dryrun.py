#!/usr/bin/env python3
# coding=utf-8
"""
关键词候选配置 dry-run 工具（只读）

用途：
    在不调用 AI、不爬虫、不发 Telegram 的前提下，用一批样本标题检查某个
    frequency_words 候选配置的命中分布、过宽组、零命中组，以及“吞噬检测”
    （一个标题被靠前的宽组抢走、本应进入靠后更具体组的情况）。

只读保证：
    - 不写任何配置文件，不读现网 config/frequency_words.txt（除非显式 --config 指向它）。
    - 不联网、不调用模型、不触发推送。
    - SQLite 仅以只读方式打开。

语义对齐：
    复刻线上 count_word_frequency 的归属逻辑——
    标题先过 GLOBAL_FILTER（子串、全局），再按词组【文件顺序】找第一个命中组并 break，
    因此一个标题只归属一个组，组顺序即优先级。

用法：
    python3 scripts/keyword_dryrun.py \
        --config config/custom/keyword/v0_2_candidate.txt \
        --samples samples.txt
    python3 scripts/keyword_dryrun.py --config <cfg> --sqlite path/to/data.db
    可选：--top 10 --rank-threshold 5 --over-broad-pct 15 --csv out.csv
"""

import argparse
import importlib.util
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# ── 直接按文件路径加载 frequency.py，绕开 trendradar 包的重依赖（pytz 等）──
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FREQ_PATH = _REPO_ROOT / "trendradar" / "core" / "frequency.py"


def _load_frequency_module():
    spec = importlib.util.spec_from_file_location("freq_dryrun", str(_FREQ_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


freq = _load_frequency_module()


# ── 模块归类（按显示名，用于吞噬检测的定向统计）──
# 同时收录 v0.2 候选名与信号分层候选名，使两版配置都能跑定向吞噬检测。
ECON_01 = {
    # v0.2
    "就业与收入压力", "房地产与居住压力", "地方财政与公共服务收缩",
    "消费降级与商业萧条", "企业经营压力外溢", "生活成本与家庭负担",
    # 信号分层版
    "经济体感与社会压力",
}
SAFETY_03 = {
    "无差别伤害与极端个体暴力", "公共场所与校园安全", "重大事故与设施异常",
    "公共安全官方通报话术", "官方通报与现场传播",
    "公共安全与社会失序",
}
AI_05 = {
    "前沿模型与产品发布", "Coding Agent 与开发工具", "AI API 价格限额与服务状态",
    "开源模型与本地部署", "AI 安全监管与平台规则",
    "AI 社会与治理异常", "AI 工具与访问后勤",
}
CONSUMER_08 = {
    "食品与商品安全争议", "消费维权与售后争议",
    "预付费会员卡与商家跑路", "平台责任与电商外卖争议",
    "消费权益与食品商品安全",
}
SHANGHAI_09 = {
    "上海通勤中断与交通异常", "上海极端天气与城市运行风险",
    "校园周边与生活半径突发事件", "上海居住安全与基础设施异常",
    "上海突发与应急", "上海本地兜底",
}
# 需重点观察是否过宽的组（两版合并）
WATCH_GROUPS = {
    "平台内容管控", "官方通报与现场传播", "专项整治与合规要求",
    "社会热点争议", "上海本地兜底",
}


def is_background(display_name):
    return bool(display_name) and display_name.startswith("背景")


def group_label(group):
    """组的可读标识：优先 display_name，否则 group_key。"""
    return group.get("display_name") or group.get("group_key") or "<未命名>"


def group_matches(group, title_lower):
    """复刻 count_word_frequency 的单组匹配：必须词全中 + 普通词任一中。"""
    required = group.get("required") or []
    normal = group.get("normal") or []
    if required and not all(freq._word_matches(r, title_lower) for r in required):
        return False
    if normal and not any(freq._word_matches(n, title_lower) for n in normal):
        return False
    # 既无 required 也无 normal 的组在解析阶段已被丢弃，这里恒不出现
    return bool(required or normal)


def passes_global_filter(title_lower, global_filters):
    """命中任一全局过滤词 → 被过滤（返回 False 表示不通过）。"""
    for gf in global_filters or []:
        if gf.lower() in title_lower:
            return False, gf
    return True, None


# ── 样本读取 ──
def read_samples_text(path):
    """每行一个标题；忽略空行与 # 注释。rank 统一为 None。"""
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            items.append((t, None))
    return items


def read_samples_sqlite(path):
    """只读打开 SQLite，按 news_items(title, MIN(rank)) 取标题与最佳排名。"""
    titles = {}
    uri = f"file:{os.path.abspath(path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT title, MIN(rank) FROM news_items "
            "WHERE title IS NOT NULL AND title != '' GROUP BY title"
        )
        for title, best_rank in cur.fetchall():
            titles[title] = best_rank
    finally:
        conn.close()
    return [(t, r) for t, r in titles.items()]


def load_samples(args):
    items = []
    if args.samples:
        items.extend(read_samples_text(args.samples))
    if args.sqlite:
        items.extend(read_samples_sqlite(args.sqlite))
    # 去重（标题相同保留 rank 较优者）
    merged = {}
    for title, rank in items:
        if title in merged:
            old = merged[title]
            if rank is not None and (old is None or rank < old):
                merged[title] = rank
        else:
            merged[title] = rank
    return [(t, r) for t, r in merged.items()]


# ── 核心分析 ──
def analyze(samples, word_groups, filter_words, global_filters):
    ordered_labels = [group_label(g) for g in word_groups]

    counts = defaultdict(int)          # 最终归属组 → 命中数
    tops = defaultdict(list)           # 最终归属组 → [(rank, title)]
    unmatched = []                     # [(rank, title)]
    dropped_global = []                # [(title, 命中的过滤词)]
    assignments = []                   # [(title, rank, winner, [all_matched])]
    pair_swallow = defaultdict(int)    # (winner_module, swallowed_module) → 计数

    for title, rank in samples:
        title_lower = title.lower()

        ok, hit = passes_global_filter(title_lower, global_filters)
        if not ok:
            dropped_global.append((title, hit))
            continue

        # 全局过滤词（! 语法，本实现全局生效）
        if any(freq._word_matches(fw, title_lower) for fw in (filter_words or [])):
            dropped_global.append((title, "<filter_word>"))
            continue

        matched = [
            group_label(g) for g in word_groups if group_matches(g, title_lower)
        ]
        if not matched:
            unmatched.append((rank, title))
            assignments.append((title, rank, None, []))
            continue

        winner = matched[0]            # 文件顺序第一个 = 线上 break 归属
        counts[winner] += 1
        tops[winner].append((rank if rank is not None else 999, title))
        assignments.append((title, rank, winner, matched))

        # 吞噬统计：winner 之外的命中组都是“被抢走的候选”
        for other in matched[1:]:
            pair_swallow[(module_of(winner), module_of(other))] += 1

    return {
        "ordered_labels": ordered_labels,
        "counts": counts,
        "tops": tops,
        "unmatched": unmatched,
        "dropped_global": dropped_global,
        "assignments": assignments,
        "pair_swallow": pair_swallow,
    }


def module_of(label):
    if is_background(label):
        return "背景表"
    if label in ECON_01:
        return "01经济"
    if label in SAFETY_03:
        return "03公共安全"
    if label in AI_05:
        return "05 AI"
    if label in CONSUMER_08:
        return "08消费"
    if label in SHANGHAI_09:
        return "09上海"
    return "其他主表"


# ── 输出 ──
def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def report(res, word_groups, total_input, args):
    counts = res["counts"]
    tops = res["tops"]

    main_labels = [lbl for lbl in res["ordered_labels"] if not is_background(lbl)]
    bg_labels = [lbl for lbl in res["ordered_labels"] if is_background(lbl)]

    hr("0. 概览")
    print(f"输入标题数（去重后）   : {total_input}")
    print(f"被全局过滤丢弃         : {len(res['dropped_global'])}")
    matched_total = sum(counts.values())
    print(f"命中并归属某组         : {matched_total}")
    print(f"未归类（不进报告）     : {len(res['unmatched'])}")
    print(f"词组总数               : {len(word_groups)}  "
          f"(主表 {len(main_labels)} / 背景 {len(bg_labels)})")

    hr("1. 各组命中数（文件顺序）— 主追踪表")
    print_group_counts(main_labels, counts, total_input, tops, args)

    hr("2. 各组命中数（文件顺序）— 背景表")
    print_group_counts(bg_labels, counts, total_input, tops, args)
    bg_total = sum(counts.get(lbl, 0) for lbl in bg_labels)
    print(f"\n背景表命中合计: {bg_total}"
          + ("   ⚠️ 背景表占比偏高，留意是否抢主屏" if total_input and bg_total / total_input > 0.25 else ""))

    hr("3. 疑似过宽组")
    pct = args.over_broad_pct / 100.0
    flagged = False
    for lbl in res["ordered_labels"]:
        c = counts.get(lbl, 0)
        share = c / total_input if total_input else 0
        watch = lbl in WATCH_GROUPS
        if share > pct or watch:
            tag = []
            if share > pct:
                tag.append(f"占比 {share*100:.1f}% > {args.over_broad_pct}%")
            if watch:
                tag.append("【重点观察组】")
            print(f"  - {lbl}: 命中 {c}  {' '.join(tag)}")
            flagged = True
    if not flagged:
        print("  （无）")

    hr("4. 零命中组")
    zero = [lbl for lbl in res["ordered_labels"] if counts.get(lbl, 0) == 0]
    if zero:
        for lbl in zero:
            print(f"  - {lbl}")
    else:
        print("  （无）")

    hr("5. 未归类标题")
    print(f"未归类总数: {len(res['unmatched'])}")
    high = [(r, t) for r, t in res["unmatched"]
            if r is not None and r <= args.rank_threshold]
    print(f"其中“高热未归类”(min_rank <= {args.rank_threshold}): {len(high)}")
    for r, t in sorted(high, key=lambda x: x[0])[: args.top]:
        print(f"    [rank {r}] {t}")
    print(f"  -- 未归类样例（前 {args.top}）--")
    for r, t in res["unmatched"][: args.top]:
        print(f"    {t}")

    hr("6. 吞噬检测")
    print("说明：一个标题命中多个组时，线上只进【文件顺序第一个】组，"
          "其余更靠后的组被“吞掉”。")

    print("\n[6.0] 模块级吞噬概览 (winner模块 → 被吞模块: 次数)")
    if res["pair_swallow"]:
        for (w, s), n in sorted(res["pair_swallow"].items(), key=lambda x: -x[1]):
            print(f"    {w:8s} → {s:8s} : {n}")
    else:
        print("    （无多组命中）")

    print_targeted_swallow(
        res, "[6.1] 01 经济 是否吞掉 08 消费权益",
        winner_set=ECON_01, swallowed_set=CONSUMER_08, args=args)
    print_targeted_swallow(
        res, "[6.2] 03 公共安全 是否吞掉 09 上海 realtime",
        winner_set=SAFETY_03, swallowed_set=SHANGHAI_09, args=args)

    print("\n[6.3] 05 AI 命中标题（人工复核是否为泛 AI 营销）")
    ai_hits = [a for a in res["assignments"] if a[2] in AI_05]
    print(f"    05 命中合计: {len(ai_hits)}")
    for title, rank, winner, _ in ai_hits[: args.top]:
        print(f"    [{winner}] {title}")

    print("\n[6.4] 背景表是否抢到主追踪表应接住的标题")
    print("      （winner 为背景组、却同时命中某主表组；正常排序下应为 0）")
    bg_steal = [
        a for a in res["assignments"]
        if a[2] and is_background(a[2])
        and any(not is_background(m) for m in a[3][1:])
    ]
    if bg_steal:
        for title, rank, winner, matched in bg_steal[: args.top]:
            others = [m for m in matched[1:] if not is_background(m)]
            print(f"    ⚠️ [{winner}] {title}  也命中: {others}")
    else:
        print("    （0，符合预期：背景表在主表之后，抢不到主表已接走的标题）")

    if args.csv:
        write_csv(res["assignments"], args.csv)
        print(f"\n已写出归属映射 CSV: {args.csv}")


def print_group_counts(labels, counts, total_input, tops, args):
    if not labels:
        print("  （无）")
        return
    for lbl in labels:
        c = counts.get(lbl, 0)
        share = (c / total_input * 100) if total_input else 0
        print(f"\n  ▸ {lbl}: {c}  ({share:.1f}%)")
        if c:
            for rank, title in sorted(tops[lbl], key=lambda x: x[0])[: args.top]:
                rk = "-" if rank == 999 else rank
                print(f"      [rank {rk}] {title}")


def print_targeted_swallow(res, title, winner_set, swallowed_set, args):
    print(f"\n{title}")
    hits = [
        a for a in res["assignments"]
        if a[2] in winner_set and any(m in swallowed_set for m in a[3][1:])
    ]
    print(f"    命中数: {len(hits)}")
    for t, rank, winner, matched in hits[: args.top]:
        swallowed = [m for m in matched[1:] if m in swallowed_set]
        print(f"    ⚠️ [{winner}] {t}  本应也可进: {swallowed}")


def write_csv(assignments, path):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "min_rank", "winner_group", "all_matched_groups"])
        for title, rank, winner, matched in assignments:
            w.writerow([title, "" if rank is None else rank,
                        winner or "<未归类>", " | ".join(matched)])


def main():
    p = argparse.ArgumentParser(description="关键词候选配置 dry-run（只读）")
    p.add_argument("--config", required=True, help="候选配置路径")
    p.add_argument("--samples", help="样本文本，每行一个标题")
    p.add_argument("--sqlite", help="本地 SQLite（只读，读 news_items）")
    p.add_argument("--top", type=int, default=10, help="每组 Top N（默认 10）")
    p.add_argument("--rank-threshold", type=int, default=5,
                   help="高热未归类的 rank 阈值（默认 5）")
    p.add_argument("--over-broad-pct", type=float, default=15.0,
                   help="过宽组命中占比阈值百分比（默认 15）")
    p.add_argument("--csv", help="可选：写出标题→归属组 CSV")
    args = p.parse_args()

    if not args.samples and not args.sqlite:
        p.error("至少提供 --samples 或 --sqlite 之一")

    if not os.path.exists(args.config):
        p.error(f"配置文件不存在: {args.config}")

    word_groups, filter_words, global_filters = freq.load_frequency_words(args.config)
    print(f"已加载配置: {args.config}")
    print(f"  词组数: {len(word_groups)}  过滤词(!): {len(filter_words)}  "
          f"全局过滤: {len(global_filters)}")

    samples = load_samples(args)
    if not samples:
        print("没有读到任何样本标题。")
        sys.exit(1)

    res = analyze(samples, word_groups, filter_words, global_filters)
    report(res, word_groups, len(samples), args)


if __name__ == "__main__":
    main()
