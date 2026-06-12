# CR-A Local Cooldown State Loop — Operator Guide

## Purpose

This document explains how to run the local CR-A cooldown state loop in
artifact dry-run mode.

It is for local operator validation and audit artifacts only.

## Safety Boundary

```text
local-only
explicit input path
explicit output path
dry-run only
no Telegram send
no dispatch suppression
no production enforcement
no default path
no env/config path
```

The dry-run never sends Telegram messages, suppresses dispatch, reads
environment variables for state paths, or writes to a default location.

## Required Inputs

The relevant `build_and_write_cr_runtime_dry_run` parameters for the local
cooldown loop:

```text
include_cooldown_audit=True
cooldown_prior_snapshot_path=<explicit prior state path>
cooldown_next_snapshot_path=<explicit next state output path>
```

Alternative inputs:

- `cooldown_prior_snapshot` — in-memory prior state (no file I/O)
- `cooldown_prior_snapshot_path` — local read-only input file
- `cooldown_next_snapshot_path` — local explicit write-back output file

When both `cooldown_prior_snapshot` and `cooldown_prior_snapshot_path` are
supplied, the dry-run raises `ValueError` (mutually exclusive).

## Expected Loop

### 1. First run with missing prior state

```text
prior load:   loaded=False, error=None
repeat preview: new
cooldown decision: allow_new
state transition preview: next snapshot available
next state file: written
```

A missing file is treated as a known-empty prior state. There is no prior
history, so the candidate is `new` and the decision is `allow_new`.

### 2. Second run using previous output as prior

```text
prior load:   loaded=True, error=None
repeat preview: same_level_repeat
cooldown decision: cooldown
state transition preview: next snapshot available
next state file: written
```

The prior state now contains the entry from Run 1. The same event is
recognized as `same_level_repeat` and the cooldown decision is `cooldown`.

### 3. Malformed prior state

```text
prior load:   loaded=False, error!=None
repeat preview: not_evaluated
cooldown decision: not_evaluated
state transition preview: suppressed
next state file: not written
```

A malformed or schema-invalid file means the source failed. The dry-run
fails closed: no prior snapshot is used, the preview is suppressed, and no
next-state file is written.

## Example Smoke Script

```python
from pathlib import Path
import tempfile

from tests.test_cr_cooldown_artifact_wiring import _hotlist_stats, _artifact_config
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run
from trendradar.cr.state_store import load_cr_event_state_snapshot

root = Path(tempfile.mkdtemp(prefix="cooldown-loop-"))

prior_path = root / "prior-state.json"
next_path = root / "next-state.json"

# Run 1: missing prior → new / allow_new
run1 = build_and_write_cr_runtime_dry_run(
    hotlist_stats=_hotlist_stats(),
    run_label="loop-run-1",
    artifact_config=_artifact_config(str(root / "artifacts-1")),
    include_cooldown_audit=True,
    cooldown_prior_snapshot_path=prior_path,
    cooldown_next_snapshot_path=next_path,
)

print("Run 1 load:", run1.cooldown_prior_snapshot_load)
print("Run 1 save:", run1.cooldown_next_snapshot_save)
# Run 1: loaded=False, error=None, next state written

# Run 2: use Run 1 output as prior → same_level_repeat / cooldown
next2 = root / "next-state-2.json"
run2 = build_and_write_cr_runtime_dry_run(
    hotlist_stats=_hotlist_stats(),
    run_label="loop-run-2",
    artifact_config=_artifact_config(str(root / "artifacts-2")),
    include_cooldown_audit=True,
    cooldown_prior_snapshot_path=next_path,
    cooldown_next_snapshot_path=next2,
)

print("Run 2 load:", run2.cooldown_prior_snapshot_load)
print("Run 2 save:", run2.cooldown_next_snapshot_save)
# Run 2: loaded=True, error=None, same_level_repeat, next state written
```

This script uses test fixtures for input data. Replace with real runtime
stats for production-like validation.

## Operator Checklist

```text
[ ] confirm on master
[ ] confirm no Telegram send gate (env | grep PTILOPSIS_CR_TELEGRAM_SEND)
[ ] choose temp/local state directory
[ ] run first dry-run with missing prior path
[ ] inspect Markdown/HTML artifact for new / allow_new
[ ] verify next state file exists and is valid JSON
[ ] run second dry-run with previous output as prior
[ ] verify same_level_repeat / cooldown in artifact
[ ] test malformed prior if changing state parser behavior
[ ] verify malformed prior suppresses next-state write
```

## What This Does Not Mean

```text
This does not mean production cooldown enforcement exists.
This does not mean Telegram dispatch is suppressed.
This does not mean state paths are configured.
This does not mean scheduler integration exists.
```

The local cooldown loop is an operator validation tool. It produces audit
artifacts and explicit local state files. It does not enforce, suppress, or
schedule anything.

## Handoff

Future work may include:

```text
PR11a: CLI/operator wrapper for local cooldown loop
PR11b: hard-gated production state path config
PR11c: production enforcement dry-run shadow mode
PR11d: Telegram/dispatch suppression only after shadow validation
```

None of that is implemented here.
