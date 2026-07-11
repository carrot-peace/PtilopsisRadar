# CR-A Hotspot Event Lifecycle Management — Design

Design-only document. No runtime behavior changes are proposed here. This
records the agreed goals, the implementation path, the coupling points we must
resolve, and how we resolve them. Implementation starts with **J1** (a pure
predicate module) after this document is accepted.

Companion docs: [`cr-a-operator-runbook.md`](cr-a-operator-runbook.md),
[`cr-a-rollback-guide.md`](cr-a-rollback-guide.md).

---

## 0. Problem statement

CR-A hotspot events today have only **enter / refresh**, never **exit**. Three
persistent surfaces grow without bound:

1. **`output/cr/state/cr_dispatch_state.json`** (event-state snapshot) —
   [`merge_cr_event_state_entries`](../trendradar/cr/state_snapshot.py) keeps
   `previous.entries + updates` deduped by `event_key` and **never deletes a
   key**. Cooldown "expiry"
   ([`cooldown_enforce.py`](../trendradar/cr/cooldown_enforce.py)) only
   re-allows dispatch; it does not evict the entry. There is **no TTL / prune /
   eviction anywhere** in the CR module. Every distinct event ever seen in
   `live` mode is a permanent entry. **Each `live` run reads the whole file,
   canonicalizes (sorts all keys), and rewrites it — per-run cost grows with the
   cumulative distinct-event count.** This is the load-bearing problem.
2. **Archive directories** — `output/cr/archive/{markdown,html,dispatch_plan,
   dispatch_receipts}/` and `output/meta/deploy_trace/archive/` each receive one
   file per run, keyed by run label. The writer explicitly does **no retention
   cleanup** ([`artifacts.py`](../trendradar/cr/artifacts.py)). ~5 files/run,
   forever. Inert (does not slow a run) but unbounded on disk.
3. **`output/cr/state/cr_deferred_dispatch_queue.json`** — self-limiting in the
   common case (accepted entries removed, deduped by `event_key`), but
   `failed_transport` / `not_configured` / `rejected` entries are retained with
   no retry cap or expiry, so they accumulate under sustained failure.

"Lifecycle management" gives each event an **exit**.

---

## 1. Goals — and whether they are reasonable

| Goal | Verdict | Note |
| --- | --- | --- |
| **G1 — Explicit lifecycle** | 🟡 **Trimmed** | A full state machine (NEW/ACTIVE/COOLING/DORMANT/EXPIRED) is gold-plating. The only question that drives an action is "**is this entry evictable?**". Reduced to: one `is_evictable` predicate + one descriptive label for observability. No FSM. |
| **G2 — Bounded state file** | 🟢 **Load-bearing** | The only goal with a performance payoff. Bounds the event-state file to a time window instead of all-time. |
| **G3 — Bounded per-run archives, long-term event history** | 🟢 Reasonable, **deferred** | Per-run archives are inert "death debt" but grow unbounded. Upgraded from simple retention to **compaction + retention**: weekly event-level rollup preserves long-term history; per-run archives are cleaned only after rollup coverage. Does not slow runs; compounding risk is low but nonzero over months. |
| **G4 — Bounded deferred queue** | 🟢 Reasonable, **deferred** | Self-limiting in the common case; only matters under sustained transport failure. |
| **G5 — Zero behavior regression** | 🔴 **Non-negotiable red line** | Evicting a still-cooling event = duplicate alert. Every design choice bends around this. |
| **G6 — Default-safe, gated, preview-first** | 🟢 Reasonable | Follows the A1–A8 discipline. `preview` → `enforce`. Default off = current behavior. |
| **G7 — Observable** | 🟢 Reasonable, **right-sized** | The janitor writes its **own** report file. It does **not** touch the `deploy_trace` schema (respects the A8 hard boundary). |

Net: directions are sound. G1 is reduced from a state machine to a predicate +
label. G3/G4 are kept as goals but deferred. **G2 is the load-bearing goal,
guarded by G5.**

### Known, accepted limitation

TTL eviction bounds the file by **time**, not by **count**. It eliminates
all-time monotonic growth (≈95% of the problem) but does not impose a hard size
cap; within the TTL window a spike in event rate can still produce a large file.
A `MAX_ENTRIES` count-cap is intentionally **not** built now (it would turn the
predicate from "time" into "time ∪ ranked-eviction" for marginal benefit). It is
left as a future knob.

