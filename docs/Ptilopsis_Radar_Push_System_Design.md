# Ptilopsis Radar Push System Design

Status: design draft
Version: v0.4.1
Scope: Telegram-first push system, CR/DR product model, CR input adapter contract, Growth Raw v0.1, archive model, implementation sequence, minor review fixes

## 1. Product Boundary

Ptilopsis Radar 的推送系统不是普通的通知出口，而是项目与用户交互的核心界面。

HTML、Markdown、Archive 是展开层、留档层、复盘层；Telegram text 是系统主动触达用户的主要方式。因此本系统的核心目标不是"把报告发出去"，而是：

```text
在合适的时间，用足够克制、足够解释性的文本，告诉用户：
- 是否有值得现在关注的信息环境变化；
- 为什么这条内容值得被推送；
- 如果需要展开，应查看哪一份 HTML artifact；
- 系统不把热度、关键词命中、证据结构等同于事实确认。
```

Current phase focuses on push design and CR/DR product structure, not data collection.

信息抓取已经通过关键词重写、hotlist、RSS、source/evidence 等进入可用状态；接下来要优化的是：

```text
when to push
what to push
how to write the push text
how to archive and expose the report artifact
```

MVP push channel is Telegram bot only. Email may be considered later, but is not part of the MVP.

Every push must have text. HTML is an artifact and may be attached to Telegram, served through GitHub Pages, served through a private service, or retained locally. Markdown is archive-only unless explicitly extended later.

System-level interaction uses English. Hotspot/topic content keeps its native language.

Examples of system-level terms:

```text
CR
CR-A
CR-P
DR
CR Primitive Record
CR Source Item
CR Candidate
CRCandidate
CRScoreResult
CRDecision
CRDecisionPolicy
CRScoringProfile
Decision
Triggers
Run
Date
Part
Link
CR HTML
DR HTML
```

Hotspot titles, summaries, and source excerpts keep their original language, usually Chinese.

Push text is no-emoji by default.

## 2. Current / Daily Product Split

The push system is split into two major product systems:

```text
CR = Current Report
DR = Daily Report
```

CR and DR are independent in trigger policy, content structure, AI participation, archive lifecycle, and Telegram message grammar.

They are not independent source systems. CR and DR share the same underlying source data family; the difference is time scale and product purpose.

```text
CR = high-frequency current-window radar
DR = daily-scale report and interpretation
```

CR uses high-frequency current-window data. DR uses daily-scale accumulated data.

### 2.1 CR: Current Report

CR is the high-frequency current report system.

CR is generated on a fixed schedule, such as every 30 minutes or another configured interval. Every CR run should produce a CR artifact regardless of whether a push is sent.

CR has two push-facing forms:

```text
CR-A = Current Report Alert
CR-P = Current Report Pull
```

CR MVP must be able to run fully without AI.

CR-A is not based on `AIAnalysisResult`.
CR-A is not based on the existing environment alert brief path.
CR-A is triggered by deterministic scoring and decision policy.

### 2.2 DR: Daily Report

DR is the daily report system.

DR may use the current environment newsletter / AI overview direction in the repository. AI can be used for AI Brief, daily overview, topic brief generation, and editorial interpretation.

DR must not be treated as CR-A. DR is a scheduled daily product, not a realtime alert decision.

## 3. Engineering Alignment with Current Repository

The target baseline assumes the PR6–PR8 cleanup direction:

```text
non-Telegram runtime channels removed
classic report runtime removed
standalone/display-region runtime gates removed
display_mode=platform runtime path retired
canonical output fixed as the CR/DR input baseline
generic Telegram split path removed
```

If legacy `DISPLAY_MODE` or `display_mode=platform` compatibility branches still exist in the checked-out branch, CR must bypass them and consume canonical data only. Those compatibility remnants are out of scope for CR product semantics.

Current repository reality:

```text
current/incremental automatic push is still AI-driven
current realtime alert branch depends on ai_analysis.success
environment alert formatter is not the CR-A MVP foundation
```

Reusable infrastructure:

```text
Telegram delivery
Telegram receiver fanout
Telegram HTML attachment mechanism
local HTML artifact generation
DR environment newsletter direction
alert_state / cooldown / dedupe concepts
source/evidence metadata
daily newsletter HTML rendering direction
```

Not reusable as CR-A MVP foundation:

```text
AIAnalysisResult-driven realtime alert branch
select_environment_alert_items()
render_environment_telegram_alert_brief()
current dashboard naming as product language
generic split Telegram text path
```

Important engineering principle:

```text
CR scoring, CR decision, CR presentation, and delivery must be separated through explicit internal APIs.

CR scoring must not be implemented inside Telegram sender, HTML renderer, archive writer, or CLI orchestration code.
```

The existing repository contains legacy procedural flows and long parameter chains. PR6–PR8 reduced several legacy runtime surfaces, but CR should not extend the old pattern.

### 3.1 Field Reality

Current repository data is not yet a clean CR Candidate model.

The current main structures are:

```text
hotlist stats: keyword-group level
RSS stats: keyword-group level
title items: item-level metadata inside stats groups
evidence: mostly keyword-group level
rank_timeline: within-day item/source level, current/daily only
```

Therefore, the first CR implementation step must be an adapter layer, not scoring.

### 3.2 Metadata Pass-through Baseline

Low-cost metadata pass-through is allowed and useful before/inside PR9b.

Useful pass-through fields include:

```text
source_id in hotlist title items
feed_id in RSS title items
RSS published_at / summary / author when already available
```

These fields reduce future adapter guesswork. They must remain passive metadata and must not change report rendering, Telegram behavior, storage schema, or scoring.

## 4. Artifact and Event Model

The system distinguishes between run, report artifact, push event, and push message.

```text
Run
→ Report Artifact
→ Push Event
→ Push Message
→ optional HTML Attachment
→ Archive
```

### 4.1 CR Artifacts

Every CR run eventually produces:

```text
CR Candidate set
CR ScoreResult set
CR Decision set
CR HTML
CR Markdown
optional CR-A text
future CR-P text
```

However, implementation proceeds in layers:

