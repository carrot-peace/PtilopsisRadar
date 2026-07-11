# evidence.md

Phase 2 evidence only. No interpretation. Patterns require 3+ occurrences unless marked insufficient data.

## Process checkpoints

- Started with 523 candidate files after excluding the current audit thread.
- Corpus cutoff: `2026-07-08T16:29:15+08:00` (inclusive).
- After 25 sampled files: 2526 first-150-line records read; raw records discarded after aggregate receipts were retained.

# evidence.md

Phase 2 evidence only. No interpretation. Patterns require 3+ occurrences unless marked insufficient data.

## Scope and guardrails

- Main transcript candidates: 523 files, 380330023 bytes.
- Candidate mtime range: 2025-11-26 18:54:52 +0800 -> 2026-07-08 16:29:11 +0800.
- Sampled files read: 45. Read cap: first 150 lines per sampled file.
- Corpus cutoff: `2026-07-08T16:29:15+08:00` (inclusive).
- Sample mix: Claude Code: 12, Codex active: 18, Codex archived: 15
- Full corpus sweeps used Python regex count/file-match operations; raw logs were not copied here.
- Quotes are short and mechanically redacted for paths, URLs, emails, tokens, and likely secrets.

## Global pattern counts

- config: 103270 matches across 506 files.
- correction: 84557 matches across 504 files.
- delegate: 181847 matches across 523 files.
- deliberation: 195541 matches across 509 files.
- execution: 253258 matches across 512 files.
- frustration: 37414 matches across 433 files.

## 1. Recurring themes - what I return to again and again

- Project/source recurrence: `[name]` appears in 296 candidate files.
- Project/source recurrence: `Codex active` appears in 127 candidate files.
- Project/source recurrence: `Codex archived` appears in 100 candidate files.
- 2025-11-26 18:54:52 +0800 | Codex active | `candidate-0001` | "<environment_context> <cwd>[redacted] <approval_policy>on-request</approval_policy> <sandbox_mode>workspace-write</sandbox_mode> <network_access>restricted</network_access> </en..." | sampled first-150-line project/theme hint
- 2025-11-27 12:15:52 +0800 | Codex active | `candidate-0002` | "<environment_context> <cwd>[redacted] <approval_policy>on-request</approval_policy> <sandbox_mode>workspace-write</sandbox_mode> <network_access>restricted</network_access> </en..." | sampled first-150-line project/theme hint
- 2026-03-11 10:27:09 +0800 | Codex active | `candidate-0003` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> ## Skills A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skill..." | sampled first-150-line project/theme hint
- 2026-05-06 19:02:15 +0800 | Codex active | `candidate-0004` | "<environment_context> <cwd>[redacted] project</cwd> <shell>zsh</shell> <current_date>2026-05-06</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | sampled first-150-line project/theme hint
- 2026-05-06 18:52:30 +0800 | Codex active | `candidate-0005` | "<environment_context> <cwd>[redacted] project</cwd> <shell>zsh</shell> <current_date>2026-05-06</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | sampled first-150-line project/theme hint
- 2026-05-07 09:57:53 +0800 | Codex active | `candidate-0006` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | sampled first-150-line project/theme hint
- 2026-05-07 10:07:57 +0800 | Codex active | `candidate-0007` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | sampled first-150-line project/theme hint
- 2026-05-07 10:03:23 +0800 | Codex active | `candidate-0008` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | sampled first-150-line project/theme hint
- 2026-05-08 10:34:03 +0800 | Codex archived | `candidate-0009` | "<environment_context> <cwd>[redacted] <shell>zsh</shell> <current_date>2026-05-08</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | sampled first-150-line project/theme hint
- 2026-05-08 10:39:11 +0800 | Codex active | `candidate-0010` | "<environment_context> <cwd>[redacted] <shell>zsh</shell> <current_date>2026-05-08</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | sampled first-150-line project/theme hint
- 2026-05-08 10:37:53 +0800 | Codex archived | `candidate-0011` | "<environment_context> <cwd>[redacted] <shell>zsh</shell> <current_date>2026-05-08</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | sampled first-150-line project/theme hint
- 2026-05-20 17:31:16 +0800 | Codex active | `candidate-0037` | "<environment_context> <cwd>[redacted] skill</cwd> <shell>zsh</shell> <current_date>2026-05-20</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | sampled first-150-line project/theme hint

## 2. Abandonment graveyard - what I start and never finish

