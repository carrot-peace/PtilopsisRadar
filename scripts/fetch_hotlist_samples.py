#!/usr/bin/env python3
# coding=utf-8
"""
只读热榜抓取工具（用于关键词配置的真实数据 dry-run）

从 newsnow 公共 API 抓取当前各平台热榜标题，落成样本文件，供 scripts/keyword_dryrun.py
做命中分布 / 吞噬检测对比。

只读保证：
    - 仅抓取（GET 公共 API），不写真实库 output/news、不调 AI、不发 Telegram、不推送。
    - 产物隔离在 output/dryrun/ 下，不影响正式管道状态。

复用：
    按文件路径加载 trendradar/crawler/fetcher.py 的 DataFetcher（绕开 trendradar 包重依赖），
    其 crawl_websites() 已带重试 / 域名安全校验 / rank 提取。

用法：
    python3 scripts/fetch_hotlist_samples.py
    python3 scripts/fetch_hotlist_samples.py --platforms weibo,douyin,toutiao
    python3 scripts/fetch_hotlist_samples.py --config config/config.yaml --api-url https://your/api/s

产物：
    output/dryrun/<date>_samples.txt   每行一个标题（跨平台去重）
    output/dryrun/<date>_samples.db    news_items(title, platform_id, rank)，供 --sqlite 取 rank
"""

import argparse
import datetime
import importlib.util
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FETCHER_PATH = REPO_ROOT / "trendradar" / "crawler" / "fetcher.py"


def _load_fetcher():
    """按路径加载 fetcher 模块（只依赖 requests/stdlib，不触发 trendradar 包 __init__）。"""
    spec = importlib.util.spec_from_file_location("tr_fetcher_dryrun", str(FETCHER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_platforms(config_path):
    """读取 config.yaml 的 platforms.sources。

    优先用 PyYAML；不可用时退化为对 `sources:` 块的极简行扫描。
    返回 [(id, name, expected_domain), ...] 与 api_url（可能为空字符串）。
    """
    text = Path(config_path).read_text(encoding="utf-8")

    # 优先 YAML
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        plat = (data or {}).get("platforms", {}) or {}
        api_url = (plat.get("api_url") or "").strip()
        out = []
        for s in plat.get("sources", []) or []:
            if not s.get("enabled", True):
                continue
            sid = s.get("id")
            if sid:
                out.append((sid, s.get("name", sid), s.get("expected_domain", "")))
        return out, api_url
    except ImportError:
        pass

    # 回退：仅扫描顶层 platforms: 块，避免误抓 rss 等其它 sources。
    # 支持 platforms 是最后一个顶层键；找不到时快速失败，不扫描整份配置。
    m_block = re.search(r"^platforms:\s*\n(.*?)(?=^\S|\Z)", text, re.S | re.M)
    if not m_block:
        raise ValueError("未找到顶层 platforms: 配置块，无法用正则回退解析平台 sources")
    block = m_block.group(1)

    api_url = ""
    m_api = re.search(r"^\s*api_url:\s*[\"']?([^\"'\n]*)[\"']?", block, re.M)
    if m_api:
        api_url = m_api.group(1).strip()

    out = []
    # 以 "- id:" 为单位切分每个 source
    for chunk in re.split(r"\n\s*-\s+id:", block)[1:]:
        sid = chunk.split("\n", 1)[0].strip().strip('"').strip("'")
        name_m = re.search(r"name:\s*\"?([^\"\n]+)\"?", chunk)
        dom_m = re.search(r"expected_domain:\s*\"?([^\"\n]+)\"?", chunk)
        enabled_m = re.search(r"enabled:\s*(false|true)", chunk)
        if enabled_m and enabled_m.group(1) == "false":
            continue
        if sid:
            out.append(
                (
                    sid,
                    (name_m.group(1).strip() if name_m else sid),
                    (dom_m.group(1).strip() if dom_m else ""),
                )
            )
    return out, api_url


def main():
    p = argparse.ArgumentParser(description="只读抓取公共热榜样本（用于 keyword dry-run）")
    p.add_argument("--config", default="config/config.yaml", help="config.yaml 路径")
    p.add_argument("--platforms", help="逗号分隔的平台 id，覆盖 config（如 weibo,douyin）")
    p.add_argument("--api-url", help="覆盖 newsnow API 基础地址")
    p.add_argument("--interval", type=int, default=300, help="平台间请求间隔毫秒（默认 300）")
    p.add_argument("--out-dir", default="output/dryrun", help="产物目录")
    args = p.parse_args()

    fetcher_mod = _load_fetcher()

    # 平台与 api_url
    cfg_api_url = ""
    domain_rules = {}
    if args.platforms:
        ids = [(s.strip(), s.strip(), "") for s in args.platforms.split(",") if s.strip()]
    else:
        if not Path(args.config).exists():
            p.error(f"找不到配置文件 {args.config}，或用 --platforms 指定平台")
        ids, cfg_api_url = _load_platforms(args.config)
        if not ids:
            p.error("未从 config 解析到任何 platforms.sources，可用 --platforms 指定")

    api_url = args.api_url or cfg_api_url or None
    ids_list = [(sid, name) for sid, name, _dom in ids]
    domain_rules = {sid: dom for sid, _name, dom in ids if dom}

    print(f"将抓取 {len(ids_list)} 个平台：{', '.join(sid for sid, _ in ids_list)}")
    print(f"API: {api_url or fetcher_mod.DataFetcher.DEFAULT_API_URL}")

    fetcher = fetcher_mod.DataFetcher(api_url=api_url)
    results, id_to_name, failed_ids = fetcher.crawl_websites(
        ids_list, request_interval=args.interval, domain_rules=domain_rules
    )

    if failed_ids:
        print(f"⚠️ 失败/丢弃的平台：{', '.join(failed_ids)}")

    # 汇总：标题去重（保留最优 rank）；同时保留每平台 (title, rank) 入库
    title_best_rank = {}
    rows = []  # (title, platform_id, rank)
    for sid, titles in results.items():
        for title, td in titles.items():
            ranks = td.get("ranks") or [99]
            r = min(ranks)
            rows.append((title, sid, r))
            if title not in title_best_rank or r < title_best_rank[title]:
                title_best_rank[title] = r

    if not rows:
        print("没有抓到任何标题（可能是网络不可达或 API 变更）。")
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    txt_path = out_dir / f"{date}_samples.txt"
    db_path = out_dir / f"{date}_samples.db"

    # samples.txt：按最优 rank 排序，便于人工浏览
    with open(txt_path, "w", encoding="utf-8") as f:
        for title, _r in sorted(title_best_rank.items(), key=lambda x: x[1]):
            f.write(title + "\n")

    # 最小 sqlite：news_items(title, platform_id, rank)，与 keyword_dryrun --sqlite 兼容
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE news_items (title TEXT NOT NULL, platform_id TEXT, rank INTEGER NOT NULL)"
        )
        conn.executemany("INSERT INTO news_items (title, platform_id, rank) VALUES (?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()

    print(f"成功平台 {len(results)} / 失败 {len(failed_ids)}；"
          f"去重标题 {len(title_best_rank)} 条，入库行 {len(rows)} 条")
    print(f"产物：\n  {txt_path}\n  {db_path}")
    print("\n下一步 dry-run：")
    print(f"  python3 scripts/keyword_dryrun.py --config config/frequency_words.txt --sqlite {db_path}")


if __name__ == "__main__":
    main()