```text
PR9b: CR primitive records / adapter
PR9c: true topic-level CR Candidates
PR9d: scoring
PR9e: decision
```

CR has exactly one unified HTML artifact per run.

CR-A and CR-P do not generate separate HTML reports. They are different Telegram text views over the same CR data.

```text
CR-A = automatic alert push view
CR-P = manual pull view
CR HTML = unified full current artifact
CR Markdown = permanent per-run audit archive
```

### 4.2 DR Artifacts

Every DR run produces:

```text
DR HTML
DR Telegram text
```

DR does not generate Markdown in MVP. DR HTML is the permanent daily report.

## 5. CR Data Layers

CR must distinguish three layers:

```text
raw repository stats
→ CR Primitive Record / CR Source Item
→ topic-level CR Candidate
```

### 5.1 Raw Repository Stats

Raw repository stats are existing dictionaries and dataclasses produced by the current pipeline.

Examples:

```text
stats from count_word_frequency()
rss_items / rss_new_items from count_rss_frequency()
title_info
new_titles
id_to_name
source tiers
evidence output
```

These are not CR Candidates.

### 5.2 CR Primitive Record

A CR Primitive Record is the adapter-level representation of existing stats.

It may still be keyword-group based.

Purpose:

```text
preserve fields
normalize source/item metadata
record availability flags
avoid pretending keyword groups are topic clusters
```

PR9b should produce this layer.

### 5.3 CR Candidate

A CR Candidate is a topic-level cluster.

It is not necessarily a verified real-world event. It is a topic-level information cluster built from one CR run.

PR9c should build true CR Candidates from primitive records.

Before PR9c, code and tests should avoid overclaiming that primitive records represent topic-level Candidates.

## 6. CR Candidate Model

CR Candidate is the unit of current report evaluation.

Candidate generation uses mixed internal recall but topic-level user presentation.

Inputs may include:

```text
rewritten keyword hits
hotlist items
RSS items
source/evidence metadata
run-local rank/time signals
title/topic similarity
```

User-facing presentation must not expose raw keyword groups as the main title. Keywords are recall and scoring inputs, not the primary display unit.

Candidate display name rule:

```text
Choose the hottest / most prominent topic or title inside the topic cluster.
```

Heat has priority over source credibility when selecting the visible topic name. This reflects the project's purpose: Ptilopsis Radar tracks information-environment movement. Even if a high-heat topic later turns out to be false, its spread is still meaningful as an information signal.

Core principle:

```text
Heat decides visibility.
Credibility and source structure decide interpretation.
```

Keyword configuration is a positive selection system, not a negative exclusion system.

The CR Candidate pool uses broad inclusion. Keyword match can be enough for initial inclusion, unless the record is structurally invalid. The system should not maintain a separate content blacklist as the main filtering mechanism.

Allowed structural cleanup examples:

```text
empty title
unparseable record
damaged fields
exact duplicate record
```

Topic clustering MVP should use deterministic text similarity. A simple implementation may compare normalized title/topic tokens and treat two items as the same topic when token/keyword overlap reaches a configurable threshold.

Before implementation, existing topic normalization / dedupe helpers should be audited, but CR Candidate clustering should be an independent CR layer.

## 7. CR Input Adapter

CR requires a dedicated input adapter before scoring.

Existing repository data such as hotlist stats, RSS stats, title dictionaries, new title metadata, rank/count/time fields, and source/evidence metadata must be normalized into CR-specific models.

The CR Input Adapter consumes existing canonical run data and produces preliminary primitive records / source items.

It must not:

```text
score candidates
decide suppress/watch/alert/urgent
render Telegram text
write HTML or Markdown
send notifications
cluster topics
```

Expected inputs may include:

```text
stats from keyword/hotlist analysis
rss_items / rss_new_items
new_titles / title_info
source/evidence metadata
rank / count / time / is_new / rank_timeline
RSS published time / source / url
```

Expected output:

```text
CR primitive records with stable IDs, source/title data, keyword group fields,
representative links, normalized rank visibility, source type, and availability flags.
```

Current repository stats are not the CR Candidate model. They are source data for the adapter.

## 8. PR9b CR Input Adapter Contract

PR9b must establish a clean adapter contract.

The adapter contract exists to protect later scoring from repository quirks such as RSS pseudo-ranks, sentinel ranks, synthetic time fields, first crawl `is_new` noise, and keyword-group/topic mismatch.

### 8.1 Required Source Item Fields

A future `CRSourceItem` or equivalent primitive item should include:

```text
source_type: "hotlist" | "rss" | "unknown"
source_id: str | None
feed_id: str | None
source_name: str
title: str
url: str | None
keyword_group: str | None
keyword_groups: list[str] | None
is_new: bool | None
is_new_semantics: "new_titles_detection" | "incremental_first_crawl" | "unknown"
```

`keyword_group` may be a single primary group in PR9b. If multiple keyword groups are available, the adapter may preserve them in `keyword_groups` for future clustering/evidence work.

`is_new` must not be consumed without `is_new_semantics`.

```text
new_titles_detection:
  is_new comes from normal new title detection.

incremental_first_crawl:
  is_new may be true because this is the first crawl of the day.
  It must not contribute to New Burst.

unknown:
  scoring must be conservative.
```

For RSS:

```text
published_at: str | None
summary: str | None
author: str | None
```

For hotlist:

```text
raw_rank: int | None
normalized_rank: int | None
is_visible: bool
rank_sentinel: "none" | "zero" | "ninety_nine" | "missing"
```

### 8.2 Source Type Rules

`source_type` must be explicit.

```text
hotlist: rank can be used for Growth / Current Heat
rss: rank must not be used as heat rank
unknown: rank-based scoring disabled
```

RSS published-order pseudo-rank must never enter Rank Movement or Current Heat rank scoring.

### 8.3 Rank Normalization

Adapter must normalize rank sentinels.

```text
rank in {0, 99, None, missing} → not visible
normalized_rank = None
is_visible = false
```

A valid visible rank is a positive integer that is not a sentinel.

Scoring must consume `normalized_rank` / `is_visible`, not raw rank directly.

### 8.4 Rank Timeline Contract

Fields:

