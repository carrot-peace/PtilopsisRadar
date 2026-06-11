# CR-A Repeat Preview Evidence (PR10b)

## 1. Purpose

PR10b adds repeat preview evidence for CR-A audit artifacts.

This is observability-only. It classifies how a current candidate would be
interpreted against an explicitly supplied in-memory prior event state
snapshot. It does not decide whether anything should be suppressed.

## 2. Relationship to PR10a

PR10a answers:

```text
What event is this?
```

It does that by exposing Event Identity evidence, with `event_key` based
primarily on normalized title and `candidate_id` / `cluster_key` kept as
supporting evidence.

PR10b answers:

```text
Given prior event state, how would this candidate be interpreted?
```

It uses the PR10a `event_key`, the current decision level / score, and an
optional caller-provided prior state snapshot. If no prior snapshot is
provided, repeat preview is explicitly `not_evaluated`.

## 3. Preview statuses

- `not_evaluated`: no prior event state snapshot was provided.
- `new`: a prior snapshot was provided, but this `event_key` was absent.
- `same_event_repeat`: the `event_key` was seen before, but decision levels are
  unavailable.
- `same_level_repeat`: the `event_key` was seen before with the same decision
  level.
- `meaningful_escalation`: the `event_key` was seen before and the current
  decision level is higher.
- `deescalation`: the `event_key` was seen before and the current decision
  level is lower.

Decision level ordering for preview is:

```text
suppress < watch < alert < urgent
```

`suppress` remains only a decision label in this preview layer. PR10b does not
enforce suppress behavior.

## 4. Same-Level Repeat vs Meaningful Escalation

Repeat preview distinguishes stable repeated events from events whose decision
level changed enough to matter:

- Same event, `alert -> alert`: `same_level_repeat`
- Same event, `watch -> alert`: `meaningful_escalation`
- Same event, `alert -> urgent`: `meaningful_escalation`
- Same event, `urgent -> alert`: `deescalation`

This reflects Deployment Run-2, where the same event moved through:

```text
watch -> watch -> urgent -> alert -> watch -> watch
```

## 5. Non-Goals

- no dispatch suppression
- no cooldown enforcement
- no persistence
- no storage
- no Telegram change
- no runtime send change
- no config.yaml integration
- no generated artifact changes

## 6. PR10 Handoff

Recommended next steps:

- PR10c: define the state persistence boundary for event state snapshots.
- PR10d: implement cooldown policy / enforcement after the state boundary is
  explicit.
- Later: improve title variant normalization for semantically equivalent event
  titles that currently produce different `event_key` values.
