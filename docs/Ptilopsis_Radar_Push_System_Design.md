# Ptilopsis Radar Push System Design

Status: design draft  
Version: v0.3  
Scope: Telegram-first push system, CR/DR product model, archive model, CR scoring boundary, scoring formula status, implementation feasibility review incorporated

## 1. Product Boundary

Ptilopsis Radar 的推送系统不是普通的通知出口，而是项目与用户交互的核心界面。

HTML、Markdown、Archive 是展开层、留档层、复盘层；Telegram text 是系统主动触达用户的主要方式。因此本系统的核心目标不是“把报告发出去”，而是：

```text
在合适的时间，用足够克制、足够解释性的文本，告诉用户：
- 是否有值得现在关注的信息环境变化；
- 为什么这条内容值得被推送；
- 如果需要展开，应查看哪一份 HTML artifact；
- 系统不把热度、关键词命中、证据结构等同于事实确认。
```

Current phase focuses on push design, not data collection.

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

The repository has recently been cleaned up toward canonical output. The target baseline assumes the PR6–PR8 cleanup direction:

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

Every CR run produces:

```text
CR Candidate set
CR ScoreResult set
CR Decision set
CR HTML
CR Markdown
optional CR-A text
future CR-P text
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

## 5. CR Candidate Model

CR Candidate is the unit of current report evaluation.

A CR Candidate is not necessarily a verified real-world event. It is a topic-level information cluster built from one CR run.

Candidate generation uses mixed internal recall but topic-level user presentation.

Inputs may include:

```text
rewritten keyword hits
hotlist items
RSS items
source/evidence metadata
run-to-run deltas
title/topic similarity
```

User-facing presentation must not expose raw keyword groups as the main title. Keywords are recall and scoring inputs, not the primary display unit.

Candidate display name rule:

```text
Choose the hottest / most prominent topic or title inside the topic cluster.
```

Heat has priority over source credibility when selecting the visible topic name. This reflects the project’s purpose: Ptilopsis Radar tracks information-environment movement. Even if a high-heat topic later turns out to be false, its spread is still meaningful as an information signal.

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

## 6. CR Input Adapter

CR requires a dedicated input adapter before scoring.

Existing repository data such as hotlist stats, RSS stats, title dictionaries, new title metadata, rank/count/time fields, and source/evidence metadata must be normalized into CR-specific models.

The CR Input Adapter consumes existing canonical run data and produces preliminary `CRCandidate` objects or candidate input records.

It must not:

```text
score candidates
decide suppress/watch/alert/urgent
render Telegram text
write HTML or Markdown
send notifications
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
CRCandidate input records with stable IDs, source/title data, candidate topic fields, representative links, and raw scoring inputs where available.
```

Current repository stats are not the CR Candidate model. They are source data for the adapter.

## 7. CR Decision Levels

CR uses four Decision levels:

```text
suppress
watch
alert
urgent
```

### 7.1 suppress

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

### 7.2 watch

`watch` means the candidate is visible and has observation value, but is not worth actively interrupting the user.

Meaning:

```text
visible in CR HTML
eligible for CR-P in future
no automatic push
```

### 7.3 alert

`alert` means the candidate is eligible for automatic CR-A push.

Meaning:

```text
eligible for CR-A
respects quiet
respects cooldown
```

Alert is primarily driven by high heat or rapid growth. It does not require factual verification or cross-layer confirmation.

### 7.4 urgent

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

## 8. CR Scoring Architecture

CR scoring must be an independent internal API.

The intended flow:

```text
Candidate Builder
→ Scoring API
→ Decision Policy
→ Presentation Layer
→ Delivery Layer
```

### 8.1 Candidate Builder

Candidate Builder constructs CR Candidates from canonical run data.

It does not decide push eligibility. It only produces candidate objects.

### 8.2 Scoring API

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

### 8.3 Decision Policy

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

### 8.4 Presentation Layer

Presentation Layer renders:

```text
CR-A text
CR-P text
CR HTML
CR Markdown
```

It consumes Candidate + ScoreResult + Decision. It must not recompute scores.

### 8.5 Delivery Layer

Delivery Layer sends:

```text
Telegram text
optional HTML attachment
```

It must not compute scores or decide push eligibility.

## 9. CR Score Profile v0.1 Draft: Score Budget and Decision Shape

This is an initial calibration profile, not a permanent product law.

This section defines score components, component caps, and decision thresholds. It does not fully define the concrete scoring formulas.

Concrete formulas depend on CR Input Adapter field availability and must be finalized after a repository field audit.

Concrete thresholds and weights may change after historical CR archive review. The profile must be versioned.

### 9.1 Score Structure

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

### 9.2 Heat Score

Heat Score is the primary decision driver.

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

### 9.3 Cross-Evidence Score

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

### 9.4 Heat Cap and Urgent Threshold

In profile v0.1, Heat Score cap equals the urgent threshold by design.

```text
Heat Score cap = 80
Urgent threshold = 80
```

This is intentional.

Maximum Heat Score alone can produce urgent because CR is a heat-first information-environment radar. Cross-Evidence is not required for the hottest tier.

### 9.5 Thresholds

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

### 9.6 Formula Status

CR Score Profile v0.1 defines score budgets, caps, and decision thresholds. It does not yet define final concrete scoring formulas.

Formula design is a separate step before implementation and must be based on repository field availability.

### 9.7 Growth Formula Direction

Growth should compare the current run against both the previous run and a recent rolling baseline.

Temporary baseline design:

```text
growth_baseline = 0.4 * previous_run_value + 0.6 * recent_3_run_average
```

If recent 3-run history is unavailable, the formula should degrade to previous-run comparison. If previous-run data is also unavailable, growth scoring should be conservative.

Design target:

```text
Growth should consider both rank movement and count/heat delta.
```

Implementation constraint:

```text
v0.1 must use fields currently available in the repository. If rank movement or count/heat delta is unavailable or unreliable, the formula should degrade gracefully rather than forcing a large data-layer rewrite.
```

### 9.8 Low-base Dampening

Growth scoring must dampen very low-base ratio growth.

Low-base candidates must not be hard-blocked. A strong rank jump, cross-source appearance, or other visibility signal may still produce a high Growth Raw Score.

### 9.9 Current Heat Formula Direction

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

### 9.10 Cross-Evidence Formula Direction

Cross-Evidence Score should measure structure, not truth.

Target signals include:

```text
hotlist + RSS co-occurrence
cross-source appearance
source-tier diversity
background support linked to the same topic cluster
```

Cross-Evidence must not make a low-heat candidate important by itself. It supports escalation when Heat already indicates visibility.

### 9.11 Field Audit Requirement

Before implementing CR Scoring Formula v0.1, PR9b must audit which fields are available from current repository data structures.

The audit should classify each field by:

```text
source location
available modes
available source types
stability
candidate-level availability
usable score component
fallback behavior
```

Candidate fields to audit include, but are not limited to:

```text
rank
count
first_time
last_time
is_new
rank_timeline
source_name
url
rss_published_at
keyword_group
source_tier
evidence_count
previous_run_value
recent_3_run_average
```

### 9.12 Calibration Warning

The numbers in profile v0.1 are calibration defaults, not permanent product law.

Future calibration should avoid overfitting to a small set of historical cases. Calibration should also evaluate distribution shape, such as:

```text
How often does urgent occur?
How often does alert occur?
How many high-score candidates are suppressed?
How often does low-base growth overfire?
How often does a high-heat topic fail to reach alert?
```

## 10. CR Decision Order

CR Decision calculation order:

```text
1. Build CRCandidate
2. Score Candidate
3. Compute suppress labels
4. Apply Decision Policy
5. Archive all candidates
6. Text push consumes eligible decisions
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