```text
rank_timeline: list[dict] | []
has_rank_timeline: bool
has_reliable_rank_timeline: bool
visible_observation_count: int
```

Current/daily hotlist items may have reliable rank_timeline from storage.

`visible_observation_count` is the count of reliable visible observations in `rank_timeline`. Scoring should consume this field instead of reparsing raw timeline data.

Incremental items may lack rank_timeline or have synthetic title_info. Adapter must mark them unreliable rather than fabricate growth.

### 8.5 Previous Observation Contract

For Growth, previous rank must come from rank_timeline, not from `ranks[-2]`.

`ranks` is a distinct rank list, not a per-observation sequence.

Adapter should expose, when possible:

```text
previous_observation_exists: bool
previous_observation_visible: bool
previous_visible_rank: int | None
current_rank: int | None
rank_delta: int | None
```

`previous_visible_rank` should be derived from the second most recent reliable visible rank observation in rank_timeline, or equivalent reliable timeline logic.

If no reliable rank_timeline exists, previous observation fields should be unavailable.

### 8.6 Time Signal Contract

Fields:

```text
first_time: str | None
last_time: str | None
has_time_signals: bool
time_signals_synthetic: bool
run_time_inferred: bool
```

Incremental synthetic title_info may set first_time == last_time == current time. This must be marked synthetic.

`run_time_inferred = true` is not a penalty by itself. It is expected in the current repository because run_time may often be inferred from max last_time.

### 8.7 First Crawl of Day Contract

Adapter must expose:

```text
first_crawl_of_day: bool | None
```

This protects New Burst from `is_new` overfire on the first crawl of a day.

If `first_crawl_of_day` cannot be inferred, adapter should expose unknown and scoring must be conservative.

Rule:

```text
first_crawl_of_day == true → is_new must not contribute to New Burst
```

### 8.8 Count Contract

Fields:

```text
count: int | None
has_count: bool
count_semantics: "crawl_count" | "rss_item_count" | "group_count" | "unknown"
```

Count must not be naked-added across sources.

Count fallback may be used weakly for persistence only when rank_timeline is unavailable.

### 8.9 Availability Flags

Minimum flags:

```text
source_type
has_current_rank
has_rank_timeline
has_reliable_rank_timeline
has_time_signals
time_signals_synthetic
has_count
first_crawl_of_day
```

These flags are not optional debug sugar. They are scoring safety requirements.

## 9. CR Decision Levels

CR uses four Decision levels:

```text
suppress
watch
alert
urgent
```

### 9.1 suppress

`suppress` is not a low-score range. It is a veto-style presentation label set.

Meaning:

```text
HTML only
collapsed by default
never enters Telegram text push
still scored
used for audit and scoring iteration
```

Suppressed candidates are still scored, archived, and retained. Suppress only controls presentation and push eligibility.

A candidate may have a high score and still be suppressed. This is intentional. It allows later review of whether scoring is over-firing, suppress labels are too aggressive, or a suppressed topic should become watch/alert in future profile versions.

### 9.2 watch

`watch` means the candidate is visible and has observation value, but is not worth actively interrupting the user.

Meaning:

```text
visible in CR HTML
eligible for CR-P in future
no automatic push
```

### 9.3 alert

`alert` means the candidate is eligible for automatic CR-A push.

Meaning:

```text
eligible for CR-A
respects quiet
respects cooldown
```

Alert is primarily driven by high heat or rapid growth. It does not require factual verification or cross-layer confirmation.

### 9.4 urgent

`urgent` means the candidate is eligible for CR-A and can bypass quiet hours.

Meaning:

```text
eligible for CR-A
can bypass quiet
still respects dedupe / minimum cooldown
```

In profile v0.1, urgent can be triggered by Heat Score alone, without Cross-Evidence Score.

This means integrated heat can produce urgent. A single heat subcomponent, such as Growth Raw Score alone or Current Heat Raw Score alone, is not guaranteed to produce urgent unless a future profile explicitly defines such an override rule.

Urgent does not require cross-layer verification.

Cross-Evidence and background support can help upgrade a candidate, but they are not hard requirements for urgent.

## 10. CR Scoring Architecture

CR scoring must be an independent internal API.

The intended flow:

```text
Primitive Input Adapter
→ Candidate Builder / Clustering
→ Scoring API
→ Decision Policy
→ Presentation Layer
→ Delivery Layer
```

### 10.1 Candidate Builder

Candidate Builder constructs CR Candidates from primitive records.

It does not decide push eligibility. It only produces candidate objects.

### 10.2 Scoring API

Scoring API computes score results.

Input:

```text
CRCandidate
CRScoringProfile
optional CRRunContext
```

Output:

```text
CRScoreResult
```

Scoring API must not:

```text
send Telegram messages
render HTML
write Markdown
write archive files
decide quiet / cooldown
decide final push delivery
```

### 10.3 Decision Policy

Decision Policy consumes:

```text
CRCandidate
CRScoreResult
suppress labels
runtime state
```

It outputs:

```text
CRDecision
```

Decision Policy handles:

```text
suppress / watch / alert / urgent
push eligibility
quiet bypass
dedupe key
trigger reasons
```

### 10.4 Presentation Layer

Presentation Layer renders:

```text
CR-A text
CR-P text
CR HTML
CR Markdown
```

It consumes Candidate + ScoreResult + Decision. It must not recompute scores.

### 10.5 Delivery Layer

Delivery Layer sends:

```text
Telegram text
optional HTML attachment
```

It must not compute scores or decide push eligibility.

## 11. CR Score Profile v0.1 Draft: Score Budget and Decision Shape

This is an initial calibration profile, not a permanent product law.

This section defines score components, component caps, and decision thresholds. It does not fully define final scoring formulas.

Concrete formulas depend on CR Input Adapter field availability and must be finalized after adapter contract and clustering are implemented.

Concrete thresholds and weights may change after historical CR archive review. The profile must be versioned.

### 11.1 Score Structure

CR uses a 100-point capped score profile.

```text
Total Score = Heat Score + Cross-Evidence Score
Max Total Score = 100
```

Components:

```text
Heat Score cap = 80
Cross-Evidence Score cap = 20
```