- 2026-06-05 15:36:59 +0800 -> 2026-06-28 09:44:13 +0800 | Claude Code | `local source [redacted]` | "Claude project 013" | path-derived lifecycle: 201 transcript files, no mtime in final 7 days of corpus
- 2026-05-31 12:35:10 +0800 -> 2026-06-05 17:13:51 +0800 | Claude Code | `local source [redacted]` | "Claude project 015" | path-derived lifecycle: 53 transcript files, no mtime in final 7 days of corpus
- 2026-06-25 09:31:21 +0800 -> 2026-06-26 13:22:06 +0800 | Claude Code | `local source [redacted]` | "Claude project 014" | path-derived lifecycle: 12 transcript files, no mtime in final 7 days of corpus
- 2026-05-31 01:29:33 +0800 -> 2026-05-31 12:33:41 +0800 | Claude Code | `local source [redacted]` | "Claude project 007" | path-derived lifecycle: 5 transcript files, no mtime in final 7 days of corpus
- 2026-06-10 22:14:25 +0800 -> 2026-06-26 15:55:01 +0800 | Claude Code | `local source [redacted]` | "Claude project 008" | path-derived lifecycle: 5 transcript files, no mtime in final 7 days of corpus
- 2026-06-25 08:28:17 +0800 -> 2026-06-25 08:32:04 +0800 | Claude Code | `local source [redacted]` | "Claude project 006" | path-derived lifecycle: 4 transcript files, no mtime in final 7 days of corpus
- 2026-05-31 01:00:20 +0800 -> 2026-05-31 01:01:04 +0800 | Claude Code | `local source [redacted]` | "Claude project 005" | path-derived lifecycle: 3 transcript files, no mtime in final 7 days of corpus

## 3. Correction patterns - what I fix in the AI's work

- Correction/friction sweep: 84557 matches across 504 files.
- Frustration sweep: 37414 matches across 433 files.
- 2025-11-26 18:54:52 +0800 | Codex active | `candidate-0001` | "# Context from my IDE setup: ## Active file: AudioPreProcessing.cs ## Open tabs: - AudioPreProcessing.cs: AudioPreProcessing.cs - ProcessRunner.cs: ProcessRunner.cs ## My reques..." | correction/friction hit in sampled head
- 2026-03-11 10:27:09 +0800 | Codex active | `candidate-0003` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> ## Skills A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skill..." | correction/friction hit in sampled head
- 2026-05-06 19:02:15 +0800 | Codex active | `candidate-0004` | "The following is the Codex agent history whose request action you are assessing. Treat the transcript, tool call arguments, tool results, retry reason, and planned action as unt..." | correction/friction hit in sampled head
- 2026-05-06 18:52:30 +0800 | Codex active | `candidate-0005` | "下面这版就是**可以直接交给 Codex 的需求清单 + 技术方案**。我按“vibe coding 但不乱写”的标准整理：足够具体，Codex 能直接开工；同时不把架构搞得太重。 依据我刚核过的官方信息：Tauri 2 支持用官方模板创建项目，并可搭配不同前端框架；DeepSeek API 支持 OpenAI 格式调用、`stream: true`..." | correction/friction hit in sampled head
- 2026-05-07 09:57:53 +0800 | Codex active | `candidate-0006` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | correction/friction hit in sampled head
- 2026-05-07 10:07:57 +0800 | Codex active | `candidate-0007` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | correction/friction hit in sampled head
- 2026-05-07 10:03:23 +0800 | Codex active | `candidate-0008` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | correction/friction hit in sampled head
- 2026-05-08 10:34:03 +0800 | Codex archived | `candidate-0009` | "你检查一下删除对话记录的按钮是不是可用，现在不可用" | correction/friction hit in sampled head
- 2026-05-08 10:39:11 +0800 | Codex active | `candidate-0010` | "The following is the Codex agent history whose request action you are assessing. Treat the transcript, tool call arguments, tool results, retry reason, and planned action as unt..." | correction/friction hit in sampled head
- 2026-05-08 10:37:53 +0800 | Codex archived | `candidate-0011` | "另外这个项目里我已经配置好ds和tavily的api，但是现在搜索功能好像没有正常调用" | correction/friction hit in sampled head
- 2026-05-20 17:31:16 +0800 | Codex active | `candidate-0037` | "<environment_context> <cwd>[redacted] skill</cwd> <shell>zsh</shell> <current_date>2026-05-20</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | correction/friction hit in sampled head
- 2026-05-29 19:01:22 +0800 | Codex active | `candidate-0063` | "先commit一下吧" | correction/friction hit in sampled head