### 10.1 High-score Suppressed Observability

Each CR run should expose high-score suppressed count for observability.

Example:

```text
High-score suppressed candidates: 3
```

This helps detect over-aggressive suppress labels or scoring drift.

This count should appear in CR HTML and CR Markdown. It does not need to appear in Telegram text.

## 11. Runtime State and Terms

### 11.1 quiet

`quiet` means a configured time period where automatic CR-A should not interrupt the user unless the candidate is urgent.

CR-P is manual and is not subject to quiet.

DR follows its scheduled delivery policy and should be scheduled outside quiet periods when possible.

### 11.2 cooldown

`cooldown` means suppressing repeated automatic pushes for the same or similar CR Candidate within a configured interval.

Alert respects cooldown.

Urgent may bypass quiet, but still respects dedupe and minimum cooldown.

### 11.3 minimum cooldown

`minimum cooldown` is the shortest interval during which even urgent should not repeatedly push the same dedupe key.

This prevents urgent topics from spamming Telegram every run.

### 11.4 dedupe key

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

### 11.5 alert_state

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

### 11.6 successful CR

A successful CR is a run that produced a valid CR data object and at least one CR artifact.

A CR can be successful even if no CR-A push is sent.

### 11.7 Candidate ordering

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

### 11.8 Growth measurement

Growth measurement is profile-defined.

It should consider current run, previous run, and/or a rolling window depending on available data.

Growth scoring must dampen very low-base growth.

### 11.9 CR-A message part semantics

For multi-message CR-A, `Candidates: N` means the total number of candidates in the CR-A push event, not the number in the current message part.

`Part: i/n` means this Telegram message is part `i` of `n` structured CR-A messages.