Each component may have redundant raw sub-scores. Raw sub-scores can exceed the component cap. Final component score is capped before contributing to total score.

```text
heat_score = min(80, heat_raw_score)
cross_evidence_score = min(20, cross_evidence_raw_score)
total_score = heat_score + cross_evidence_score
```

### 11.2 Heat Score

Draft score budget:

```text
Growth Raw Score: 0–60
Current Heat Raw Score: 0–50
Heat Score cap: 80
```

Growth is weighted higher than current heat.

Reason:

```text
CR-A is an early radar. Rapidly rising topics, even from a low base, may deserve early attention. Current heat matters, but momentum is more valuable for catching topics early.
```

Very low-base growth must be dampened to avoid low-base ratio noise.

This does not mean low-base growth is worthless. It means extremely low absolute volume should not receive full growth credit solely from a high relative ratio.

### 11.3 Cross-Evidence Score

Cross-Evidence Score is escalation support, not a truth score.

Draft score budget:

```text
Cross-layer Raw Score: 0–15
Background Support Raw Score: 0–10
Cross-Evidence Score cap: 20
```

Cross-Evidence Score does not verify factual accuracy.

It measures whether the heat signal has additional structure, cross-layer support, background support, or contextual completeness.

It can help a high-heat candidate move from alert to urgent, but it cannot replace Heat as the primary driver.

### 11.4 Heat Cap and Urgent Threshold

In profile v0.1, Heat Score cap equals the urgent threshold by design.

```text
Heat Score cap = 80
Urgent threshold = 80
```

This is intentional.

Maximum Heat Score alone can produce urgent because CR is a heat-first information-environment radar. Cross-Evidence is not required for the hottest tier.

### 11.5 Thresholds

Initial configurable thresholds:

```text
alert >= 60
urgent >= 80
```

These values are defaults for profile v0.1 and must be configurable.

Example config shape:

```yaml
CR:
  SCORING:
    PROFILE_VERSION: "cr-score-v0.1"
    ALERT_THRESHOLD: 60
    URGENT_THRESHOLD: 80
```

### 11.6 Formula Status

CR Score Profile v0.1 defines score budgets, caps, and decision thresholds. It does not yet define final concrete scoring formulas.

Formula design must be grounded in available repository fields.

## 12. Growth Raw v0.1

Growth Raw v0.1 is field-constrained.

It does not use:

```text
previous_run_value
recent_3_run_average
candidate-level historical baseline
true count delta
```

It uses available run-local signals:

```text
rank_timeline movement
is_new
current rank
first_time / last_time
weak count fallback
```

Total budget:

```text
Growth Raw Score: 0–60
```

Subcomponents:

```text
Rank Movement:      0–30
New Burst:          0–15
Recency Momentum:   0–10
Weak Persistence:   0–5
```

Formula:

```text
growth_raw = (
    rank_movement_score
    + new_burst_score
    + recency_momentum_score
    + weak_persistence_score
)

growth_raw = min(60, growth_raw)
```

### 12.1 Growth Field Guards

Growth scoring must consume adapter-normalized fields.

Required guards:

```text
source_type == "hotlist" for rank-based scoring
normalized_rank / is_visible, not raw rank
has_reliable_rank_timeline for rank movement and timeline persistence
time_signals_synthetic cap for recency
first_crawl_of_day guard for New Burst
```

RSS items must not contribute to Rank Movement or rank-based New Burst.

### 12.2 Rank Movement: 0–30

Purpose:

```text
Rank Movement measures whether a topic is rising quickly in visible rank position.
```

Applicable only when:

```text
source_type == "hotlist"
has_reliable_rank_timeline == true
```

Main fields:

```text
rank_timeline
current_rank
previous_observation fields
```

`previous_rank` must be derived from reliable rank_timeline. It must not be derived from `ranks[-2]`.

#### First-ever entry

If no previous reliable observation exists, and the current observation is visible, this is a first-ever entry.

```text
entered top 3       → 30
entered top 10      → 27
entered top 20      → 23
entered top 50      → 15
entered top 100     → 8
entered below 100   → 3
```

First-ever entry must apply single-observation confidence dampening unless later calibration proves it too conservative.

Suggested rule:

```text
if visible_observation_count <= 1 and count <= 1:
    first-ever entry Rank Movement *= 0.7
```

This is not a low-base veto. It only reduces one-time observation spikes.

#### Re-entry

If a previous reliable observation exists, the previous observation was not visible, and the current observation is visible, this is a re-entry.

Re-entry may use the same entry bucket:

```text
re-entered top 3       → 30
re-entered top 10      → 27
re-entered top 20      → 23
re-entered top 50      → 15
re-entered top 100     → 8
re-entered below 100   → 3
```

Re-entry does not automatically receive New Burst. New Burst depends on `is_new` and `is_new_semantics`.


#### Rank improvement

If previous observation is visible and current rank improves:

```text
improved >= 50 places and current top 20  → 28
improved >= 30 places and current top 20  → 25
improved >= 20 places                     → 21
improved >= 10 places                     → 15
improved >= 5 places                      → 9
improved < 5 places                       → 0
```

Visibility gate:

```text
if current_rank > 100:
    Rank Movement cap = 6
elif current_rank > 50:
    Rank Movement cap = 12
```

This is a low-visibility dampening rule, not a low-base veto.

#### Stable high rank

Stable high rank should mainly be scored by Current Heat and Weak Persistence, not Rank Movement.

```text
stable top 10 → Rank Movement 0–3
stable top 20 → Rank Movement 0–2
otherwise    → 0
```

#### Aggregation

Candidate-level aggregation requires PR9c clustering.

Before PR9c, Rank Movement may only be computed per primitive item.

After PR9c:

```text
Candidate Rank Movement = max(item_rank_movement_scores)
```

Do not add multiple rank movements across sources.

#### Debug fields

```text
rank_movement_score
rank_movement_reason
rank_movement_source_id
previous_visible_rank
current_rank
rank_delta
rank_timeline_available
visible_observation_count
single_observation_dampening_applied
```

### 12.3 New Burst: 0–15

Purpose:

```text
New Burst measures whether the topic has newly appeared / newly expanded.
```

Applicable only when:

```text
source_type == "hotlist"
first_crawl_of_day != true
```

If `first_crawl_of_day == true`:

```text
New Burst = 0
```

Reason: first crawl of day makes many items appear `is_new=true` for system-observation reasons, not because they newly emerged in the information environment.

If `source_type != hotlist`:

```text
New Burst = 0
```

RSS newness belongs to evidence/support, not rank-growth scoring.

#### Single item base score

If `is_new = true`:

```text
new + top 3       → 13
new + top 10      → 12
new + top 20      → 10
new + top 50      → 7
new + top 100     → 4
new + below 100   → 2
```

If `is_new = false`:

```text
0
```

#### Multi-source / multi-item new bonus

This requires PR9c clustering.

After PR9c:

```text
2 new sources/items  → +2
3 new sources/items  → +3
4+ new sources/items → +4
```

Total cap:

```text
New Burst cap = 15
```

Before PR9c, do not apply multi-source / multi-item bonus.

#### Low-base dampening

Low-base dampening applies only to burst-like bonus, not to Rank Movement or total Growth.

Suggested soft dampening:

```text
if single source and current_rank > 100:
    New Burst *= 0.65
elif single source and current_rank > 50:
    New Burst *= 0.8
else:
    New Burst unchanged
```

Low-base topics are not hard-blocked. Strong rank jump, top-N entry, or multi-source visibility may still produce high Growth.

#### Aggregation

Candidate-level aggregation requires PR9c.

After PR9c:

```text
New Burst = max(item_new_burst_scores) + multi_new_bonus
New Burst capped at 15
```

Before PR9c, New Burst is per primitive item.

#### Debug fields

```text
new_burst_score
new_burst_reason
new_item_count
new_source_count
first_crawl_of_day
low_base_dampening_applied
low_base_dampening_factor
```

### 12.4 Recency Momentum: 0–10

Purpose:

```text
Recency Momentum measures whether the topic recently appeared and remains visible in the current window.
```

Main fields:

```text
first_time
last_time
run_time
is_new
```

If time fields are synthetic, especially in incremental mode:

```text
if time_signals_synthetic:
    Recency Momentum cap = 3
```

`run_time_inferred = true` is expected in the current repository and must not be penalized by itself.

Scoring with reliable time fields:

```text
first seen within 30 min and last seen in current run/window → 10
first seen within 1 hour and still visible                  → 8
first seen within 3 hours and still visible                 → 6
first seen within 6 hours and still visible                 → 4
seen today but not fresh                                    → 1–2
stale / not currently visible                               → 0
```

If exact run_time is missing, may infer from max last_time, but must mark:

```text
run_time_inferred = true
```

Current repository storage is today-scoped. Cross-midnight continuity is not guaranteed in v0.1.

#### Aggregation

Candidate-level aggregation requires PR9c.

After PR9c:

```text
Recency Momentum = max(item_recency_scores)
```

Before PR9c, Recency Momentum is per primitive item.

#### Debug fields

```text
recency_momentum_score
first_time
last_time
run_time
time_signals_synthetic
run_time_inferred
recency_reason
```

### 12.5 Weak Persistence: 0–5

Purpose:

```text
Weak Persistence lightly rewards topics that remain visible across observations, especially if they are high rank but not moving much.
```

Main fields:

```text
rank_timeline
count
first_time / last_time
```

Only score if currently visible. If not currently visible or no reliable current rank:

```text
0
```

#### rank_timeline scoring

Only when:

```text
has_reliable_rank_timeline == true
```

Rules:

```text
visible in >= 3 observations and latest rank top 20  → 5
visible in >= 3 observations and latest rank top 50  → 4
visible in >= 2 observations and latest rank top 50  → 3
visible in >= 2 observations and latest rank top 100 → 2
otherwise                                           → 0
```

#### count fallback

If no reliable rank_timeline but count exists:

```text
count >= 5 → 3
count >= 3 → 2
count >= 2 → 1
```

But count fallback must remain weak:

```text
count fallback cap = 3
```

Incremental synthetic count may be constant or weak. Availability flags must protect against over-scoring.

#### Aggregation

Candidate-level aggregation requires PR9c.

After PR9c:

```text
Weak Persistence = max(item_persistence_scores)
```

Before PR9c, Weak Persistence is per primitive item.

#### Debug fields

```text
weak_persistence_score
visible_observation_count
latest_rank
count_fallback_used
persistence_reason
```

### 12.6 Expected Behavior Examples

Case A1: re-enters top 10 after previous non-visible observation

```text
Rank Movement: 27
New Burst: 0
Recency Momentum: 4–8
Weak Persistence: 0
Growth Raw: 31–35
```

Case A2: first-ever top 10 observation

```text
Rank Movement: 27 * 0.7 = 18.9
New Burst: 12
Recency Momentum: 8
Weak Persistence: 0
Growth Raw: about 39
```

Case B: single-source low-rank new item

```text
Rank Movement: 3–8
New Burst: 2 * 0.65 = 1.3
Recency Momentum: 2–4
Weak Persistence: 0
Growth Raw: 6–13
```

Case C: from rank 40 to rank 8

```text
Rank Movement: 25
New Burst: 0
Recency Momentum: 4–6
Weak Persistence: 2–3
Growth Raw: 31–34
```

Case D: stable top 5

```text
Rank Movement: 0–3
New Burst: 0
Recency Momentum: 0–2
Weak Persistence: 5
Growth Raw: 5–10
```

Case E: incremental mode without reliable timeline

```text
Rank Movement: unavailable → 0
New Burst: guarded by source_type / first_crawl_of_day / is_new
Recency Momentum: synthetic time cap 3
Weak Persistence: count fallback cap 3
Growth Raw: conservative
```

Case F: first crawl of day

```text
New Burst: 0
Rank Movement: only if reliable prior observation exists
Recency Momentum: synthetic/reliable time rules apply
Current Heat remains available
```

## 13. Current Heat Formula Direction

Current Heat should reflect current visibility.

Target signals include:

```text
current rank
current count / heat
top-N position
source/platform coverage
```