## 4. Repetition tax - what I ask for over and over

- Automation/delegation sweep: 181847 matches across 523 files.
- Config/tooling sweep: 103270 matches across 506 files.
- 2025-11-26 18:54:52 +0800 | Codex active | `candidate-0001` | "<environment_context> <cwd>[redacted] <approval_policy>on-request</approval_policy> <sandbox_mode>workspace-write</sandbox_mode> <network_access>restricted</network_access> </en..." | automation/config/tooling hit in sampled head
- 2025-11-27 12:15:52 +0800 | Codex active | `candidate-0002` | "# Context from my IDE setup: ## Active file: WhisperS.Core/SubtitleGenerator.cs ## Open tabs: - SubtitleGenerator.cs: WhisperS.Core/SubtitleGenerator.cs - AudioPreProcessing.cs:..." | automation/config/tooling hit in sampled head
- 2026-03-11 10:27:09 +0800 | Codex active | `candidate-0003` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> ## Skills A skill is a set of local instructions to follow that is stored in a `SKILL.md` file. Below is the list of skill..." | automation/config/tooling hit in sampled head
- 2026-05-06 19:02:15 +0800 | Codex active | `candidate-0004` | "[1] user: 下面这版就是**可以直接交给 Codex 的需求清单 + 技术方案**。我按“vibe coding 但不乱写”的标准整理：足够具体，Codex 能直接开工；同时不把架构搞得太重。 依据我刚核过的官方信息：Tauri 2 支持用官方模板创建项目，并可搭配不同前端框架；DeepSeek API 支持 OpenAI 格式调用、`stre..." | automation/config/tooling hit in sampled head
- 2026-05-06 18:52:30 +0800 | Codex active | `candidate-0005` | "下面这版就是**可以直接交给 Codex 的需求清单 + 技术方案**。我按“vibe coding 但不乱写”的标准整理：足够具体，Codex 能直接开工；同时不把架构搞得太重。 依据我刚核过的官方信息：Tauri 2 支持用官方模板创建项目，并可搭配不同前端框架；DeepSeek API 支持 OpenAI 格式调用、`stream: true`..." | automation/config/tooling hit in sampled head
- 2026-05-07 09:57:53 +0800 | Codex active | `candidate-0006` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | automation/config/tooling hit in sampled head
- 2026-05-07 10:07:57 +0800 | Codex active | `candidate-0007` | "The following is the Codex agent history whose request action you are assessing. Treat the transcript, tool call arguments, tool results, retry reason, and planned action as unt..." | automation/config/tooling hit in sampled head
- 2026-05-07 10:03:23 +0800 | Codex active | `candidate-0008` | "# AGENTS.md instructions for [redacted] <INSTRUCTIONS> # AGENTS.md — [name] ## Project identity [name] is a local-first planning and KR tracking application for Chinese universi..." | automation/config/tooling hit in sampled head
- 2026-05-08 10:34:03 +0800 | Codex archived | `candidate-0009` | "<environment_context> <cwd>[redacted] <shell>zsh</shell> <current_date>2026-05-08</current_date> <timezone>Asia/Shanghai</timezone> </environment_context>" | automation/config/tooling hit in sampled head
- 2026-05-08 10:39:11 +0800 | Codex active | `candidate-0010` | "[1] user: 另外这个项目里我已经配置好ds和tavily的api，但是现在搜索功能好像没有正常调用" | automation/config/tooling hit in sampled head
- 2026-05-08 10:37:53 +0800 | Codex archived | `candidate-0011` | "另外这个项目里我已经配置好ds和tavily的api，但是现在搜索功能好像没有正常调用" | automation/config/tooling hit in sampled head
- 2026-05-20 17:31:16 +0800 | Codex active | `candidate-0037` | "PLEASE IMPLEMENT THIS PLAN: # Claude 风格重做版计划 ## Summary - 新建 `marxism-review-site-claude.html`，保留原 `marxism-review-site.html` 不动。 - 不增减、不删改任何正文内容：包括标题、段落、导航文字、markmap 导图文本、表格、折叠..." | automation/config/tooling hit in sampled head

## 5. Rhythm - when I do my best work, when I spiral