---

## 2. Architecture — out-of-band janitor

Lifecycle management is an **independently-runnable package tool** at
`trendradar.cr.lifecycle_runner`.  The legacy
[`scripts/cr_a_lifecycle.py`](../scripts/cr_a_lifecycle.py) command is a thin
compatibility wrapper.  The package tool talks only to the **versioned file
contracts** (`cr-event-state-v1`, `cr-deferred-dispatch-queue-v1`, archive
directories) and is never inlined within `runtime_dry_run.py`.

```
              reads/writes versioned JSON contracts (public load/save boundary)
                              │
   ┌──────────────┐          ▼            ┌─────────────────────────────┐
   │ J1 pure       │   cr_dispatch_state  │ J2 janitor (composition root)│
   │ is_evictable  │◀── ttl_for_level ────│  - load (public)             │
   │ (zero imports)│   injected param     │  - filter via J1             │
   └──────────────┘                       │  - preview report OR save    │
                                          └─────────────────────────────┘
```

Why this shape:

- The CR-A dispatch hot path (`runtime_dry_run.py`) is **untouched** — solving
  coupling point **A** by construction.
- The janitor depends on **what the files look like** (schema versions exist
  exactly for this), not on **how the code is written**.
- Fail-closed is inherent: if the janitor breaks, dispatch is unaffected.
- It is a leaf: nothing depends on it, so future changes to lifecycle policy
  touch only the janitor + J1.

---

## 3. The two operating decisions

### Decision 1 — Trigger: call once after the main run

Chosen over an independent cron.

- **Avoids a two-writer race.** The event-state file grows only in `live` runs.
  An independent cron would create a second writer to
  `cr_dispatch_state.json`; with `os.replace` last-writer-wins, that silently
  loses an update — reintroducing a data-safety hole right after we guarded G5.
  The post-run call is a **single writer**.
- **Cadence aligns naturally.** Lifecycle runs right after the run that grew the
  file; when CR-A is `off`, the file does not grow and the janitor need not run.
- **Cost is one removable line** calling the janitor's public entrypoint —
  *trigger* coupling, not *logic* coupling. Precedent exists: the deploy-trace
  writer is wired the same way, wrapped fail-closed
  ([`__main__.py` deploy-trace call](../trendradar/__main__.py)).
- **Superset:** the janitor remains runnable by hand; the post-run call only
  adds an automatic trigger.

Mandatory: the call is **gated and fail-closed**, and is a **no-op when
lifecycle is unconfigured**, so adding the line is behavior-neutral until an
operator opts in.

### Decision 2 — TTL basis: `ttl = max(cooldown, TTL_FLOOR)`, adaptive

Chosen over a fixed number of days. (Note: the cooldown policy is a single
scalar `same_level_cooldown_minutes = 60`,
[`cooldown_policy.py`](../trendradar/cr/cooldown_policy.py); it does not connect
to `config.yaml`.)

- Because cooldown ≈ 60 min, it is a trivially small safety floor. The knob that
  actually sizes the file is **`TTL_FLOOR` = the memory window**, and in
  practice `max(cooldown, FLOOR)` ≈ `FLOOR`. The cooldown term is a
  **correctness belt**: even a mis-set tiny FLOOR cannot violate G5.
- Adaptive makes the red line **true by construction** — you cannot configure
  `ttl < cooldown`. A fixed value would require a human to re-verify
  `fixed ≥ cooldown` every time cooldown changes (the silent landmine again).
- `TTL_FLOOR` has a clear operator-facing meaning: *"after how long dormant does
  a re-appearing event count as NEW rather than a repeat?"*

Default `TTL_FLOOR = 7 days`: long enough that an event reappearing within a
week is still recognized as repeat/escalation; short enough to kill all-time
growth. This is a **starting point** — J2's `preview` mode lists what *would* be
evicted so the operator can tune against real dormancy data (G6).

---

## 4. Coupling points — which we must resolve, and how