Because source/platform count scales are not directly comparable, v0.1 should prefer simple and explainable normalization.

Rank-based normalization is preferred when raw counts are not comparable.

Target design:

```text
Current Heat should normalize source/platform-specific rank and count scales before aggregation.
```

Implementation constraint:

```text
Avoid building a full per-platform scoring system unless the current repository already provides enough metadata. Prefer simple, explainable normalization first.
```

Current Heat v0.1 likely uses:

```text
rank/top-N normalized score
distinct source coverage
capped same-group item count
small is_new / recency tie-breaker
```

RSS should not contribute rank heat.

## 14. Cross-Evidence Formula Direction

Cross-Evidence Score should measure structure, not truth.

Target signals include:

```text
hotlist + RSS co-occurrence
cross-source appearance
source-tier diversity
background support linked to the same topic cluster
```

Cross-Evidence must not make a low-heat candidate important by itself. It supports escalation when Heat already indicates visibility.

### 14.1 Cross-Evidence v0.1

Before PR9c topic clustering matures, Cross-Evidence v0.1 is weak support.

Allowed v0.1 signals:

```text
hotlist + RSS same keyword/group co-occurrence
source-tier diversity
capped source/evidence count
```

These are not topic-level evidence.

### 14.2 Background Support

Background Support Raw Score remains in the design budget:

```text
Background Support Raw Score: 0–10
```

But it is not implemented in v0.1.

Reason:

```text
current background support is not a stable topic-level data model
forcing it into scoring would create pseudo-context
```

## 15. CR Decision Order

CR Decision calculation order:

```text
1. Build primitive records
2. Build / cluster CR Candidates
3. Score Candidate
4. Compute suppress labels
5. Apply Decision Policy
6. Archive all candidates
7. Text push consumes eligible decisions
```

Decision rule draft:

```text
if suppress label exists:
    decision = suppress
elif total_score >= URGENT_THRESHOLD:
    decision = urgent
elif total_score >= ALERT_THRESHOLD:
    decision = alert
else:
    decision = watch
```

Important rule:

```text
Suppress does not stop scoring.
Suppress only controls presentation and push eligibility.
```

Markdown archive should be able to record:

```text
Profile Version: cr-score-v0.1
Growth Raw Score: ...
Current Heat Raw Score: ...
Heat Score: ...
Cross-layer Raw Score: ...
Background Support Raw Score: ...
Cross-Evidence Score: ...
Total Score: ...
Decision: suppress
Suppress Labels: ...
```

### 15.1 High-score Suppressed Observability

Each CR run should expose high-score suppressed count for observability.

Example:

```text
High-score suppressed candidates: 3
```

This helps detect over-aggressive suppress labels or scoring drift.

This count should appear in CR HTML and CR Markdown. It does not need to appear in Telegram text.

## 16. Runtime State and Terms

### 16.1 quiet

`quiet` means a configured time period where automatic CR-A should not interrupt the user unless the candidate is urgent.

CR-P is manual and is not subject to quiet.

DR follows its scheduled delivery policy and should be scheduled outside quiet periods when possible.

### 16.2 cooldown

`cooldown` means suppressing repeated automatic pushes for the same or similar CR Candidate within a configured interval.

Alert respects cooldown.

Urgent may bypass quiet, but still respects dedupe and minimum cooldown.

### 16.3 minimum cooldown

`minimum cooldown` is the shortest interval during which even urgent should not repeatedly push the same dedupe key.

This prevents urgent topics from spamming Telegram every run.

### 16.4 dedupe key

`dedupe key` is a stable key representing a candidate/event identity for push suppression.

It may be based on:

```text
normalized topic
cluster key
representative title
source/domain
Decision namespace
CR-A event namespace
profile version when necessary
```

### 16.5 alert_state

`alert_state` is runtime state used to remember recent pushed events and enforce cooldown/dedupe.

CR may reuse the concept of alert_state but should avoid reusing old environment alert label semantics directly.

CR alert state should distinguish:

```text
event_type = CR-A
profile_version
decision
dedupe_key
last_sent_at
```

### 16.6 successful CR

A successful CR is a run that produced a valid CR data object and at least one CR artifact.

A CR can be successful even if no CR-A push is sent.

### 16.7 Candidate ordering

Candidate ordering is:

```text
urgent
alert
watch
suppress
```

Within each Decision section, sort by:

```text
total_score descending
Heat Score descending
Current Heat / Growth tie-breakers as defined by the active profile
```

### 16.8 Growth measurement

Growth measurement is profile-defined.

In v0.1 it uses run-local fields and within-day rank_timeline where reliable.

Growth scoring must dampen very low-base growth but must not become a reverse blacklist.

### 16.9 CR-A message part semantics

For multi-message CR-A, `Candidates: N` means the total number of candidates in the CR-A push event, not the number in the current message part.

`Part: i/n` means this Telegram message is part `i` of `n` structured CR-A messages.

## 17. CR HTML

CR HTML is the unified full current artifact.

It uses four Decision sections:

```text
urgent
alert
watch
suppress
```

`suppress` is collapsed by default.

CR HTML is based on the broad candidate pool. It is not limited to pushed candidates.

Each candidate entry should contain:

```text
topic/title
decision
score summary
trigger reasons
short summary
representative link(s)
source/evidence info
```

CR HTML is the expansion layer for CR-A and CR-P.

CR HTML is the default attachment for CR-A and CR-P, subject to configuration.

## 18. CR-A: Current Report Alert

CR-A is the automatic alert push.

Characteristics:

```text
automatic
alert/urgent only
respects quiet
respects cooldown
urgent can bypass quiet
still respects dedupe / minimum cooldown
default attaches CR HTML
attachment configurable
```

CR-A consumes only candidates with Decision:

```text
alert
urgent
```

`suppress` and `watch` never enter CR-A text.

### 18.1 CR-A Text Grammar

CR-A uses structured candidate text.

Template:

```text
Ptilopsis Radar｜CR-A
Run: YYYY-MM-DD HH:mm
Candidates: N

1. Topic title
Decision: urgent
Triggers: high heat; rapid growth; RSS support
Summary: ...
Link: hottest link
```

