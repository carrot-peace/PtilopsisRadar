# coding=utf-8
"""DR dispatch executor and sink boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable

from trendradar.dr.dispatch_plan import DRDispatchMessage, DRDispatchPlan


@dataclass(frozen=True)
class DRDispatchReceipt:
    message_index: int
    accepted: bool
    status: str
    detail: str
    run_label: str
    date: str
    text_accepted: bool = False
    document_accepted: bool | None = None


@dataclass(frozen=True)
class DRDispatchExecutionResult:
    plan: DRDispatchPlan
    attempted: bool
    receipts: tuple[DRDispatchReceipt, ...]
    reason: str
    accepted_count: int


@runtime_checkable
class DRDispatchSink(Protocol):
    def submit(
        self, message: DRDispatchMessage, *, message_index: int
    ) -> DRDispatchReceipt:
        ...


@dataclass
class DRMemoryDispatchSink:
    submitted_messages: List[DRDispatchMessage] = field(default_factory=list)

    def submit(
        self, message: DRDispatchMessage, *, message_index: int
    ) -> DRDispatchReceipt:
        self.submitted_messages.append(message)
        return DRDispatchReceipt(
            message_index=message_index,
            accepted=True,
            status="accepted",
            detail="memory_sink",
            run_label=message.run_label,
            date=message.date,
            text_accepted=True,
            document_accepted=message.attach_html,
        )


@dataclass
class DRNoopDispatchSink:
    def submit(
        self, message: DRDispatchMessage, *, message_index: int
    ) -> DRDispatchReceipt:
        return DRDispatchReceipt(
            message_index=message_index,
            accepted=True,
            status="accepted",
            detail="noop_sink",
            run_label=message.run_label,
            date=message.date,
            text_accepted=True,
            document_accepted=message.attach_html,
        )


TRANSPORT_EXCEPTIONS = (TimeoutError, ConnectionError, OSError, ValueError)


def execute_dr_dispatch_plan(
    plan: DRDispatchPlan,
    *,
    sink: DRDispatchSink | None,
) -> DRDispatchExecutionResult:
    """Execute a DR dispatch plan against an injected sink."""
    if not plan.should_dispatch:
        return DRDispatchExecutionResult(
            plan=plan,
            attempted=False,
            receipts=(),
            reason=plan.reason,
            accepted_count=0,
        )
    if sink is None:
        return DRDispatchExecutionResult(
            plan=plan,
            attempted=False,
            receipts=(),
            reason="no_sink",
            accepted_count=0,
        )

    receipts: list[DRDispatchReceipt] = []
    for index, message in enumerate(plan.messages):
        try:
            receipt = sink.submit(message, message_index=index)
        except TRANSPORT_EXCEPTIONS as exc:
            receipt = DRDispatchReceipt(
                message_index=index,
                accepted=False,
                status="failed_transport",
                detail=type(exc).__name__,
                run_label=message.run_label,
                date=message.date,
                text_accepted=False,
                document_accepted=None,
            )
        receipts.append(receipt)

    accepted_count = sum(1 for r in receipts if r.accepted)
    return DRDispatchExecutionResult(
        plan=plan,
        attempted=True,
        receipts=tuple(receipts),
        reason="executed",
        accepted_count=accepted_count,
    )


def dr_dispatch_receipts_to_json_dict(
    *,
    plan: DRDispatchPlan,
    dispatch_mode: str,
    execution: DRDispatchExecutionResult | None,
    created_at: str,
) -> dict[str, object]:
    receipts = execution.receipts if execution is not None else ()
    return {
        "schema_version": "dr-dispatch-receipts-v1",
        "dispatch_mode": dispatch_mode,
        "created_at": created_at,
        "run_label": plan.run_label,
        "date": plan.date,
        "attempted": bool(execution.attempted) if execution is not None else False,
        "reason": execution.reason
        if execution is not None
        else "not_executed_artifact_mode",
        "accepted_count": execution.accepted_count if execution is not None else 0,
        "receipts": [
            {
                "message_index": receipt.message_index,
                "accepted": receipt.accepted,
                "status": receipt.status,
                "detail": receipt.detail,
                "run_label": receipt.run_label,
                "date": receipt.date,
                "text_accepted": receipt.text_accepted,
                "document_accepted": receipt.document_accepted,
            }
            for receipt in receipts
        ],
    }
