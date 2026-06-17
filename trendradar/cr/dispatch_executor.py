# coding=utf-8
"""
CR dispatch executor / sink boundary (PR9m) v0.1.

A small, local execution boundary that consumes a :class:`CRDispatchPlan` and
hands its planned messages to an injected sink, returning a structured
execution result.

This module answers exactly one system question:

    Given a CRDispatchPlan, can the system execute the plan against an injected
    local sink and return a structured execution result?

It is a delivery *boundary* only.  It does not know any external channel
exists: no real network call, no token, no destination / channel id, no parse
mode, no retry / backoff, and no run-to-run state.  The sink is always injected
by the caller; the executor constructs no external sender.  Real delivery is a
future PR.

Design reference: PR9m.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable

from trendradar.cr.dispatch_plan import CRDispatchMessage, CRDispatchPlan


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRDispatchReceipt:
    """Outcome of submitting one planned message to a sink.

    Channel-agnostic: carries acceptance status and descriptive counts only —
    no destination, channel id, token, parse mode, or network metadata.
    """

    message_index: int
    accepted: bool
    status: str
    detail: str
    candidate_count: int
    run_label: str


@dataclass(frozen=True)
class CRDispatchExecutionResult:
    """Structured result of executing a dispatch plan against a sink."""

    plan: CRDispatchPlan
    attempted: bool
    receipts: tuple[CRDispatchReceipt, ...]
    reason: str
    accepted_count: int


# ---------------------------------------------------------------------------
# Sink protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CRDispatchSink(Protocol):
    """Injected sink that accepts planned CR dispatch messages.

    Implementations are provided by the caller.  The executor never builds a
    real external sender and is unaware of any specific delivery channel.  In
    v0.1, the executor collapses ``TimeoutError``, ``ConnectionError``, and
    ``OSError`` raised by :meth:`submit` into ``failed_transport`` receipts;
    other exceptions propagate to the caller.
    """

    def submit(
        self, message: CRDispatchMessage, *, message_index: int
    ) -> CRDispatchReceipt:
        ...


# ---------------------------------------------------------------------------
# Local sink implementations (for dry-run / tests)
# ---------------------------------------------------------------------------


@dataclass
class CRMemoryDispatchSink:
    """In-memory sink that records submitted messages.

    No filesystem, no network, no external channel — useful for dry-run and
    tests.
    """

    submitted_messages: List[CRDispatchMessage] = field(default_factory=list)

    def submit(
        self, message: CRDispatchMessage, *, message_index: int
    ) -> CRDispatchReceipt:
        self.submitted_messages.append(message)
        return CRDispatchReceipt(
            message_index=message_index,
            accepted=True,
            status="accepted",
            detail="memory_sink",
            candidate_count=message.candidate_count,
            run_label=message.run_label,
        )


@dataclass
class CRNoopDispatchSink:
    """Sink that accepts messages without recording them.

    Accepts every message (so plan execution succeeds) but stores nothing.
    """

    def submit(
        self, message: CRDispatchMessage, *, message_index: int
    ) -> CRDispatchReceipt:
        return CRDispatchReceipt(
            message_index=message_index,
            accepted=True,
            status="accepted",
            detail="noop_sink",
            candidate_count=message.candidate_count,
            run_label=message.run_label,
        )


# ---------------------------------------------------------------------------
# Transport exception matching
# ---------------------------------------------------------------------------

TRANSPORT_EXCEPTIONS = (TimeoutError, ConnectionError, OSError)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def execute_cr_dispatch_plan(
    plan: CRDispatchPlan,
    *,
    sink: CRDispatchSink,
) -> CRDispatchExecutionResult:
    """Execute a dispatch plan against an injected sink.

    Pure orchestration: does not mutate the plan or its messages, does not
    re-check eligibility, re-render text, or recompute decisions, and sends
    nothing real.  Transport exceptions (timeout, connection, OS errors) are
    caught per-message and collapsed into ``failed_transport`` receipts so the
    caller always receives a structured result.

    Behavior:
      - ``plan.should_dispatch is False`` → the sink is never called;
        ``attempted=False``, ``receipts=()``, ``reason=plan.reason``,
        ``accepted_count=0``.
      - ``plan.should_dispatch is True`` → each message is submitted in order
        with its positional ``message_index``; ``attempted=True``,
        ``reason="executed"``, and ``accepted_count`` is the number of
        receipts whose ``accepted`` is ``True``.
      - If a sink submit raises a transport exception, a ``failed_transport``
        receipt is produced for that message; other messages continue.

    Returns
    -------
    CRDispatchExecutionResult
    """
    # Skipped plan — do not touch the sink.
    if not plan.should_dispatch:
        return CRDispatchExecutionResult(
            plan=plan,
            attempted=False,
            receipts=(),
            reason=plan.reason,
            accepted_count=0,
        )

    # Ready plan — submit each message in order.
    receipts: list[CRDispatchReceipt] = []
    for index, message in enumerate(plan.messages):
        try:
            receipt = sink.submit(message, message_index=index)
        except TRANSPORT_EXCEPTIONS as exc:
            receipt = CRDispatchReceipt(
                message_index=index,
                accepted=False,
                status="failed_transport",
                detail=type(exc).__name__,
                candidate_count=message.candidate_count,
                run_label=message.run_label,
            )
        receipts.append(receipt)

    accepted_count = sum(1 for r in receipts if r.accepted)

    return CRDispatchExecutionResult(
        plan=plan,
        attempted=True,
        receipts=tuple(receipts),
        reason="executed",
        accepted_count=accepted_count,
    )