Rules:

```text
no emoji
system terms in English
hotspot content in native language
no score shown in MVP
future score display allowed
compact trigger labels
one hottest link per Candidate
no boundary note
```

Boundary notes should not appear in runtime text or HTML. The assumption that Ptilopsis Radar tracks information-environment movement rather than factual confirmation is a system-level principle, not repeated in every output.

### 18.2 Multi-message CR-A

Target design: CR-A supports structured multi-message delivery.

This is not generic text splitting. Each part must be a complete structured CR-A message.

Each part repeats the full header:

```text
Ptilopsis Radar｜CR-A
Part: 1/3
Run: YYYY-MM-DD HH:mm
Candidates: N
```

Chunking details are an open implementation detail.

No generic text split path should be reintroduced. No silent truncation should hide selected candidates without making the CR HTML the complete expansion layer.

## 19. CR-P: Current Report Pull

CR-P is designed but deferred.

It is included in the design now because it shares the CR Candidate, Decision, HTML, and text grammar with CR-A.

Status:

```text
designed
not implemented in current phase
requires future Telegram bot command runtime
```

### 19.1 Command Shape

Intended command:

```text
/pull current
```

`pull` means retrieving an existing artifact. It must not trigger a new CR run.

Future commands for "run immediately" must use a different verb.

### 19.2 Target Artifact

Default target:

```text
latest successful CR
```

Future extension may support:

```text
/pull current latest
/pull current <timestamp>
```

If `latest` is specified, it must return the latest successful CR artifact, not the latest alert-worthy CR.

### 19.3 Permission

Allowed:

```text
owner chats
command chats
```

Passive receivers do not automatically have command permission.

### 19.4 Runtime Behavior

```text
reply only to requesting chat
not subject to quiet
does not update alert_state
does not affect cooldown
does not affect dedupe
default attaches CR HTML
```

CR-P shares CR-A candidate grammar, with different candidate selection:

```text
CR-A: alert / urgent only
CR-P: watch / alert / urgent
suppress: never enters text
```

## 20. DR: Daily Report

DR is the daily report product.

DR can use AI according to the current project positioning. AI is allowed for AI Brief, daily overview, and topic-level daily interpretation.

DR Telegram text is:

```text
AI Brief + Topics
```

AI Brief is the main content of DR text. MVP directly reuses the existing generated AI overview / AI Brief from DR HTML or the environment newsletter result. A dedicated DR text summarizer can be designed later.

DR and CR share the same underlying source data family, but at different time scales. DR should not be expected to mirror every CR Decision. DR is a daily-scale product that may aggregate, reinterpret, or omit topics according to daily report logic.

### 20.1 DR Text Grammar

Template:

```text
Ptilopsis Radar｜DR
Date: YYYY-MM-DD

AI Brief
{existing AI overview}

Topics
1. Topic A
2. Topic B
3. Topic C

DR HTML: attached
```

Rules:

```text
no emoji
system terms in English
topic content in native language
no Decision in DR text
no links in DR text
```

DR text only lists topic names after AI Brief. Briefs, source links, evidence, and details live in DR HTML.

### 20.2 DR HTML

DR HTML follows daily sections, not CR four-level sections.

Suggested structure:

```text
Mini Dashboard / AI Brief
Key Topics
Background & Evidence
Raw Hotlist / Appendix
```

DR HTML quality rules:

```text
long lists should be collapsed
topic entries must not be title-only
topic entries should include simple brief / introduction
source links must be included in HTML
source links may be collapsed by default
```

### 20.3 DR Fallback

If AI or DR text rendering fails, the system must not fabricate AI conclusions.

Fallback should use system-level English.

Example:

```text
Ptilopsis Radar｜DR
Daily text is temporarily unavailable. DR HTML has been generated and attached when available.
```

DR HTML should still be attached when available.

## 21. Artifact Registry and Path Resolver

The design requires a small artifact/path abstraction.

The product layer should not depend on old internal names such as `dashboard` or `full`.

An `ArtifactRegistry` or `ArtifactPathResolver` should resolve:

```text
CR per-run HTML path
CR per-run Markdown archive path
CR daily consolidated HTML path
DR recent HTML path
DR archive HTML path
latest CR artifact
latest DR artifact
```

This prevents artifact paths from being scattered across report generation, notification sender, and CLI orchestration code.

The first implementation may map product names onto existing path conventions internally, but product-facing code should use:

```text
CR HTML
DR HTML
CR Markdown
DR Archive
CR Archive
```

## 22. Archive and Retention

CR and DR have separate archive models.

### 22.1 Archive Separation

Archive folders should be separated:

```text
archive/
  cr/
  dr/
```

Exact paths may be refined during implementation, but CR Archive and DR Archive must remain conceptually separate.

### 22.2 DR Archive

DR HTML:

```text
one per day
retained permanently
no Markdown in MVP
recent folder keeps latest 30 days
older DR HTML moves to DR Archive
moving to Archive does not alter content or format
```

DR is a daily finished product, so HTML is the permanent DR archive format.

### 22.3 CR Archive

Every CR run generates:

```text
CR HTML
CR Markdown
```

#### CR Markdown

```text
per-run
written directly to CR Archive
permanent
not daily-merged
same candidate ordering as CR HTML
precise audit record for scoring / policy iteration
```

CR Markdown must preserve scoring and decision debug information.

#### CR HTML

```text
per-run
kept as recent artifact for 7 days
used for CR-A / CR-P attachment and recent browsing
after 7 days consolidated by day
after consolidation original per-run HTML is deleted
```

### 22.4 CR Daily HTML Consolidation

Target design: expired CR HTML is consolidated by day.

Consolidated daily CR HTML:

```text
still uses urgent / alert / watch / suppress sections
suppress remains collapsed by default
duplicate / near-duplicate Candidates may be merged
frequency must be preserved
first_seen / last_seen should be preserved
peak_decision should be preserved
```

Duplicate merging is allowed for readability, but per-run Markdown remains the precise audit source.

Archive job should avoid DR generation time and must not block DR generation.

Implementation detail remains open. The target behavior is retained, but first implementation may focus on per-run CR Markdown and recent CR HTML before implementing daily consolidation.

