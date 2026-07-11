#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_THREAD_IDS = set()


@dataclass(frozen=True)
class MiningConfig:
    home: Path
    output: Path
    report: Path
    sample_list: Path
    all_list: Path
    final_body: Path
    current_thread_ids: set[str]
    cutoff: float | None
    cutoff_label: str | None
    public_labels: dict[Path, str]

    @property
    def main_sources(self):
        return [
            ("Claude Code", self.home / ".claude" / "projects", "*.jsonl"),
            ("Codex active", self.home / ".codex" / "sessions", "*.jsonl"),
            ("Codex archived", self.home / ".codex" / "archived_sessions", "*.jsonl"),
        ]

PATTERNS = {
    "correction": [
        "no, I meant", "that's not what", "again", "stop", "wrong", "not what I asked",
        "不是", "不对", "错", "重新", "再来", "别", "不要", "停", "你误解", "我说的是",
    ],
    "frustration": [
        "frustrat", "annoy", "waste", "stuck", "broken", "failed", "fail",
        "烦", "崩", "卡", "浪费", "失败", "坏了", "受不了", "怎么又",
    ],
    "delegate": [
        "automate", "automation", "script", "agent", "subagent", "workflow", "command",
        "自动", "脚本", "代理", "工作流", "命令", "批量",
    ],
    "deliberation": [
        "plan", "think", "analyze", "compare", "research", "investigate", "review",
        "计划", "分析", "研究", "比较", "调研", "评估", "复盘",
    ],
    "execution": [
        "just do it", "implement", "fix", "ship", "run", "commit", "push", "merge",
        "直接做", "实现", "修", "跑", "提交", "推送", "合并", "发布",
    ],
    "config": [
        "AGENTS.md", "CLAUDE.md", "config.toml", "skill", "plugin", "mcp",
        "配置", "技能", "插件",
    ],
}

SENSITIVE_RE = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(api[_-]?key|token|secret|password|passwd|Authorization)\s*[:=]\s*['\"]?[^'\"\s,}]+", re.I),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"https?://\S+"),
    re.compile(r"/Users/[^\s\"']+"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])"),
    re.compile(r"\b\d{8,}\b"),
]

PROJECT_HINT_RE = re.compile(
    r"(PtilopsisRadar|Codex|Claude|MCP|plugin|skill|AGENTS|CLAUDE|roadmap|mirror)",
    re.I,
)


