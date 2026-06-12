# PR10 Design Input: Lessons from Deployment Run-2

## 1. Purpose

This note records observed design input from Deployment Run-2 and is intended
to guide PR10 planning.

This document is design input, not implementation.

Specifically:

- This is not a feature spec.
- This is not runtime behavior.
- This is evidence for future PR10 work.

It should help PR10 start from observed CR-A behavior instead of assumptions
from short local bursts or static code review alone.

## 2. Deployment Run-2 Summary

- Mode: true 90-minute artifact-only monitoring.
- Runs: 6 runs, A–F.
- Window: about 97.8 minutes.
- No Telegram send.
- No secrets printed.
- No runtime code modified.
- All runs exited successfully.

Run-2 corrected the earlier short-burst observation. The short burst was useful
for smoke-checking behavior, but it was not a valid 90-minute observation
window and should not be used as the main basis for PR10 state design.

This note does not include secrets, private chat IDs, tokens, or local-only
sensitive values.

## 3. Key Observations

### candidate_id is not stable enough to be the primary dedupe key

The Guangxi explosion candidate changed candidate_id from 6e204d8621b7 to
35a135d75a46 when the cluster gained a zhihu source.

This invalidates the earlier short-burst assumption that `candidate_id` could
be the primary state key. `candidate_id` may still be useful as evidence, but
it should not be the sole event identity.

### cluster_key is not stable enough to be the primary dedupe key

`cluster_key` can grow when new sources or platforms join the same event. That
makes it useful for debugging and evidence, but it is too source-sensitive and
too verbose to be the primary storage or display key.

### normalized title is the most promising current event identity basis

The title stayed semantically stable for the persistent Guangxi explosion
event. A normalized title is short, human-readable, and currently the most
promising basis for event identity.

It is not perfect because title variants exist. For example:

```text
"广西兴安发生爆炸已致7死17伤" and "广西兴安爆炸致7死17伤" should probably map to the same event, but naive string equality may not handle this.
```

### decision level is dynamic

Run-2 observed this lifecycle for the same persistent event:

```text
watch -> watch -> urgent -> alert -> watch -> watch
```

The same event can move between watch, urgent, alert, and back to watch. PR10
must not treat alert state as a one-time static label. Future logic should
consider score and decision-level changes. Repeat logic should distinguish
"same event, same level" from "same event, meaningful escalation".

### cooldown evidence is real but still limited

C→D duplicate risk was observed within about 19 minutes. A 30-minute cooldown
would have blocked that immediate duplicate. A 60-minute cooldown is a
conservative initial default candidate, not a strongly proven conclusion. More
observation windows are needed before hardcoding policy.

Run-2 supports discussing an initial 30–60 minute cooldown range. A 60-minute
window is conservative, but confidence remains medium-low to medium because
only one dominant persistent event was observed.

## 4. Design Implications for PR10

PR10 should not start by using `candidate_id` as the state key.

Recommended initial event identity direction:

```text
event_key = normalized_title_key + supporting evidence
```

Supporting evidence may include:

- candidate_id
- cluster_key
- platform set
- source URL set
- score/decision trajectory

Only normalized title should be considered the current primary basis, pending
more observations.

The first implementation should probably expose repeat/state evidence before
enforcing suppression. PR10 should make the evidence trail visible before it
starts hiding repeated events.

## 5. Recommended PR10 Sequence

```text
PR10a: expose event identity evidence in artifacts
PR10b: expose repeat preview evidence in artifacts
PR10c: add state persistence boundary
PR10d: add cooldown policy / enforcement
PR10e: add transport/retry/error sanitization hardening
PR10f: guarded production enablement
```

PR10a/PR10b should improve observability first. PR10c/PR10d should implement
actual persistence and suppression later. Avoid making the alert system a
black box too early.

PR10a is implemented: see
[cr_event_identity_evidence.md](cr_event_identity_evidence.md) for the event
identity evidence now exposed in CR audit artifacts.

PR10b is implemented as repeat preview evidence: see
[cr_repeat_preview.md](cr_repeat_preview.md). It classifies same-level repeat,
meaningful escalation, deescalation, new, and not-evaluated states without
enforcing suppression or cooldown. PR10b closure and PR10c handoff are recorded
in [pr10b_closure_repeat_preview.md](pr10b_closure_repeat_preview.md).

## 6. Non-Goals

- no runtime behavior change
- no Telegram behavior change
- no dedupe enforcement
- no cooldown enforcement
- no state persistence
- no storage integration
- no config.yaml wiring
- no dashboard work
- no bot commands
- no notification facade integration

## 7. Open Questions

- How aggressive should title normalization be?
- Should semantically similar title variants collapse into the same event?
- How should score changes affect repeat notification?
- Should urgent escalation bypass cooldown?
- When should an already-seen event be allowed to notify again?
- How many more observation windows are needed before production defaults?
- Should source/platform expansion update evidence without changing identity?

## 8. Closing Statement

Run-2 turns PR10 from speculative architecture into observed system design. The
next step should preserve this evidence trail before implementing enforcement.