| Point | Status | Resolution |
| --- | --- | --- |
| **A** — janitor inlined into `runtime_dry_run` | 🔴 **Must solve** | Solved by *form*: standalone tool over versioned file contracts; never imported by runtime. The one allowed concession is the post-run trigger line (trigger, not logic). |
| **B** — eviction predicate needs cooldown values | 🔴 **Must solve correctly** | Guards G5, so it cannot be "decouple and guess". Solved by **dependency injection** — see below. |
| **C** — reaching into private `_canonical_entries` | ⚪ Does not arise | J1 filters the public `snapshot.entries` tuple and builds a new `CREventStateSnapshot`; the public `save_cr_event_state_snapshot` canonicalizes internally. No private access. |
| **E** — modifying `deferred_queue.py` | ⚪ Does not arise | J4 expires stale entries via the existing public `remove_deferred_entries` + public load/save. The module is not modified. |
| **F** — adding fields to `deploy_trace` schema | ⚪ Does not arise | The janitor writes its **own** report file. `deploy_trace` is untouched. |
| **D** — archive compaction + retention needs archive path layouts and per-run artifact discovery | ⚪ **Deferred** | J3a (weekly rollup) reads per-run archive directories to aggregate by `event_key`; J3b (retention) deletes per-run files only after rollup coverage. Both stay at public directory boundaries; no module internals touched. Deferred safely — non-compounding until months of accumulation. |

So the **only** coupling we actively solve is **A** (by form) and **B** (by
injection). C/E/F vanish if the janitor stays at public boundaries and writes
its own report; D is deferred safely.

### How B is resolved — injection at the composition root

```python
# J1 — pure, zero imports. Lifecycle logic is unaware cooldown exists.
def is_evictable(entry, *, now, ttl_for_level) -> bool:
    # G5 encoded here: age(now - seen_at) must exceed ttl for the entry's level.
    ...

# J2 janitor — composition root. The ONE wire to cooldown lives here, explicit.
ttl_for_level = {level: max(cooldown_seconds(level), TTL_FLOOR_SECONDS)
                 for level in levels}        # from public DEFAULT_CR_COOLDOWN_POLICY
is_evictable(entry, now=now, ttl_for_level=ttl_for_level)
```

- **J1 imports nothing from cooldown** — it receives a `level → seconds` map. It
  is testable in complete isolation (which *is* the proof of decoupling).
- **B lives on a single explicit line** in the janitor. If cooldown changes,
  that one wire changes — not the logic.
- **G5 is provable, not hand-waved:** if `ttl ≥ cooldown` for every level, an
  evicted entry's cooldown is already expired, so its next appearance would be
  `allow_new` regardless — eviction is decision-neutral.
- **Mechanical guard:** a test asserts `∀ level: ttl_for_level[level] ≥
  cooldown(level)`. The red line is enforced by the test suite, not by memory.

---

## 5. Implementation path (J1–J5)

| Step | Content | Invasion | When |
| --- | --- | --- | --- |
| **J1** | Pure module `trendradar/cr/event_lifecycle.py`: `is_evictable(...)` + `describe_phase(...)` label. Zero imports; TTL injected. Full unit tests in isolation. | **None** (new leaf) | **Now** |
| **J2** | Janitor `trendradar.cr.lifecycle_runner` (with `scripts/cr_a_lifecycle.py` compatibility wrapper): load `cr-event-state-v1` (public) → `preview` (report `would_evict`) or `enforce` (atomic save of pruned snapshot). Builds `ttl_for_level` from public cooldown policy + `TTL_FLOOR`. | **None** (package composition root) | **Now** |
| **J3a** | Weekly event archive rollup — **generate only**. Reads per-run archive artifacts (`cr/archive/{dispatch_plan,dispatch_receipts}/`), aggregates by `event_key` per ISO week, writes `output/cr/archive_weekly/events/YYYY-WNN.json`. Does **not** delete any per-run archive. | Low (reads dir listings + JSON) | **Deferred — non-compounding** |
| **J3b** | Per-run archive retention. Deletes per-run archive files **only** when: (1) the covering weekly rollup exists and records the source run; (2) the per-run archive exceeds the short-term retention window. Never touches `latest/`. Preview-first. | Low (reads dir listings, deletes files) | **After J3a** |
| **J4** | Deferred-queue hygiene: expire entries past `deferred_until` + grace, or cap retries; via public `remove_deferred_entries`; records eviction in a report. | Low (public API only) | **Deferred — non-compounding** |
| **J5** | Observability: janitor emits its own lifecycle report (active / dormant / evicted counts); extend smoke check with a "state not over-bounded" invariant. J5 initially serves J2; its report and smoke-check patterns are reused when J3/J4 land. | None~low (no `deploy_trace` change) | After J2 |