## 23. Attachment Rules

Default:

```text
CR-A: attach CR HTML
CR-P: attach CR HTML
DR: attach DR HTML
```

All attachment defaults are configurable.

Text push success is primary. Attachment failure does not mark the push as failed.

```text
Text push success = push success
Attachment success = enhancement
```

Markdown archive is local archive only and is not sent through Telegram in MVP.

## 24. Configuration Surface

Configuration should be organized by product object.

Example shape:

```yaml
CR:
  SCORING:
    PROFILE_VERSION: "cr-score-v0.1"
    ALERT_THRESHOLD: 60
    URGENT_THRESHOLD: 80

  PUSH:
    CR_A:
      ATTACH_HTML: true

  ARCHIVE:
    RECENT_HTML_DAYS: 7
    CONSOLIDATE_EXPIRED_HTML: true
    MARKDOWN_PER_RUN: true

DR:
  PUSH:
    ATTACH_HTML: true

  ARCHIVE:
    RECENT_HTML_DAYS: 30
    PERMANENT_HTML: true
    MARKDOWN_ENABLED: false
```

Config keys use English uppercase.

CR-P config is not required in the current implementation phase because CR-P is deferred until Telegram bot command runtime exists.

## 25. Future AI-Assisted CR

CR MVP is no-AI.

Future AI participation must not invalidate the no-AI baseline. AI can only be an optional enhancement layer.

Possible future modes:

### 25.1 Additive Scoring

```text
program_score + ai_score = total_score
```

If used, score scale and thresholds must be recalibrated. AI score scale must not be casually chosen because 0–10 and 0–100 have different calibration behavior.

### 25.2 AI Second Review

Program policy produces the baseline decision first.

AI reviewer may suggest:

```text
keep
suppress
upgrade
downgrade
request_more_evidence
```

This mode is useful for handling accidental high scores caused by rigid keyword combinations.

AI failure must not block no-AI CR baseline.

## 26. Known Risks and Open Design Items

### 26.1 Scoring Risks

```text
Concrete Current Heat and Cross-Evidence formulas are still not finalized.
Growth v0.1 is run-local and within-day; it is not true historical growth.
Score profile v0.1 uses calibration numbers that must be tested against archive distribution.
Cross-Evidence Score is escalation support and may strongly affect alert→urgent upgrades.
Heat cap equals urgent threshold intentionally, but this should be monitored.
Raw score redundancy is retained but may need simplification after implementation.
Platform/source normalization may be complex and must be grounded in actual repository fields.
Current Heat v0.1 and Cross-Evidence v0.1 still need separate concrete formula specs before implementation.
```

### 26.2 Adapter Risks

```text
RSS pseudo-rank may pollute rank scoring unless source_type is explicit.
rank sentinels must be normalized before scoring.
first_crawl_of_day must prevent is_new overfire.
incremental synthetic time fields must be marked.
candidate-level aggregation requires clustering.
Candidate-level scoring may combine max sub-scores from different source items after PR9c; this may overstate Growth unless calibrated.
Recency buckets are cadence-bound; minute thresholds approximate how many runs ago an item first appeared.
```

### 26.3 Archive Risks

```text
CR daily HTML consolidation is target design but implementation details remain open.
Duplicate merge must preserve frequency and peak state.
Per-run Markdown is the precise audit source.
```

### 26.4 Message Risks

```text
CR-A structured multi-message delivery is target design.
Chunking details remain open.
No generic text split path should be reintroduced.
```

### 26.5 Remaining Open Items

```text
CRPrimitiveRecord field schema
CRSourceItem field schema
CRCandidate field schema
CRScoreResult field schema
CRDecision field schema
CRDecisionPolicy schema
suppress label set
Candidate clustering algorithm
Current Heat Raw Score formula
Cross-layer Raw Score formula
Background Support Raw Score future design
CR-A multi-message chunking details
CR HTML / Markdown path naming
DR AI Brief source field mapping
CR-P bot command runtime
```

## 27. Suggested Implementation Order

Recommended order:

```text
PR9a: Design manual only

PR9-pre-a: low-cost metadata pass-through
- status: landed directly on master as commit 1b7a342
- preserves source_id / feed_id / RSS metadata
- no CR module
- no scoring
- no Telegram

PR9b: CR primitive model + input adapter
- trendradar/cr/models.py
- trendradar/cr/adapter.py
- trendradar/cr/__init__.py
- CRSourceItem / primitive records
- source_type
- normalized_rank / visibility
- rank sentinel normalization
- first_crawl_of_day flag
- rank_timeline reliability flags
- time synthetic flags
- no scoring
- no decision
- no Telegram

PR9c: CR deterministic clustering + normalization
- normalized title/topic tokens
- cluster_key
- heat-first display title selection
- source item aggregation
- true topic-level CRCandidate
- no scoring if possible

PR9d: CR scoring API
- CRScoringProfile
- CRScoreResult
- Growth Raw v0.1
- Current Heat v0.1
- weak Cross-Evidence v0.1
- candidate-level scoring depends on PR9c clustering output
- Current Heat and Cross-Evidence require concrete v0.1 formula specs before implementation
- no Telegram
- no final push decision

PR9e: CR Decision Policy
- suppress / watch / alert / urgent
- suppress veto
- trigger reasons
- decision ordering
- high-score suppressed observability
- no Telegram

PR9f: ArtifactRegistry / PathResolver
- CR per-run HTML path
- CR per-run Markdown path
- DR recent/archive path
- product-level artifact naming

PR9g: CR-A formatter + delivery adapter
- structured CR-A text
- attach CR HTML
- reuse Telegram delivery/fanout
- do not extend AI realtime branch as decision logic

PR9h: DR Telegram formatter alignment
- AI Brief from existing overview source
- Topics only
- no links in text
- attach DR HTML

Future: CR-P bot runtime
Future: AI-assisted CR review
Future: CR daily HTML consolidation implementation
```

The first implementation target should be a clean CR internal API, not Telegram integration.

CR should be the first new modular boundary in the repository. New CR logic must not be added into the old procedural flow unless it is only called as an external API.
