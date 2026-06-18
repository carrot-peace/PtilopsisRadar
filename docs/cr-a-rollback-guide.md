# CR-A Rollback Guide

Safe rollback and emergency-stop guidance for the CR-A dispatch pipeline
(A1–A7). Companion to [`cr-a-operator-runbook.md`](cr-a-operator-runbook.md).

All switches below are environment variables. None of them mutate state or send
anything by themselves — they change what the next run is permitted to do.

---

## 1. Rollback switches

### Emergency stop — disable CR-A dispatch entirely

```bash
export PTILOPSIS_CR_DISPATCH_MODE=off
```

### Disable real Telegram send (keep CR-A running)

```bash
export PTILOPSIS_CR_TELEGRAM_SEND=0
```

### Disable quiet-hours policy

```bash
export PTILOPSIS_CR_QUIET_HOURS_ENABLED=0
```

### Disable urgent bypass

```bash
export PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT=0
```

---

## 2. Effects

```text
DISPATCH_MODE=off:
  Stops CR-A dispatch. No artifacts, no send, no state, no queue mutation.

TELEGRAM_SEND=0:
  Prevents live Telegram send even if mode is live.
  The sink is not constructed; CR-A still writes artifacts.

QUIET_HOURS_ENABLED=0:
  Stops the quiet-hours deferral policy.
  May leave existing deferred queue entries until explicitly handled
  (see Section 4).

QUIET_HOURS_ALLOW_URGENT=0:
  Urgent messages no longer bypass quiet-hours; they defer like alerts.
```

Choosing a switch:

```text
- Stop everything now            -> DISPATCH_MODE=off
- Keep observing, stop sending   -> TELEGRAM_SEND=0 (stay in live, or use shadow)
- Stop holding messages overnight-> QUIET_HOURS_ENABLED=0 (mind stranded queue)
- Stop urgent overriding quiet   -> QUIET_HOURS_ALLOW_URGENT=0
```

---

## 3. Emergency artifact backup

Back up CR artifacts and deploy traces before any manual cleanup. These commands
are non-destructive (copy only):

```bash
mkdir -p output/backup/cr-a-$(date +%Y%m%d-%H%M%S)
cp -R output/cr output/backup/cr-a-$(date +%Y%m%d-%H%M%S)/cr
cp -R output/meta/deploy_trace output/backup/cr-a-$(date +%Y%m%d-%H%M%S)/deploy_trace
```

`output/` is git-ignored; backups stay local and are not committed.

---

## 4. Handling the deferred queue during rollback

Queue file:

```text
output/cr/state/cr_deferred_dispatch_queue.json
```

```text
- Do NOT manually edit the queue unless performing emergency rollback.
- Back up the queue before any manual deletion (see below).
- A malformed queue fails closed: no send, queue not overwritten.
- Disabling quiet-hours can strand queued entries. To clear them, either:
    (a) run a normal post-quiet `live` run so accepted entries flush out, or
    (b) back up and remove the queue file manually (destructive — backup first).
```

Manual clear (destructive — **back up first**):

```bash
# 1. Back up.
mkdir -p output/backup/cr-a-$(date +%Y%m%d-%H%M%S)
cp output/cr/state/cr_deferred_dispatch_queue.json \
   output/backup/cr-a-$(date +%Y%m%d-%H%M%S)/cr_deferred_dispatch_queue.json
# 2. Only then remove (the next run starts from an empty queue).
rm output/cr/state/cr_deferred_dispatch_queue.json
```

There is no automatic drain command in CR-A; draining is done by normal
post-quiet `live` runs that flush accepted entries.

---

## 5. Rollback verification

After applying a rollback switch, confirm the intended no-send posture:

```text
[ ] DISPATCH_MODE=off  -> no new dispatch_plan.json / dispatch_receipts.json writes
[ ] TELEGRAM_SEND=0    -> receipts show not_configured / no accepted live send
[ ] cr_dispatch_state.json not advanced by a non-accepted outcome
[ ] deferred queue not unexpectedly mutated
```

Run the read-only smoke check to confirm no false success crept in:

```bash
.venv/bin/python scripts/cr_a_smoke_check.py
```