## 12. CR HTML

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

## 13. CR-A: Current Report Alert

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

### 13.1 CR-A Text Grammar

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

### 13.2 Multi-message CR-A

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

## 14. CR-P: Current Report Pull

CR-P is designed but deferred.

It is included in the design now because it shares the CR Candidate, Decision, HTML, and text grammar with CR-A.

Status:

```text
designed
not implemented in current phase
requires future Telegram bot command runtime
```

### 14.1 Command Shape

Intended command:

```text
/pull current
```

`pull` means retrieving an existing artifact. It must not trigger a new CR run.

Future commands for “run immediately” must use a different verb.

### 14.2 Target Artifact

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

### 14.3 Permission

Allowed:

```text
owner chats
command chats
```

Passive receivers do not automatically have command permission.

### 14.4 Runtime Behavior

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

## 15. DR: Daily Report

DR is the daily report product.

DR can use AI according to the current project positioning. AI is allowed for AI Brief, daily overview, and topic-level daily interpretation.

DR Telegram text is:

```text
AI Brief + Topics
```

AI Brief is the main content of DR text. MVP directly reuses the existing generated AI overview / AI Brief from DR HTML or the environment newsletter result. A dedicated DR text summarizer can be designed later.

DR and CR share the same underlying source data family, but at different time scales. DR should not be expected to mirror every CR Decision. DR is a daily-scale product that may aggregate, reinterpret, or omit topics according to daily report logic.

### 15.1 DR Text Grammar

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

### 15.2 DR HTML

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

### 15.3 DR Fallback

If AI or DR text rendering fails, the system must not fabricate AI conclusions.

Fallback should use system-level English.

Example:

```text
Ptilopsis Radar｜DR
Daily text is temporarily unavailable. DR HTML has been generated and attached when available.
```

DR HTML should still be attached when available.

## 16. Artifact Registry and Path Resolver

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

## 17. Archive and Retention

CR and DR have separate archive models.

### 17.1 Archive Separation

Archive folders should be separated:

```text
archive/
  cr/
  dr/
```

Exact paths may be refined during implementation, but CR Archive and DR Archive must remain conceptually separate.

### 17.2 DR Archive

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

### 17.3 CR Archive

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

### 17.4 CR Daily HTML Consolidation

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

## 18. Attachment Rules

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

## 19. Configuration Surface

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

## 20. Future AI-Assisted CR

CR MVP is no-AI.

Future AI participation must not invalidate the no-AI baseline. AI can only be an optional enhancement layer.

Possible future modes:

### 20.1 Additive Scoring

```text
program_score + ai_score = total_score
```

If used, score scale and thresholds must be recalibrated. AI score scale must not be casually chosen because 0–10 and 0–100 have different calibration behavior.

### 20.2 AI Second Review

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

## 21. Known Risks and Open Design Items

### 21.1 Scoring Risks

```text
Concrete scoring formulas are not finalized.
Growth formula may over-score low-base growth.
Score profile v0.1 uses calibration numbers that must be tested against archive distribution.
Cross-Evidence Score is escalation support and may strongly affect alert→urgent upgrades.
Heat cap equals urgent threshold intentionally, but this should be monitored.
Raw score redundancy is retained but may need simplification after implementation.
Platform/source normalization may be complex and must be grounded in actual repository fields.
```

### 21.2 Archive Risks

```text
CR daily HTML consolidation is target design but implementation details remain open.
Duplicate merge must preserve frequency and peak state.
Per-run Markdown is the precise audit source.
```

### 21.3 Message Risks

```text
CR-A structured multi-message delivery is target design.
Chunking details remain open.
No generic text split path should be reintroduced.
```

### 21.4 Remaining Open Items

```text
CRCandidate field schema
CRScoreResult field schema
CRDecision field schema
CRDecisionPolicy schema
suppress label set
Candidate clustering algorithm
Growth Raw Score formula
Current Heat Raw Score formula
Cross-layer Raw Score formula
Background Support Raw Score formula
CR-A multi-message chunking details
CR HTML / Markdown path naming
DR AI Brief source field mapping
CR-P bot command runtime
```

## 22. Suggested Implementation Order

Recommended order:

```text
PR9a: Design manual only

PR9b: CR domain model + input adapter + scoring field audit
- CRCandidate
- CRRunContext
- adapter from existing stats/rss/new_titles/title_info
- field availability audit for future scoring formula
- no scoring
- no Telegram

PR9c: CR deterministic clustering + normalization
- normalized title/topic tokens
- cluster_key
- heat-first display title selection
- no scoring

PR9d: CR scoring API
- CRScoringProfile
- CRScoreResult
- concrete formula based on PR9b field audit
- capped Heat / Cross-Evidence score profile
- low-base growth dampening requirement
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
