# coding=utf-8
"""Pure DR dispatch planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


FORMAT_TELEGRAM_HTML = "telegram_html"
DR_DISPATCH_PLAN_SCHEMA_VERSION = "dr-dispatch-plan-v1"


@dataclass(frozen=True)
class DRDispatchMessage:
    text: str
    format: str
    run_label: str
    date: str
    html_path: str
    attach_html: bool = True


@dataclass(frozen=True)
class DRDispatchPlan:
    should_dispatch: bool
    messages: tuple[DRDispatchMessage, ...]
    reason: str
    run_label: str
    date: str
    html_path: str
    attach_html: bool


def build_dr_dispatch_plan(
    *,
    text: str,
    html_path: str | Path | None,
    run_label: str,
    date: str,
    attach_html: bool = True,
) -> DRDispatchPlan:
    """Build a side-effect-free DR dispatch plan."""
    normalized_html = str(html_path or "")
    if not normalized_html:
        return DRDispatchPlan(
            should_dispatch=False,
            messages=(),
            reason="missing_html",
            run_label=run_label,
            date=date,
            html_path="",
            attach_html=attach_html,
        )
    if not str(text or "").strip():
        return DRDispatchPlan(
            should_dispatch=False,
            messages=(),
            reason="empty_text",
            run_label=run_label,
            date=date,
            html_path=normalized_html,
            attach_html=attach_html,
        )

    message = DRDispatchMessage(
        text=text,
        format=FORMAT_TELEGRAM_HTML,
        run_label=run_label,
        date=date,
        html_path=normalized_html,
        attach_html=attach_html,
    )
    return DRDispatchPlan(
        should_dispatch=True,
        messages=(message,),
        reason="ready",
        run_label=run_label,
        date=date,
        html_path=normalized_html,
        attach_html=attach_html,
    )


def dr_dispatch_plan_to_json_dict(
    plan: DRDispatchPlan,
    *,
    dispatch_mode: str,
    created_at: str,
) -> dict[str, object]:
    return {
        "schema_version": DR_DISPATCH_PLAN_SCHEMA_VERSION,
        "dispatch_mode": dispatch_mode,
        "created_at": created_at,
        "should_dispatch": plan.should_dispatch,
        "reason": plan.reason,
        "run_label": plan.run_label,
        "date": plan.date,
        "html_path": plan.html_path,
        "attach_html": plan.attach_html,
        "messages": [
            {
                "message_index": idx,
                "format": message.format,
                "run_label": message.run_label,
                "date": message.date,
                "html_path": message.html_path,
                "attach_html": message.attach_html,
                "text": message.text,
            }
            for idx, message in enumerate(plan.messages)
        ],
    }