- Candidate transcript mtime hour 10:00 has 48 files.
- Candidate transcript mtime hour 22:00 has 48 files.
- Candidate transcript mtime hour 08:00 has 36 files.
- Candidate transcript mtime hour 12:00 has 35 files.
- Candidate transcript mtime hour 17:00 has 31 files.
- Candidate transcript mtime hour 19:00 has 31 files.
- Candidate transcript mtime hour 11:00 has 31 files.
- Candidate transcript mtime hour 15:00 has 30 files.
- Sampled first-150-line timestamp hour 10:00 has 693 records.
- Sampled first-150-line timestamp hour 16:00 has 518 records.
- Sampled first-150-line timestamp hour 18:00 has 486 records.
- Sampled first-150-line timestamp hour 11:00 has 474 records.
- Sampled first-150-line timestamp hour 09:00 has 394 records.
- Sampled first-150-line timestamp hour 12:00 has 348 records.
- Sampled first-150-line timestamp hour 14:00 has 341 records.
- Sampled first-150-line timestamp hour 19:00 has 296 records.
- Sampled first-150-line timestamp hour 15:00 has 201 records.
- Sampled first-150-line timestamp hour 13:00 has 169 records.
- Sampled first-150-line timestamp hour 17:00 has 150 records.
- Sampled first-150-line timestamp hour 20:00 has 150 records.
- Sampled first-150-line timestamp hour 07:00 has 149 records.
- Sampled first-150-line timestamp hour 01:00 has 63 records.
- Sampled first-150-line timestamp hour 08:00 has 17 records.
- Sampled first-150-line timestamp hour 23:00 has 12 records.
- Sampled first-150-line timestamp hour 22:00 has 12 records.
- 2025-11-27 12:15:52 +0800 | Codex active | `candidate-0002` | "sample reached 150-line cap at 2025-11-27 12:15:52 +0800" | long session head reached read cap
- 2026-03-11 10:27:09 +0800 | Codex active | `candidate-0003` | "sample reached 150-line cap at 2026-03-11 10:27:09 +0800" | long session head reached read cap
- 2026-05-06 19:02:15 +0800 | Codex active | `candidate-0004` | "sample reached 150-line cap at 2026-05-06 19:02:15 +0800" | long session head reached read cap
- 2026-05-06 18:52:30 +0800 | Codex active | `candidate-0005` | "sample reached 150-line cap at 2026-05-06 18:52:30 +0800" | long session head reached read cap
- 2026-05-07 10:07:57 +0800 | Codex active | `candidate-0007` | "sample reached 150-line cap at 2026-05-07 10:07:57 +0800" | long session head reached read cap
- 2026-05-07 10:03:23 +0800 | Codex active | `candidate-0008` | "sample reached 150-line cap at 2026-05-07 10:03:23 +0800" | long session head reached read cap
- 2026-05-08 10:34:03 +0800 | Codex archived | `candidate-0009` | "sample reached 150-line cap at 2026-05-08 10:34:03 +0800" | long session head reached read cap
- 2026-05-08 10:37:53 +0800 | Codex archived | `candidate-0011` | "sample reached 150-line cap at 2026-05-08 10:37:53 +0800" | long session head reached read cap
- 2026-05-20 17:31:16 +0800 | Codex active | `candidate-0037` | "sample reached 150-line cap at 2026-05-20 17:31:16 +0800" | long session head reached read cap
- 2026-06-05 16:01:21 +0800 | Claude Code | `candidate-0168` | "sample reached 150-line cap at 2026-06-05 16:01:21 +0800" | long session head reached read cap
- 2026-06-06 20:06:41 +0800 | Claude Code | `candidate-0220` | "sample reached 150-line cap at 2026-06-06 20:06:41 +0800" | long session head reached read cap
- 2026-06-10 11:39:43 +0800 | Claude Code | `candidate-0246` | "sample reached 150-line cap at 2026-06-10 11:39:43 +0800" | long session head reached read cap

## 6. Blind spots - conspicuously absent

- 2026-07-08 16:29:11 +0800 | all sources | `candidate manifest` | "low-frequency terms recorded in section intro" | absence is counted via full-corpus Python regex sweeps

## Sampled files

