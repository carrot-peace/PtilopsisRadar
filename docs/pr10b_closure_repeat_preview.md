# PR10b Closure: CR-A Repeat Preview Evidence

## Status

PR10b is implemented and merged.

It adds audit-only repeat preview evidence for CR-A candidates.

## What PR10b Adds

- pure repeat preview module
- same-level repeat vs meaningful escalation semantics
- deescalation semantics
- `not_evaluated` / `new` distinction
- optional Markdown / HTML repeat preview rendering
- tests for preview semantics and rendering
- docs for repeat preview handoff

## What PR10b Does Not Do

- no Telegram behavior change
- no dispatch behavior change
- no dedupe enforcement
- no cooldown enforcement
- no state persistence
- no storage
- no config integration
- no generated artifacts committed

## Validation

Post-merge dev smoke passed on `s-MacBook-Air.local`:

- HEAD: `74d734f`
- focused tests passed
- artifact-only dry-run exited 0
- Event Identity still appears in Markdown / HTML artifacts
- Repeat Preview is absent by default, as expected
- Telegram was not sent
- working tree stayed clean

## Deployment Smoke

Actual deployment Mac mini smoke is deferred.

Expected machine:

```text
Ptilopsiss-Mac-mini.local
```

The deferred deployment smoke is not a failure. It means deployment validation
remains pending until the deployment machine is convenient to access.

## Design Handoff

PR10a answers:

```text
What event is this?
```

PR10b answers:

```text
Given prior event state, how would this candidate be interpreted?
```

PR10c should answer:

```text
Where does the prior event state snapshot come from, and how is it safely read/written?
```

PR10c should still avoid cooldown enforcement.

Recommended next PR:

```text
PR10c: CR-A event state snapshot boundary
```

## Open Questions for PR10c

- Where should event state live?
- What is the exact schema?
- How should state read failure behave?
- How should state write failure behave?
- Should state updates happen for watch candidates, alert candidates, urgent
  candidates, or all rendered candidates?
- Should deployment-local state be ignored by git?
- How should corrupted state be prevented from affecting dispatch?
- Should state be updated before or after artifact generation?
- Should same-level repeats be recorded differently from meaningful escalations?