The post-run trigger line (Decision 1) is added when J2 lands, gated and
fail-closed.

### J3a — Weekly event archive rollup

J3a upgrades archive management from simple retention to **compaction**:
per-run archives are short-term raw evidence; weekly rollups are long-term,
event-level, operator-managed archives.

**Directory structure.**

```text
output/cr/archive_weekly/events/
  2026-W24.json
  2026-W25.json
  2026-W26.json
```

This sits alongside the existing `output/cr/archive/` tree. The per-run
archives remain at their current paths; J3a does not move or delete them.

**Weekly rollup schema (`cr-weekly-event-archive-v1`).**

```json
{
  "schema_version": "cr-weekly-event-archive-v1",
  "week": "2026-W25",
  "period_start": "2026-06-15T00:00:00+08:00",
  "period_end": "2026-06-22T00:00:00+08:00",
  "generated_at": "2026-06-22T00:10:00+08:00",
  "source_runs": {
    "count": 336,
    "first_run_label": "incremental-20260615-000501",
    "last_run_label": "daily-20260621-235500"
  },
  "events": [
    {
      "event_key": "...",
      "first_seen_at": "...",
      "last_seen_at": "...",
      "max_level": "urgent",
      "levels_seen": ["alert", "urgent"],
      "titles": ["..."],
      "candidate_ids": ["..."],
      "dispatch_count": 3,
      "accepted_count": 2,
      "deferred_count": 1,
      "receipt_statuses": {
        "accepted": 2,
        "rejected": 0,
        "failed_transport": 1
      },
      "sample_messages": ["..."],
      "source_artifacts": [
        "output/cr/archive/dispatch_plan/incremental-20260615-090000.json",
        "output/cr/archive/dispatch_receipts/incremental-20260615-090000.json"
      ]
    }
  ]
}
```

Key design choices:

- **Aggregated by `event_key`**, not by run. The rollup is an event archive,
  not a run archive. Each event's lifecycle within the week is a single entry.
- **`source_artifacts`** records which per-run archive files contributed to
  this entry. J3b uses this to determine coverage.
- **`source_runs.count`** and labels provide an audit trail back to raw
  evidence.
- **`sample_messages`** retains representative CR-A text for replay/review.
  Full per-run messages remain in the per-run archives until those are
  cleaned.

J3a operates in two modes (gated by config):

- `preview` — lists which weeks *would* be rolled up, reports event counts.
  No files written.
- `generate` — writes the weekly rollup JSON. Existing rollup files for the
  same week are **not** overwritten (idempotent: skip if exists).

J3a does **not** delete any per-run archive. Deletion belongs to J3b.

### J3b — Per-run archive retention

J3b cleans per-run archive files subject to a **coverage precondition**:

```text
delete eligible ⟺ covered_by_weekly_rollup ∧ older_than_retention_window
```

Not merely `older_than_retention_window`. This ensures raw evidence is never
lost before compaction.

Deletion conditions (all must hold):

1. The per-run archive's week has a corresponding weekly rollup file in
   `output/cr/archive_weekly/events/`.
2. That rollup records the run label (or artifact path) in its
   `source_artifacts` / `source_runs`.
3. The per-run archive's mtime exceeds the short-term retention window
   (default 30 days).
4. The file is **not** under any `latest/` directory.
5. Mode is `enforce` (not `preview`).

Safety:

- J3b is **preview-first**: `preview` mode lists every file that *would* be
  deleted, with the covering rollup path. No files are removed.
- J3b reports every deleted file and its covering weekly rollup.
- J3b does **not** delete weekly rollup files. Those are long-term,
  operator-managed archives. If the operator considers them too numerous,
  they manage `output/cr/archive_weekly/` manually.
