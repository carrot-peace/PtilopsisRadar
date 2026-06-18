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
| **G3 — Bounded archives** | 🟢 Reasonable, **deferred** | Inert "death debt": does not slow runs, swept later at identical cost, does not compound. |
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

Lifecycle management is a **standalone, independently-runnable tool** (same
shape as [`scripts/cr_a_smoke_check.py`](../scripts/cr_a_smoke_check.py)) that
talks only to the **versioned file contracts** (`cr-event-state-v1`,
`cr-deferred-dispatch-queue-v1`, archive directories). It is **never imported
into, or inlined within, `runtime_dry_run.py`**.

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
| **D** — archive retention needs two modules' path layouts | ⚪ **Deferred** | Non-compounding death debt; handled later by the same janitor (or a one-line `find -mtime` cron) with no entanglement. |

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
| **J2** | Janitor `scripts/cr_a_lifecycle.py`: load `cr-event-state-v1` (public) → `preview` (report `would_evict`) or `enforce` (atomic save of pruned snapshot). Builds `ttl_for_level` from public cooldown policy + `TTL_FLOOR`. | **None** (standalone) | **Now** |
| **J3** | Archive retention (keep last N / last D days) for `cr/archive/*` and `deploy_trace/archive`; backup-before-delete; never touches `latest/`. | Low (reads dir listings) | **Deferred — non-compounding** |
| **J4** | Deferred-queue hygiene: expire entries past `deferred_until` + grace, or cap retries; via public `remove_deferred_entries`; records eviction in a report. | Low (public API only) | **Deferred — non-compounding** |
| **J5** | Observability: janitor emits its own lifecycle report (active / dormant / evicted counts); extend smoke check with a "state not over-bounded" invariant. | None~low (no `deploy_trace` change) | After J2 |

The post-run trigger line (Decision 1) is added when J2 lands, gated and
fail-closed.

---

## 6. Configuration (all default off = current behavior)

| Variable | Allowed values | Default | Meaning |
| --- | --- | --- | --- |
| `PTILOPSIS_CR_LIFECYCLE_ENABLED` | `1` to enable | unset ⇒ off | Master gate. Off ⇒ janitor is a no-op. |
| `PTILOPSIS_CR_LIFECYCLE_MODE` | `preview`, `enforce` | `preview` | `preview` reports `would_evict` only; `enforce` writes the pruned snapshot. |
| `PTILOPSIS_CR_LIFECYCLE_TTL_FLOOR_DAYS` | positive number | `7` | Memory window. Effective ttl = `max(cooldown, this)`. |

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

---

## 8. Non-goals

- No CR runtime behavior change (dispatch, cooldown, quiet-hours, deferred flush
  all unchanged).
- No `deploy_trace` schema change.
- No count-based hard cap (`MAX_ENTRIES`) — future knob.
- No legacy notification reintroduction.
- J3 (archives) and J4 (queue) are documented but deferred.
