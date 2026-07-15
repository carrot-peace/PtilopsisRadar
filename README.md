# Ptilopsis Radar

Information Environment Anomaly Monitoring & Public Opinion Radar Tool

[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.1.0-blue.svg)](https://github.com/carrot-peace/PtilopsisRadar)

**English** | **[中文](README-CN.md)**

---

## What This Project Is

Ptilopsis Radar monitors anomaly signals across multi-platform information environments. It simultaneously ingests data from Chinese hot-list / social platforms and RSS / international media / official sources, classifies sources into evidence tiers (A / B / C / D), and identifies through programmatic rules:

- **Cross-layer resonance** — Social / trending platforms and primary or background sources appear simultaneously
- **High-heat unverified** — D-tier platforms show rising propagation, but lack A / B / C source corroboration
- **Chinese-only heat** — Internal warming within the Chinese information environment, but missing A / B international or official background sources
- **Silence gap** — A / B background sources carry information, but Chinese social platforms show weak response
- **Suppressed / background items** — Information present but below anomaly thresholds

## What This Project Is Not

- Not a news client or RSS reader
- Not a news product centered on newsletter or hot-topic digest consumption
- Not a fact-checking tool — it does not judge true or false
- Not a public opinion conclusion generator — it does not output "event has occurred"
- Not a system that lets AI directly judge truth or falsehood

---

## Product Boundary

PtilopsisRadar is a product-boundary fork of TrendRadar.

TrendRadar optimizes for broad utility: aggregation, RSS reading, AI summaries, MCP integrations, and customizable artifact reports.

PtilopsisRadar optimizes for a narrow radar function: detecting abnormal propagation structures in Chinese-language information environments.

Therefore, features that are valid in TrendRadar may be deliberately removed from PtilopsisRadar when they expand the maintenance surface without improving signal detection.

Use this as the governing rule:
- Do not preserve a feature merely because it was valid in TrendRadar.
- Preserve a feature only if it improves signal detection, evidence quality, operational reliability, or radar readability.
- Otherwise classify it as legacy / deprecated / deletion candidate.

### Signal Domains

Economic, social, policy, public-safety, and geopolitical topics are valid as signal domains.

They do not expand PtilopsisRadar into a general news, market-data, or economic-data product.

Micro-level economic signals are in scope when they appear as information-environment signals, such as layoffs, wage arrears, shop closures, rent pressure, local fiscal stress, consumption changes, supply disruptions, price anomalies, or similar signals.

They are out of scope when they require PtilopsisRadar to become a market dashboard, investment tracker, macroeconomic database, financial-news aggregator, or general RSS/news reader.

### Core Product Path

```
hotlist/RSS crawling
→ source tiers
→ evidence summary / evidence labels / bucketize
→ environment AI analysis
→ current dashboard / daily report artifacts
```

---

## What Problem It Solves

Chinese internet hot-list platforms (Weibo, Douyin, Zhihu, etc.) carry early-stage propagation value, but their credibility is unstable. International media, official sources, technical communities, and financial sources provide background reference, but are naturally isolated from Chinese social platform information streams.

Ptilopsis Radar's value is placing these sources into a unified observation framework, examining whether "heat" and "evidence tier" are misaligned: a topic trending on D-tier platforms does not mean the event has been established; a topic with background information on A / B sources but silence on Chinese platforms is also a signal worth observing.

---

## Core Mechanisms

### Multi-Source Collection

Simultaneously crawls two categories of data sources:

- **Hot-list platforms**: Weibo, Baidu, Douyin, Zhihu, Bilibili, Toutiao, The Paper, Wall Street CN, CLS, iFeng, Tieba
- **RSS feeds**: Official blogs from OpenAI, Anthropic, Google AI; international media from Reuters, AP, BBC, NYT, Washington Post; financial sources like Yahoo Finance; technical communities like Hacker News

Data sourced from the [newsnow](https://github.com/ourongxing/newsnow) open-source project API.

### Source Tier Classification

Each data source is mapped to an evidence tier (defined in `config/source_tiers.yaml`):

| Tier | Meaning | Examples |
|------|---------|----------|
| **A** | Primary / official sources | OpenAI official blog, Anthropic research publications, Google DeepMind Blog |
| **B** | International media / background sources | Reuters, AP, BBC, NYT, Hacker News, Yahoo Finance |
| **C** | Chinese relatively serious information sources | The Paper, Wall Street CN, CLS, Zhihu, Baidu |
| **D** | High-timeliness low-credibility propagation platforms | Weibo, Douyin, Tieba, Bilibili |
| **unknown** | Unconfigured tier | — |

**Important: Tiers are source labels, not factuality judgments. D-tier heat only indicates that propagation is occurring, not that the event has been established.**

### Programmatic Evidence Classification

The program (`trendradar/ai/evidence.py`) treats keyword topic groups as candidate containers, then evaluates every reader-facing event from the exact evidence bound to it:

1. Aggregates which A / B / C / D sources the topic has hit, grouped by tier
2. Calculates D-tier heat (platform count, highest ranking)
3. Detects sentiment signals (strong emotion words in titles)
4. Assigns a stable `evidence_id` to each collected text and binds returned events through `evidence_ids`
5. Recomputes the final `event_label`, verification status, factual boundary, and section from each event's evidence subset

**Topic groups are not reader-facing entries. Verification status and section are determined exclusively from event-level evidence; AI may not alter them.**

### Restrained AI Writing

AI (optional, requires API Key configuration) organizes candidate texts into concrete events and writes restrained, evidence-bound titles, summaries, and propagation notes. AI does not:

- Introduce new facts, numbers, or persons not in the evidence summary
- Alter an event's verification status, factual boundary, or section allocation
- Rewrite D-tier propagation as factual events
- Output investment advice, action guidance, or trend predictions

### Reports & Push Notifications

Generates an Information Environment Anomaly Monitoring Daily Report (HTML).
Report delivery runs only through the separately gated CR or DR dispatch
planes. Deployment notifications and supervisor alerts use an independent,
owner-only operational channel. The old multi-channel notification, fallback,
and compatibility facade are fully removed. See
[`docs/transport_boundaries.md`](docs/transport_boundaries.md).

For the event schema, Gemini budget, delivery gates, deployment steps, and
acceptance checklist, see [`docs/dr-operator-guide.md`](docs/dr-operator-guide.md).

---

## Anomaly Section Reference

| Section | Verification Status | Meaning |
|---------|-------------------|---------|
| **Cross-layer resonance** | Cross-layer resonance exists | D-tier has heat, and A / B background sources corroborate. Cross-layer source resonance exists, but not all D-tier claims are confirmed |
| **High-heat unverified** | High-heat unverified | Pure D-tier high heat, no A / B / C corroboration. Can only confirm propagation is occurring, cannot confirm the event has been established |
| **Chinese-only heat** | Chinese sources resonate (missing A / B background) | D-tier has heat and C serious sources corroborate, but missing A / B primary / international background sources. Internal warming in Chinese information environment; should not be directly treated as a factually significant event |
| **Silence gap** | Silence gap | A / B background sources carry information, but D-tier has no heat. Background sources have information, Chinese social platforms show no clear response |
| **Suppressed** | — | Information below anomaly thresholds (low heat, low-heat sentiment clusters, etc.), for dashboard counts only |

Additionally, the program identifies **sentiment signals** as secondary attribute annotations: when strong emotion words appear in titles, a `sentiment_flag` is set, but this does not constitute an independent section.

---

## AI Involvement Boundaries

This project has explicit boundaries for AI usage:

| Handled by Program | Handled by AI |
|--------------------|---------------|
| Source tier classification (A / B / C / D) | Readable expression |
| Verification status determination | Restrained summary / analysis text |
| Section allocation (bucketing) | One-sentence overview interpretation |
| Report skeleton & data statistics | — |
| Heat calculation & ranking tracking | — |

What AI cannot do:

1. Introduce new facts, numbers, or conclusions beyond the evidence summary
2. Alter verification status or move sections
3. Rewrite D-tier high-heat propagation as factual events
4. Provide guidance to investors / brands / the public
5. Make trend predictions or write grand narratives
6. sample_titles (representative propagation texts) are only "someone is saying / spreading this", not factual sources

---

## Quick Start

### Requirements

- Python >= 3.12
- Package manager: [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Local Run

```bash
# Clone repository
git clone https://github.com/carrot-peace/PtilopsisRadar.git
cd PtilopsisRadar

# Install dependencies with uv
uv sync

# Edit configuration (see "Configuration Entry Points" below)
cp config/config.yaml config/config.yaml.bak
# Edit config/config.yaml to configure data sources and artifact generation

# Run
uv run python -m trendradar
```

### Apple Container Deployment (macOS, Recommended)

Requires macOS 26+ with [Apple container](https://github.com/apple/container) v1.0.0+.

```bash
# Build image
scripts/apple-container/build-image.zsh ptilopsis-radar:latest

# Prepare .env
cp docker/.env.example docker/.env
# Edit docker/.env to configure environment variables

# Run with cron + web server
container run -d \
  --name trendradar \
  --cpus 2 --memory 1g \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=$(pwd)/config,target=/app/config,readonly \
  --volume $(pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest
```

For persistent operation, a LaunchAgent supervisor is provided:

```bash
# Load the supervisor (auto-restarts on crash)
mkdir -p ~/Library/Logs/PtilopsisRadar
launchctl bootstrap gui/$(id -u) scripts/apple-container/com.carrot-peace.ptilopsis-radar.plist
```

See [`docs/deployment/apple-container-cutover.md`](docs/deployment/apple-container-cutover.md) for full migration notes and [`docs/deployment/apple-container-rebuild-guide.md`](docs/deployment/apple-container-rebuild-guide.md) for update procedures.

### Docker Deployment

```bash
# Optional: build the crawler image locally with a unique deployment identity
scripts/docker/build-image.sh wantcat/trendradar:latest

cd docker
cp .env.example .env
# Edit .env to configure environment variables
docker compose up -d
```

`docker-compose.yml` runs the tagged image; it does not build local Prompt or Python changes automatically. Re-run the build script before recreating containers whenever the DR pipeline changes.

### GitHub Actions Deployment

1. Fork this repository
2. Configure required environment variables in repository Settings → Secrets (AI API Key, remote storage, etc.)
3. Enable the scheduled task in `.github/workflows/crawler.yml`

> This deployment method requires remote storage, Secrets, and workflow configuration. Currently recommended for experienced users.

### AI Analysis (Optional)

AI analysis requires an API Key. If you do not use AI analysis, set `ai_analysis.enabled: false` in `config/config.yaml`, or disable via environment variable `AI_ANALYSIS_ENABLED=false`.

When enabling, configure in the `ai` section of `config/config.yaml`:

```yaml
ai:
  model: "deepseek/deepseek-v4-flash"  # Any model in LiteLLM format
  api_key: "your-api-key"
```

Supported models include DeepSeek, OpenAI, Gemini, Claude, Ollama, etc. See [LiteLLM docs](https://docs.litellm.ai/docs/providers).

The information-environment daily report has its own capacity budget: up to 30 evidence records sent to AI, 12 evidence records per batch, and 16,000 output tokens per request by default. Docker and GitHub Actions can override these with `AI_ANALYSIS_MAX_EVENTS`, `AI_ANALYSIS_BATCH_MAX_EVIDENCE`, and `AI_ANALYSIS_MAX_OUTPUT_TOKENS` without changing translation or other AI workloads. The legacy `max_events` name limits AI input evidence, not the number of deterministic fallback events shown to readers.

### Diagnostic Commands

```bash
# Environment health check
uv run python -m trendradar --doctor

# Show current schedule status
uv run python -m trendradar --show-schedule
```

---

## Configuration Entry Points

| File | Purpose |
|------|---------|
| `config/config.yaml` | Main config: data sources, report mode, AI model, storage, scheduling, etc. |
| `config/source_tiers.yaml` | Source tier mapping: platform / RSS feed to A / B / C / D tier assignment |
| `config/frequency_words.txt` | Keywords / topic groups: for keyword matching mode (`filter.method: keyword`) |
| `config/ai_interests.txt` | AI filter interest description: for AI smart filtering mode (`filter.method: ai`) |
| `config/ai_environment_report_prompt.txt` | AI prompt template for Information Environment Anomaly Monitoring Daily Report |
| `config/timeline.yaml` | Scheduling strategy: time period definitions, day plans, week mapping |
Configuration files contain detailed comments.

---

## Project Architecture

```
trendradar/
├── __main__.py          # Entry point: NewsAnalyzer orchestrates collect→analyze→artifact pipeline
├── context.py           # AppContext: dependency injection container, wraps config-related ops
├── core/                # Core logic
│   ├── loader.py        #   Config file loading
│   ├── frequency.py     #   Keyword matching
│   ├── analyzer.py      #   Frequency statistics, weight calculation
│   ├── scheduler.py     #   Timeline scheduler
│   ├── source_tiers.py  #   Source tier resolver
│   ├── data.py          #   Data reading & new item detection
│   └── cdn.py           #   CDN multi-source fallback
├── crawler/             # Data collection
│   ├── fetcher.py       #   Hot-list platform crawler
│   └── rss/             #   RSS fetcher & parser
├── storage/             # Storage layer
│   ├── base.py          #   Data models (NewsItem, RSSItem)
│   ├── sqlite_mixin.py  #   SQLite storage mixin
│   ├── local.py         #   Local storage backend
│   ├── remote.py        #   Remote storage backend (S3-compatible)
│   └── manager.py       #   Storage manager
├── ai/                  # AI module
│   ├── analyzer.py      #   AI deep analysis
│   ├── evidence.py      #   Evidence summary construction & programmatic classification
│   ├── filter.py        #   AI smart filtering
│   ├── translator.py    #   AI translation
│   ├── prompt_loader.py #   AI prompt template loading
│   └── client.py        #   LiteLLM client
├── report/              # Report generation
│   ├── generator.py     #   Report generator
│   ├── newsletter.py    #   Current/incremental full-report renderer
│   ├── dashboard.py     #   Current dashboard and publish-safe state
│   ├── daily_v2.py      #   Daily artifact model and renderer
│   └── translation.py   #   Artifact-owned report translation
└── utils/               # Utilities
    ├── time.py          #   Time handling
    └── url.py           #   URL handling

mcp_server/              # MCP Server (FastMCP 2.0)
├── server.py            #   MCP tool server entry point
└── tools/               #   Data query, analytics, search MCP tools

scripts/
└── apple-container/     # Apple container deployment
    └── trendradar-supervisor.zsh  #   LaunchAgent supervisor script

docker/
├── Dockerfile           #   Multi-stage build (uv + supercronic)
├── docker-compose.yml   #   Docker Compose (legacy)
├── manage.py            #   Container management CLI
└── entrypoint.sh        #   Container entrypoint
```

---

## Disclaimer

This project outputs **information environment observation results**, not factual conclusions, investment advice, public safety judgments, or legal opinions.

- Source tiers (A / B / C / D) are source classification labels, not factuality judgments
- Verification status is generated by programmatic rules, expressing "source tier distribution characteristics", not "whether an event is real"
- AI-generated text is based on the program-provided evidence summary; AI does not introduce new facts beyond the evidence
- Users should independently assess information reliability and should not use this project's output as the sole basis for decisions

---

## Upstream Acknowledgments & License

This project is based on [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar). Thanks to the original author for their open-source contribution.

Hot-list data source: [newsnow](https://github.com/ourongxing/newsnow) open-source project.

This project is licensed under [GPL-3.0](LICENSE).