def build_config(args):
    output_dir = args.output_dir.resolve()
    thread_ids = set(args.exclude_thread_id or DEFAULT_THREAD_IDS)
    return MiningConfig(
        home=args.home.resolve(),
        output=output_dir / "evidence.md",
        report=output_dir / "analysis" / "session_mining" / "phase2_report.json",
        sample_list=output_dir / "analysis" / "session_mining" / "sample_files.txt",
        all_list=output_dir / "analysis" / "session_mining" / "candidate_files.txt",
        final_body=output_dir / "analysis" / "session_mining" / "evidence_final_body.md",
        current_thread_ids=thread_ids,
        cutoff=parse_cutoff(args.cutoff),
        cutoff_label=args.cutoff,
        public_labels={},
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Mine Phase 2 session evidence artifacts.")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    parser.add_argument("--exclude-thread-id", action="append")
    parser.add_argument(
        "--cutoff",
        help="Include only files modified at or before this timezone-aware ISO-8601 timestamp.",
    )
    return parser.parse_args()


def parse_cutoff(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--cutoff must include a timezone offset or Z")
    return parsed.timestamp()


def iter_files(config):
    for tool, base, glob in config.main_sources:
        if base.exists():
            for p in base.rglob(glob):
                if p.is_file():
                    if any(thread_id in p.name for thread_id in config.current_thread_ids):
                        continue
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    if config.cutoff is not None and st.st_mtime > config.cutoff:
                        continue
                    yield {
                        "tool": tool,
                        "path": p,
                        "mtime": st.st_mtime,
                        "size": st.st_size,
                    }


def dt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def public_label(p: Path, config):
    if p in config.public_labels:
        return config.public_labels[p]
    if p == config.all_list:
        return "candidate manifest"
    try:
        p.relative_to(config.home)
    except ValueError:
        return "generated artifact"
    return "local source [redacted]"


def assign_public_labels(files, config):
    for index, item in enumerate(files, start=1):
        config.public_labels[item["path"]] = f"candidate-{index:04d}"


def manifest_text(files, config):
    return "\n".join(
        f"{public_label(item['path'], config)} | {dt(item['mtime'])} | {item['tool']} | {item['size']} bytes"
        for item in files
    ) + ("\n" if files else "")


def select_samples(files):
    ordered = sorted(files, key=lambda x: (x["mtime"], str(x["path"])))
    n = len(ordered)
    chosen_idx = set()
    for i in range(min(10, n)):
        chosen_idx.add(i)
    for i in range(max(0, n - 15), n):
        chosen_idx.add(i)
    if n:
        start = 10
        end = max(start, n - 15)
        span = max(0, end - start)
        if span:
            for k in range(20):
                idx = start + int(round((span - 1) * k / 19))
                chosen_idx.add(idx)
    chosen = [ordered[i] for i in sorted(chosen_idx)]
    return chosen[:45]


def sanitize(text):
    if not text:
        return ""
    s = " ".join(str(text).replace("\n", " ").split())
    for rx in SENSITIVE_RE:
        s = rx.sub("[redacted]", s)
    s = re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "[name]", s)
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    if len(s) > 180:
        s = s[:177].rstrip() + "..."
    return s


def extract_strings(obj, limit=12):
    out = []

    def walk(x):
        if len(out) >= limit:
            return
        if isinstance(x, str):
            if len(x.strip()) >= 2:
                out.append(x)
        elif isinstance(x, list):
            for item in x:
                walk(item)
                if len(out) >= limit:
                    break
        elif isinstance(x, dict):
            preferred = [
                "content", "text", "message", "prompt", "cwd", "command", "summary",
                "title", "role", "type", "timestamp", "created_at",
            ]
            for key in preferred:
                if key in x:
                    walk(x[key])
                    if len(out) >= limit:
                        return
            for val in x.values():
                walk(val)
                if len(out) >= limit:
                    return

    walk(obj)
    return out


def classify_role(obj):
    if not isinstance(obj, dict):
        return "unknown"
    payload = obj.get("payload")
    if isinstance(payload, dict):
        payload_role = payload.get("role") or payload.get("type") or payload.get("item_type") or ""
        if isinstance(payload_role, str):
            pr = payload_role.lower()
            if pr in {"user", "user_message"} or "user" in pr:
                return "user"
            if pr in {"assistant", "agent_message"} or "assistant" in pr or "agent" in pr:
                return "assistant"
            if "function_call" in pr or "tool" in pr or "command" in pr:
                return "tool"
            if "developer" in pr or "system" in pr:
                return "system"
    role = obj.get("role") or obj.get("type") or ""
    if isinstance(role, str):
        r = role.lower()
        if "user" in r or r == "human":
            return "user"
        if "assistant" in r or "agent" in r:
            return "assistant"
        if "tool" in r or "command" in r:
            return "tool"
    msg = obj.get("message")
    if isinstance(msg, dict):
        return classify_role(msg)
    return "unknown"


def record_role_and_strings(obj):
    role = classify_role(obj)
    if not isinstance(obj, dict):
        return role, extract_strings(obj)
    payload = obj.get("payload")
    if isinstance(payload, dict):
        if role in {"system", "tool"}:
            return role, []
        fields = []
        for key in ("content", "message", "text", "summary", "arguments"):
            if key in payload:
                fields.extend(extract_strings(payload[key], limit=20))
        if fields:
            return role, fields
        return role, extract_strings(payload, limit=20)
    msg = obj.get("message")
    if isinstance(msg, dict):
        if role in {"system", "tool"}:
            return role, []
        fields = []
        for key in ("content", "text", "message"):
            if key in msg:
                fields.extend(extract_strings(msg[key], limit=20))
        if fields:
            return role, fields
    if role in {"system", "tool"}:
        return role, []
    return role, extract_strings(obj, limit=20)


def parse_ts_from_obj(obj, fallback_mtime):
    candidates = []

    def walk(x):
        if isinstance(x, dict):
            for key in ("timestamp", "created_at", "createdAt", "time", "date"):
                val = x.get(key)
                if isinstance(val, str):
                    candidates.append(val)
                elif isinstance(val, (int, float)):
                    candidates.append(val)
            for val in x.values():
                if len(candidates) < 3:
                    walk(val)

    walk(obj)
    for val in candidates:
        if isinstance(val, (int, float)):
            t = val / 1000 if val > 10_000_000_000 else val
            try:
                return dt(t)
            except Exception:
                pass
        if isinstance(val, str):
            s = val.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(s).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
            except Exception:
                pass
    return dt(fallback_mtime)


def read_head_jsonl(path, max_lines=150):
    records = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                obj = {"raw": line}
            records.append(obj)
    return records


def hit_patterns(text):
    lower = text.lower()
    hits = []
    for name, words in PATTERNS.items():
        if any(w.lower() in lower for w in words):
            hits.append(name)
    return hits


def add_receipt(receipts, section, date, tool, path, quote, note, config):
    quote = sanitize(quote)
    if not quote:
        return
    receipts[section].append({
        "date": date,
        "tool": tool,
        "path": public_label(path, config),
        "quote": quote,
        "note": note,
    })


def scan_pattern_stats(patterns, files):
    stats = {name: {"matches": 0, "files": 0} for name in patterns}
    token_to_names = defaultdict(list)
    for name, words in patterns.items():
        for word in words:
            token_to_names[word.lower()].append(name)
    matcher = re.compile("|".join(re.escape(token) for token in sorted(token_to_names, key=len, reverse=True)))
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        file_hits = set()
        for match in matcher.finditer(text):
            for name in token_to_names[match.group(0)]:
                stats[name]["matches"] += 1
                file_hits.add(name)
        for name in file_hits:
            stats[name]["files"] += 1
    return stats


def top_project_dirs(files):
    c = Counter()
    for item in files:
        c[item["tool"]] += 1
    return c


def project_lifecycles(files):
    data = {}
    for item in files:
        p = item["path"]
        parts = p.parts
        label = None
        if ".claude" in parts and "projects" in parts:
            idx = parts.index("projects")
            if idx + 1 < len(parts):
                label = "Claude project [redacted]"
        if not label:
            continue
        row = data.setdefault(label, {"count": 0, "first": item["mtime"], "last": item["mtime"], "tools": Counter()})
        row["count"] += 1
        row["first"] = min(row["first"], item["mtime"])
        row["last"] = max(row["last"], item["mtime"])
        row["tools"][item["tool"]] += 1
    return data


def add_project_receipts(receipts, files, config):
    if not files:
        return
    latest = max(x["mtime"] for x in files)
    lifecycles = project_lifecycles(files)
    for label, row in sorted(lifecycles.items(), key=lambda kv: (-kv[1]["count"], kv[1]["last"]))[:12]:
        if row["count"] >= 3:
            add_receipt(
                receipts,
                "recurring",
                f"{dt(row['first'])} -> {dt(row['last'])}",
                "Claude Code",
                config.home / ".claude" / "projects",
                f"{label}",
                f"path-derived project recurrence: {row['count']} transcript files",
                config,
            )
    vanished = []
    seven_days = 7 * 24 * 60 * 60
    for label, row in lifecycles.items():
        if row["count"] >= 3 and latest - row["last"] >= seven_days:
            vanished.append((label, row))
    for label, row in sorted(vanished, key=lambda kv: (-kv[1]["count"], kv[1]["last"]))[:12]:
        add_receipt(
            receipts,
            "abandonment",
            f"{dt(row['first'])} -> {dt(row['last'])}",
            "Claude Code",
            config.home / ".claude" / "projects",
            f"{label}",
            f"path-derived lifecycle: {row['count']} transcript files, no mtime in final 7 days of corpus",
            config,
        )


def write_evidence(files, sample, global_counts, receipts, project_counts, rhythm, blindspot_counts, config):
    total_size = sum(x["size"] for x in files)
    oldest = min(files, key=lambda x: x["mtime"]) if files else None
    newest = max(files, key=lambda x: x["mtime"]) if files else None
    sampled_by_tool = Counter(x["tool"] for x in sample)
    session_hours = Counter(datetime.fromtimestamp(x["mtime"]).hour for x in files)

    lines = []
    lines.append("# evidence.md")
    lines.append("")
    lines.append("Phase 2 evidence only. No interpretation. Patterns require 3+ occurrences unless marked insufficient data.")
    lines.append("")
    lines.append("## Scope and guardrails")
    lines.append("")
    lines.append(f"- Main transcript candidates: {len(files)} files, {total_size} bytes.")
    if oldest and newest:
        lines.append(f"- Candidate mtime range: {dt(oldest['mtime'])} -> {dt(newest['mtime'])}.")
    lines.append(f"- Sampled files read: {len(sample)}. Read cap: first 150 lines per sampled file.")
    if config.cutoff_label:
        lines.append(f"- Corpus cutoff: `{config.cutoff_label}` (inclusive).")
    lines.append("- Sample mix: " + ", ".join(f"{k}: {v}" for k, v in sorted(sampled_by_tool.items())))
    lines.append("- Full corpus sweeps used Python regex count/file-match operations; raw logs were not copied here.")
    lines.append("- Quotes are short and mechanically redacted for paths, URLs, emails, tokens, and likely secrets.")
    lines.append("")

    lines.append("## Global pattern counts")
    lines.append("")
    for name in sorted(global_counts):
        c = global_counts[name]
        lines.append(f"- {name}: {c['matches']} matches across {c['files']} files.")
    lines.append("")

    def section(title, key, intro, fallback="insufficient data"):
        lines.append(f"## {title}")
        lines.append("")
        if intro:
            for item in intro:
                lines.append(f"- {item}")
        items = receipts.get(key, [])
        if not items:
            lines.append(f"- {fallback}.")
        else:
            for r in items[:12]:
                lines.append(f"- {r['date']} | {r['tool']} | `{r['path']}` | \"{r['quote']}\" | {r['note']}")
        lines.append("")

    recurring_intro = []
    for label, count in project_counts.most_common(12):
        if count >= 3:
            recurring_intro.append(f"Project/source recurrence: `{sanitize(label)}` appears in {count} candidate files.")
    section("1. Recurring themes - what I return to again and again", "recurring", recurring_intro)

    abandonment_intro = []
    for label, count in project_counts.most_common():
        if 3 <= count <= 8:
            abandonment_intro.append(f"Candidate started/returned project with limited visible continuation in archive count: `{sanitize(label)}` appears {count} times.")
        if len(abandonment_intro) >= 8:
            break
    section("2. Abandonment graveyard - what I start and never finish", "abandonment", abandonment_intro)

    correction_intro = [
        f"Correction/friction sweep: {global_counts['correction']['matches']} matches across {global_counts['correction']['files']} files.",
        f"Frustration sweep: {global_counts['frustration']['matches']} matches across {global_counts['frustration']['files']} files.",
    ]
    section("3. Correction patterns - what I fix in the AI's work", "correction", correction_intro)

    repetition_intro = [
        f"Automation/delegation sweep: {global_counts['delegate']['matches']} matches across {global_counts['delegate']['files']} files.",
        f"Config/tooling sweep: {global_counts['config']['matches']} matches across {global_counts['config']['files']} files.",
    ]
    section("4. Repetition tax - what I ask for over and over", "repetition", repetition_intro)

    rhythm_intro = []
    for hour, count in session_hours.most_common(8):
        if count >= 3:
            rhythm_intro.append(f"Candidate transcript mtime hour {hour:02d}:00 has {count} files.")
    for hour, count in rhythm.most_common():
        if count >= 3:
            rhythm_intro.append(f"Sampled first-150-line timestamp hour {hour:02d}:00 has {count} records.")
    if not rhythm_intro:
        rhythm_intro.append("Timestamp density from sampled records did not reach 3+ in any hour.")
    section("5. Rhythm - when I do my best work, when I spiral", "rhythm", rhythm_intro)

    blind_intro = []
    for label, cnt in blindspot_counts.items():
        if cnt < 3:
            blind_intro.append(f"Absence/low-frequency term: `{label}` appears {cnt} times in full transcript candidates.")
    section("6. Blind spots - conspicuously absent", "blindspots", blind_intro)

    lines.append("## Sampled files")
    lines.append("")
    for item in sample:
        lines.append(f"- {dt(item['mtime'])} | {item['tool']} | `{public_label(item['path'], config)}` | {item['size']} bytes")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    config = build_config(parse_args())
    for path in (config.output, config.report, config.sample_list, config.all_list, config.final_body):
        path.parent.mkdir(parents=True, exist_ok=True)

    files = list(iter_files(config))
    files_sorted = sorted(files, key=lambda x: (x["mtime"], str(x["path"])))
    assign_public_labels(files_sorted, config)
    config.all_list.write_text(manifest_text(files_sorted, config), encoding="utf-8")
    sample = select_samples(files_sorted)
    config.sample_list.write_text(manifest_text(sample, config), encoding="utf-8")

    all_paths = [x["path"] for x in files_sorted]
    checkpoint_lines = [
        "# evidence.md",
        "",
        "Phase 2 evidence only. No interpretation. Patterns require 3+ occurrences unless marked insufficient data.",
        "",
        "## Process checkpoints",
        "",
        f"- Started with {len(files_sorted)} candidate files after excluding the current audit thread.",
    ]
    if config.cutoff_label:
        checkpoint_lines.append(f"- Corpus cutoff: `{config.cutoff_label}` (inclusive).")

    blindspot_terms = ("test", "user feedback", "customer", "calendar", "sleep", "break", "done", "ship")
    full_scan_patterns = {**PATTERNS, **{f"blindspot:{term}": [term] for term in blindspot_terms}}
    full_scan_stats = scan_pattern_stats(full_scan_patterns, all_paths)
    global_counts = {name: full_scan_stats[name] for name in PATTERNS}
    blindspot_counts = {term: full_scan_stats[f"blindspot:{term}"]["matches"] for term in blindspot_terms}

    receipts = defaultdict(list)
    rhythm = Counter()
    sampled_records = 0
    sample_batches_written = []

    for idx, item in enumerate(sample, start=1):
        records = read_head_jsonl(item["path"], 150)
        sampled_records += len(records)
        file_hit_categories = set()
        file_text_fragments = []
        first_date = dt(item["mtime"])
        userish = []
        for obj in records:
            rec_date = parse_ts_from_obj(obj, item["mtime"])
            first_date = rec_date or first_date
            hour_match = re.search(r"(\d{2}):\d{2}:\d{2}", rec_date or "")
            if hour_match:
                rhythm[int(hour_match.group(1))] += 1
            role, strings = record_role_and_strings(obj)
            if not strings:
                continue
            joined = " ".join(strings)
            hits = hit_patterns(joined)
            file_hit_categories.update(hits)
            for text in strings:
                if role == "user":
                    userish.append(text)
                file_text_fragments.append(text)

        joined_sample = " ".join(file_text_fragments)
        projectish = PROJECT_HINT_RE.findall(joined_sample)
        if projectish:
            add_receipt(
                receipts, "recurring", first_date, item["tool"], item["path"],
                userish[0] if userish else projectish[0],
                "sampled first-150-line project/theme hint",
                config,
            )
        if "correction" in file_hit_categories or "frustration" in file_hit_categories:
            quote = next((t for t in userish if hit_patterns(t)), userish[0] if userish else joined_sample)
            add_receipt(receipts, "correction", first_date, item["tool"], item["path"], quote, "correction/friction hit in sampled head", config)
        if "delegate" in file_hit_categories or "config" in file_hit_categories:
            quote = next((t for t in userish if "auto" in t.lower() or "自动" in t or "config" in t.lower() or "配置" in t), userish[0] if userish else joined_sample)
            add_receipt(receipts, "repetition", first_date, item["tool"], item["path"], quote, "automation/config/tooling hit in sampled head", config)
        if "deliberation" in file_hit_categories and "execution" not in file_hit_categories:
            quote = userish[0] if userish else joined_sample
            add_receipt(receipts, "abandonment", first_date, item["tool"], item["path"], quote, "planning/research hit without execution term in sampled head", config)
        if len(records) >= 150:
            add_receipt(receipts, "rhythm", first_date, item["tool"], item["path"], f"sample reached 150-line cap at {first_date}", "long session head reached read cap", config)
        if idx % 25 == 0:
            sample_batches_written.append(idx)
            partial = {
                "sampled_so_far": idx,
                "records_read_so_far": sampled_records,
                "note": "partial evidence checkpoint; raw records discarded by process",
            }
            checkpoint_path = config.output.parent / "analysis" / "session_mining" / f"checkpoint_{idx}.json"
            checkpoint_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            checkpoint_lines.append(
                f"- After {idx} sampled files: {sampled_records} first-150-line records read; "
                "raw records discarded after aggregate receipts were retained."
            )

    add_receipt(
        receipts,
        "blindspots",
        dt(max(x["mtime"] for x in files_sorted)) if files_sorted else "",
        "all sources",
        config.all_list,
        "low-frequency terms recorded in section intro",
        "absence is counted via full-corpus Python regex sweeps",
        config,
    )

    add_project_receipts(receipts, files_sorted, config)
    project_counts = top_project_dirs(files_sorted)
    final_structured = write_evidence(files_sorted, sample, global_counts, receipts, project_counts, rhythm, blindspot_counts, config)
    config.final_body.write_text(final_structured, encoding="utf-8")
    config.output.write_text("\n".join(checkpoint_lines) + "\n\n" + final_structured, encoding="utf-8")

    report = {
        "candidate_files": len(files_sorted),
        "sampled_files": len(sample),
        "sampled_records_first_150_lines": sampled_records,
        "checkpoints": sample_batches_written,
        "evidence": "evidence.md",
        "candidate_list": "analysis/session_mining/candidate_files.txt",
        "sample_list": "analysis/session_mining/sample_files.txt",
        "corpus_cutoff": config.cutoff_label,
        "global_counts": global_counts,
        "section_receipts": {k: len(v) for k, v in receipts.items()},
    }
    config.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_files": report["candidate_files"],
        "sampled_files": report["sampled_files"],
        "sampled_records": report["sampled_records_first_150_lines"],
        "evidence": report["evidence"],
        "checkpoints": report["checkpoints"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