- 2025-11-26 18:54:52 +0800 | Codex active | `candidate-0001` | 129845 bytes
- 2025-11-27 13:31:40 +0800 | Codex active | `candidate-0002` | 391469 bytes
- 2026-03-11 17:01:25 +0800 | Codex active | `candidate-0003` | 799955 bytes
- 2026-05-06 19:24:43 +0800 | Codex active | `candidate-0004` | 611480 bytes
- 2026-05-06 19:41:31 +0800 | Codex active | `candidate-0005` | 3551704 bytes
- 2026-05-07 09:57:53 +0800 | Codex active | `candidate-0006` | 92677 bytes
- 2026-05-07 10:10:10 +0800 | Codex active | `candidate-0007` | 706586 bytes
- 2026-05-07 10:10:31 +0800 | Codex active | `candidate-0008` | 595826 bytes
- 2026-05-08 10:35:04 +0800 | Codex archived | `candidate-0009` | 359462 bytes
- 2026-05-08 10:39:11 +0800 | Codex active | `candidate-0010` | 139046 bytes
- 2026-05-08 10:40:06 +0800 | Codex archived | `candidate-0011` | 325848 bytes
- 2026-05-20 18:47:20 +0800 | Codex active | `candidate-0037` | 1296296 bytes
- 2026-05-29 19:01:22 +0800 | Codex active | `candidate-0063` | 127419 bytes
- 2026-05-31 12:21:24 +0800 | Claude Code | `candidate-0089` | 7210 bytes
- 2026-06-04 12:59:10 +0800 | Codex active | `candidate-0116` | 171294 bytes
- 2026-06-04 23:53:44 +0800 | Claude Code | `candidate-0142` | 40315 bytes
- 2026-06-05 18:29:39 +0800 | Claude Code | `candidate-0168` | 2021203 bytes
- 2026-06-06 15:21:42 +0800 | Claude Code | `candidate-0194` | 230 bytes
- 2026-06-06 20:08:55 +0800 | Claude Code | `candidate-0220` | 507041 bytes
- 2026-06-10 15:30:45 +0800 | Claude Code | `candidate-0246` | 1185009 bytes
- 2026-06-12 18:34:34 +0800 | Codex active | `candidate-0273` | 237048 bytes
- 2026-06-17 14:39:24 +0800 | Claude Code | `candidate-0299` | 1806498 bytes
- 2026-06-18 07:25:26 +0800 | Codex archived | `candidate-0325` | 1087237 bytes
- 2026-06-19 01:53:24 +0800 | Claude Code | `candidate-0351` | 53192 bytes
- 2026-06-19 22:34:48 +0800 | Claude Code | `candidate-0377` | 31942 bytes
- 2026-06-20 09:48:03 +0800 | Claude Code | `candidate-0403` | 355815 bytes
- 2026-06-25 08:28:17 +0800 | Claude Code | `candidate-0430` | 10041 bytes
- 2026-06-26 13:22:06 +0800 | Claude Code | `candidate-0456` | 1465868 bytes
- 2026-07-02 16:38:43 +0800 | Codex archived | `candidate-0482` | 339229 bytes
- 2026-07-06 13:38:53 +0800 | Codex archived | `candidate-0508` | 1492446 bytes
- 2026-07-06 14:14:12 +0800 | Codex archived | `candidate-0509` | 283138 bytes
- 2026-07-07 11:24:00 +0800 | Codex archived | `candidate-0510` | 202073 bytes
- 2026-07-07 11:25:52 +0800 | Codex archived | `candidate-0511` | 364193 bytes
- 2026-07-07 14:43:49 +0800 | Codex archived | `candidate-0512` | 396237 bytes
- 2026-07-07 16:55:30 +0800 | Codex archived | `candidate-0513` | 542336 bytes
- 2026-07-08 09:29:07 +0800 | Codex archived | `candidate-0514` | 243148 bytes
- 2026-07-08 09:31:52 +0800 | Codex archived | `candidate-0515` | 75965 bytes
- 2026-07-08 09:54:31 +0800 | Codex archived | `candidate-0516` | 488546 bytes
- 2026-07-08 10:12:57 +0800 | Codex active | `candidate-0517` | 90367 bytes
- 2026-07-08 12:54:32 +0800 | Codex active | `candidate-0518` | 254003 bytes
- 2026-07-08 12:56:32 +0800 | Codex archived | `candidate-0519` | 581007 bytes
- 2026-07-08 14:12:04 +0800 | Codex active | `candidate-0520` | 119853 bytes
- 2026-07-08 14:12:30 +0800 | Codex archived | `candidate-0521` | 676972 bytes
- 2026-07-08 16:08:09 +0800 | Codex active | `candidate-0522` | 515624 bytes
- 2026-07-08 16:29:11 +0800 | Codex active | `candidate-0523` | 499914 bytes