- J3b does **not** touch `output/cr/latest/` or `output/meta/deploy_trace/latest/`.
- J3b backs up deleted files to a `.bak` sidecar is **not** done — the
  weekly rollup *is* the backup. Deleting without rollup coverage is
  prohibited by construction.

---

## 6. Configuration (all default off = current behavior)

| Variable | Allowed values | Default | Meaning |
| --- | --- | --- | --- |
| `PTILOPSIS_CR_LIFECYCLE_ENABLED` | `1` to enable | unset ⇒ off | Master gate. Off ⇒ janitor is a no-op. |
| `PTILOPSIS_CR_LIFECYCLE_MODE` | `preview`, `enforce` | `preview` | `preview` reports `would_evict` only; `enforce` writes the pruned snapshot. |
| `PTILOPSIS_CR_LIFECYCLE_TTL_FLOOR_DAYS` | positive number | `7` | Memory window. Effective ttl = `max(cooldown, this)`. |
| `PTILOPSIS_CR_ARCHIVE_ROLLUP_ENABLED` | `1` to enable | unset ⇒ off | J3a gate. Off ⇒ weekly rollup is a no-op. |
| `PTILOPSIS_CR_ARCHIVE_ROLLUP_MODE` | `preview`, `generate` | `preview` | `preview` lists weeks that would be rolled up; `generate` writes the rollup JSON. |
| `PTILOPSIS_CR_ARCHIVE_ROLLUP_WEEKLY_DIR` | path | `output/cr/archive_weekly/events` | Output directory for weekly event archive JSON files. |
| `PTILOPSIS_CR_ARCHIVE_RETENTION_ENABLED` | `1` to enable | unset ⇒ off | J3b gate. Off ⇒ per-run archive retention is a no-op. |
| `PTILOPSIS_CR_ARCHIVE_RETENTION_MODE` | `preview`, `enforce` | `preview` | `preview` lists files that would be deleted; `enforce` deletes them. |
| `PTILOPSIS_CR_ARCHIVE_RETENTION_DAYS` | positive number | `30` | Short-term retention window for per-run archives. Files older than this *and* covered by a weekly rollup are eligible for deletion. |
| `PTILOPSIS_CR_ARCHIVE_RETENTION_REQUIRE_ROLLUP` | `1` to require | `1` | When `1`, per-run archives are deleted **only** if a covering weekly rollup exists. When `0`, pure age-based deletion (not recommended — loses the compaction safety guarantee). |

Failure behavior: malformed / unreadable state ⇒ fail-closed (no write).
Invalid config values ⇒ no-op, not a crash of the calling run.

---

## 7. Safety invariants (must hold in tests)

1. `∀ level: ttl_for_level[level] ≥ cooldown(level)` — eviction is
   decision-neutral (G5).
2. `enforce` never writes when the source snapshot failed to load/parse.
3. `preview` writes no state file (report only).
4. An evicted `event_key` is one whose `seen_at` age exceeds its ttl; entries
   without a parseable `seen_at` are **kept** (fail-safe, never evicted).
5. Disabled / unconfigured ⇒ byte-for-byte no change to any state file.
6. `latest/` directories are never deleted or modified by any archive
   retention operation.
7. A per-run archive file is not deleted unless a covering weekly rollup
   exists and records the source run / artifact path.
8. Weekly rollup is generate-only in J3a (no deletion of per-run archives).
   Existing rollup files for the same week are not overwritten.
9. Weekly rollup files are long-term, operator-managed archives; the janitor
   does not auto-delete them.
10. Retention `preview` mode never deletes files; it reports every file that
    *would* be deleted together with the covering weekly rollup path.
11. Retention `enforce` must report every deleted file and its covering
    weekly rollup.

---

## 8. Non-goals

- No CR runtime behavior change (dispatch, cooldown, quiet-hours, deferred flush
  all unchanged).
- No `deploy_trace` schema change.
- No count-based hard cap (`MAX_ENTRIES`) — future knob.
- No legacy notification reintroduction.
- J3a/J3b (archive compaction + retention) and J4 (queue) are documented but
  deferred. J3a introduces no runtime mutation; J3b deletes only files that
  are covered by a weekly rollup.
- No automatic deletion of weekly rollup files — those are operator-managed.
- No archive rollup logic in `runtime_dry_run.py` — the janitor is a
  standalone tool, same as J2.
