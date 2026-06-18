#!/usr/bin/env python3
# coding=utf-8
"""CR-A local smoke check (read-only).

Validates the current CR-A artifacts without running CR or sending anything.

This script is strictly read-only:
  - sends no Telegram,
  - runs no CR runtime,
  - mutates no state and writes no files,
  - exits non-zero on malformed JSON or an invariant violation.

It checks:
  - output/cr/latest/dispatch_plan.json        parses (if present)
  - output/cr/latest/dispatch_receipts.json    parses (if present)
  - output/meta/deploy_trace/latest.json       parses (if present)
  - output/cr/state/cr_deferred_dispatch_queue.json  parses (if present)
  - core invariant: no receipt has ``accepted == true`` unless its
    ``status == "accepted"`` (no false success).

Missing files are tolerated (a fresh checkout may not have run yet) and reported
as ``SKIP``. Malformed JSON or an invariant violation is a hard failure.

See docs/cr-a-operator-runbook.md (section 9) for usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PLAN_PATH = "output/cr/latest/dispatch_plan.json"
DEFAULT_RECEIPTS_PATH = "output/cr/latest/dispatch_receipts.json"
DEFAULT_DEPLOY_TRACE_PATH = "output/meta/deploy_trace/latest.json"
DEFAULT_DEFERRED_QUEUE_PATH = "output/cr/state/cr_deferred_dispatch_queue.json"

ACCEPTED_STATUS = "accepted"


class SmokeCheckError(Exception):
    """Raised when a smoke-check invariant is violated."""


def _load_json_if_exists(path: Path) -> tuple[object | None, str]:
    """Load JSON from *path*.

    Returns ``(data, "ok")`` when parsed, ``(None, "skip")`` when the file is
    absent. Raises :class:`SmokeCheckError` on malformed JSON or read errors.
    """
    if not path.exists():
        return None, "skip"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SmokeCheckError(f"unable to read {path}: {type(exc).__name__}") from exc
    try:
        return json.loads(text), "ok"
    except json.JSONDecodeError as exc:
        raise SmokeCheckError(f"malformed JSON in {path}: {exc}") from exc


def _iter_receipt_entries(receipts_data: object) -> list[dict]:
    """Extract receipt entries from dispatch_receipts.json content."""
    if not isinstance(receipts_data, dict):
        raise SmokeCheckError("dispatch_receipts root must be a JSON object")
    entries = receipts_data.get("receipts", [])
    if not isinstance(entries, list):
        raise SmokeCheckError("dispatch_receipts 'receipts' must be a list")
    out: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise SmokeCheckError("each receipt entry must be a JSON object")
        out.append(entry)
    return out


def _assert_no_false_success(entries: list[dict]) -> None:
    """Invariant: accepted == true requires status == 'accepted'."""
    for entry in entries:
        accepted = entry.get("accepted")
        status = entry.get("status")
        if accepted is True and status != ACCEPTED_STATUS:
            index = entry.get("message_index", "?")
            raise SmokeCheckError(
                "false success: receipt "
                f"message_index={index} has accepted=true but "
                f"status={status!r} (expected {ACCEPTED_STATUS!r})"
            )


def run_smoke_check(
    *,
    plan_path: str = DEFAULT_PLAN_PATH,
    receipts_path: str = DEFAULT_RECEIPTS_PATH,
    deploy_trace_path: str = DEFAULT_DEPLOY_TRACE_PATH,
    deferred_queue_path: str = DEFAULT_DEFERRED_QUEUE_PATH,
) -> list[str]:
    """Run all smoke checks. Returns human-readable status lines.

    Raises :class:`SmokeCheckError` on the first invariant violation.
    """
    lines: list[str] = []

    plan_data, plan_state = _load_json_if_exists(Path(plan_path))
    lines.append(f"[{plan_state.upper():>4}] dispatch_plan       {plan_path}")

    receipts_data, receipts_state = _load_json_if_exists(Path(receipts_path))
    lines.append(f"[{receipts_state.upper():>4}] dispatch_receipts   {receipts_path}")

    _, trace_state = _load_json_if_exists(Path(deploy_trace_path))
    lines.append(f"[{trace_state.upper():>4}] deploy_trace        {deploy_trace_path}")

    _, queue_state = _load_json_if_exists(Path(deferred_queue_path))
    lines.append(f"[{queue_state.upper():>4}] deferred_queue      {deferred_queue_path}")

    if receipts_state == "ok":
        entries = _iter_receipt_entries(receipts_data)
        _assert_no_false_success(entries)
        lines.append(
            f"[  OK] invariant: no false success across {len(entries)} receipt(s)"
        )
    else:
        lines.append("[SKIP] invariant: no receipts to check")

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CR-A read-only smoke check")
    parser.add_argument("--plan-path", default=DEFAULT_PLAN_PATH)
    parser.add_argument("--receipts-path", default=DEFAULT_RECEIPTS_PATH)
    parser.add_argument("--deploy-trace-path", default=DEFAULT_DEPLOY_TRACE_PATH)
    parser.add_argument("--deferred-queue-path", default=DEFAULT_DEFERRED_QUEUE_PATH)
    args = parser.parse_args(argv)

    try:
        lines = run_smoke_check(
            plan_path=args.plan_path,
            receipts_path=args.receipts_path,
            deploy_trace_path=args.deploy_trace_path,
            deferred_queue_path=args.deferred_queue_path,
        )
    except SmokeCheckError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    for line in lines:
        print(line)
    print("[ OK ] CR-A smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
