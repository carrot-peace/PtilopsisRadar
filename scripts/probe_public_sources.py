#!/usr/bin/env python3
"""Probe configured public accounts without storage, AI, or notifications."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trendradar.crawler.rss import RSSFetcher


PUBLIC_TYPES = {"telegram_html", "x_public_html"}
SAFETY = re.compile(r"持刀|伤人|捅伤|刺伤|殴打|围殴|纵火|伤医|掌掴|抓咬|故意伤害|袭警|枪击|绑架")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--match-pattern", default=SAFETY.pattern,
                        help="Diagnostic topic regex; never changes runtime admission or push policy")
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10 or args.interval_seconds < 1:
        parser.error("rounds must be 1–10; interval-seconds must be >= 1")
    try:
        topic = re.compile(args.match_pattern)
    except re.error as exc:
        parser.error(f"Invalid match-pattern: {exc}")
    config = yaml.safe_load(Path(args.config).read_text())
    feeds = [dict(f) for f in config.get("rss", {}).get("feeds", [])
             if f.get("source_type") in PUBLIC_TYPES
             and (args.include_disabled or f.get("enabled", True))]
    if not feeds:
        parser.error("No matching public account sources in this config")
    enabled = [f["id"] for f in feeds if f.get("enabled", True)]
    for feed in feeds:
        feed["enabled"] = True  # In memory only; the config is never rewritten.
    fetcher = RSSFetcher.from_config({"feeds": feeds, "timeout": 20, "max_retries": 1})
    observations = []
    try:
        for round_no in range(1, args.rounds + 1):
            for feed in fetcher.feeds:
                now = datetime.now(timezone.utc)
                items, error = fetcher.fetch_feed(feed)
                times = [datetime.fromisoformat(i.published_at.replace("Z", "+00:00")) for i in items]
                fresh_count = sum(0 <= (now - t).total_seconds() <= 86400 for t in times)
                safety = [i for i in items if topic.search(i.title + " " + i.summary)]
                observations.append({
                    "round": round_no, "source": feed.id, "url": feed.url,
                    "enabled_in_config": feed.id in enabled,
                    "checked_at": now.isoformat(), "ok": error is None,
                    "error": error, "items": len(items), "fresh_24h": fresh_count,
                    "newest": max(times).isoformat() if times else None,
                    "oldest": min(times).isoformat() if times else None,
                    "topic_matches": len(safety),
                    "identities": [i.guid for i in items],
                    "sample": [asdict(i) for i in safety[:2]],
                })
                print(json.dumps({k: v for k, v in observations[-1].items()
                                  if k not in {"identities", "sample"}}, ensure_ascii=False), flush=True)
            if round_no < args.rounds:
                time.sleep(args.interval_seconds)
    finally:
        fetcher.session.close()
    report = {"schema": "public-source-probe-v1", "match_pattern": args.match_pattern,
              "observations": observations,
              "notes": "Short repeated probes establish availability only, not long-term reliability. Safety matches are discovery diagnostics, not verified events or Mainland-only classifications."}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
