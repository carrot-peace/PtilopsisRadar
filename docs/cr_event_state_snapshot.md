# CR-A Event State Snapshot Boundary (PR10c)

## 1. Purpose

PR10c defines the CR-A event state snapshot boundary.

It answers:

```text
Where does prior event state come from, and how is it safely read/written?
```

It does not answer:

```text
Should this candidate be suppressed?
```

That policy belongs to PR10d.

## 2. Relationship to PR10a and PR10b

PR10a answers:

```text
What event is this?
```

It defines event identity evidence, with `event_key` derived from normalized
title and `candidate_id` / `cluster_key` kept as supporting evidence.

PR10b answers:

```text
Given prior state, how would this event be interpreted?
```

It classifies repeat preview states when a caller explicitly provides prior
`seen_event_states`.

PR10c answers:

```text
Where does prior state come from, and how is it safely read/written?
```

It adds a pure snapshot model and an explicit-path filesystem store boundary
for future repeat preview and cooldown work.

## 3. Snapshot Schema

Schema version:

```text
cr-event-state-v1
```

Each entry may contain:

- `event_key`: required stable event identity key.
- `decision_level`: optional prior CR decision level.
- `score`: optional prior total score.
- `seen_at`: optional caller-provided timestamp string.
- `title`: optional display title evidence.
- `candidate_id`: optional candidate id evidence.
- `event_key_version`: optional identity key version evidence.

Duplicate `event_key` entries resolve deterministically: later updates replace
earlier entries, and snapshots are emitted in sorted `event_key` order.

## 4. Store Boundary

`trendradar/cr/state_store.py` is the only PR10c module that performs
filesystem I/O.

The store boundary:

- requires an explicit caller-provided path
- does not read environment variables
- does not integrate with `config.yaml`
- does not choose a global default path
- treats missing state as an empty snapshot
- treats malformed or invalid state as an empty snapshot plus a short error
- writes JSON as UTF-8
- saves through a sibling temporary file and atomic replace where possible

The store returns structured load/save results instead of raising for ordinary
load failures.

## 5. Non-Goals

- no cooldown enforcement
- no dedupe enforcement
- no dispatch suppression
- no Telegram behavior change
- no runtime integration
- no config integration
- no scheduler
- no production send behavior change
- no generated state files committed

## 6. PR10d Handoff

PR10d may use this state boundary to implement cooldown policy and
enforcement. PR10d's pure cooldown policy decision layer is documented in
[cr_cooldown_policy.md](cr_cooldown_policy.md); it previews decisions only and
does not yet read or write this state. PR10e assembles these primitives into an
audit-only context and proposes (but never writes) next-state entries; see
[cr_cooldown_audit_assembly.md](cr_cooldown_audit_assembly.md).

Open questions for PR10d:

- when to update state
- which levels update state
- whether urgent escalation bypasses cooldown
- whether deescalation updates state
- whether watch-only candidates should write state
- how to handle corrupted state in an enforcement path
