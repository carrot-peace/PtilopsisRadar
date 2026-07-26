# coding=utf-8
"""
CR runtime dry-run hook (PR9k) v0.1.

CR-internal glue that connects real runtime-produced hotlist / RSS stats to
the offline CR pipeline, then writes Markdown / HTML audit artifacts.

This is a *dry-run* bridge only.  It answers exactly one system question:

    Can the existing runtime produce CR Markdown / HTML artifacts from real
    hotlist / RSS stats without sending anything?

It deliberately stays inside the CR layer: it only converts stats via the
existing CR adapter, runs the existing CR pipeline, and writes through explicit
CR boundaries.  It performs no delivery, no suppression / de-duplication, no
AI-result integration, and reads no runtime configuration.  CR-A text and JSON
outputs are out of scope here.

Design reference: PR9k.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from trendradar.cr.adapter import adapt_hotlist_stats, adapt_rss_stats
from trendradar.cr.artifacts import (
    CRArtifactConfig,
    CRArtifactPaths,
    write_dispatch_plan_json,
    write_dispatch_receipts_json,
)
from trendradar.cr.cooldown_audit import (
    CRCooldownAuditContext,
    build_cr_cooldown_audit_context,
)
from trendradar.cr.cooldown_enforce import (
    CRCooldownEnforcementResult,
    DEFAULT_DISPATCH_STATE_PATH,
    enforce_cr_cooldown_for_candidates,
)
from trendradar.cr.cooldown_policy import CRCooldownPolicy
from trendradar.cr.dispatch_executor import (
    CRDispatchExecutionResult,
    CRDispatchSink,
    TRANSPORT_EXCEPTIONS,
    execute_cr_dispatch_plan,
)
from trendradar.cr.dispatch_plan import (
    CRDispatchMessage,
    CRDispatchPlan,
    build_cr_a_dispatch_plan,
    cr_dispatch_plan_to_json_dict,
)
from trendradar.cr.dispatch_receipt import (
    STATUS_DEFERRED_QUIET_HOURS,
    STATUS_SKIPPED_DEFERRED_QUEUE_ERROR,
    STATUS_SKIPPED_DEFERRED_QUEUE_UPSERT,
    build_dispatch_receipts_json,
)
from trendradar.cr.decision import (
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DEFAULT_CR_URGENT_THRESHOLD,
)
from trendradar.cr.deferred_queue import (
    CRDeferredDispatchEntry,
    CRDeferredDispatchQueue,
    CRDeferredQueueLoadResult,
    CRDeferredQueueSaveResult,
    CRDeferredQueueUpsertResult,
    DEFAULT_DEFERRED_QUEUE_PATH,
    load_deferred_dispatch_queue,
    ordered_entries_for_flush,
    remove_deferred_entries,
    save_deferred_dispatch_queue,
    stable_deferred_entry_id,
    upsert_deferred_entry,
)
from trendradar.cr.event_identity import (
    CREventIdentityInput,
    build_cr_event_identity_from_input,
    stable_event_key_for_candidate,
)
from trendradar.cr.html import CRHTMLRenderConfig
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.models import CRPrimitiveRecord, CRRunContext
from trendradar.cr.pipeline import (
    CRPipelineConfig,
    CRPipelineRenderConfig,
    CRPipelineResult,
    build_cr_pipeline_from_primitives,
    write_cr_pipeline_artifacts,
)
from trendradar.cr.repeat_preview import CRSeenEventState
from trendradar.cr.quiet_hours import (
    CRQuietHoursEvaluation,
    evaluate_cr_quiet_hours,
    quiet_hours_evaluation_to_plan_dict,
)
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    cr_event_state_snapshot_to_seen_states,
    merge_cr_event_state_entries,
    empty_cr_event_state_snapshot,
)
from trendradar.cr.state_store import (
    CREventStateLoadResult,
    CREventStateSaveResult,
    load_cr_event_state_snapshot,
    save_cr_event_state_snapshot,
)
from trendradar.cr.state_transition_preview import (
    CREventStateTransitionPreview,
    build_cr_event_state_transition_preview,
)
from trendradar.cr.html import render_cr_html_audit
from trendradar.cr.input_health import (
    CRInputHealth,
    candidate_has_fresh_input,
    input_health_to_json_dict,
)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRRuntimeDryRunResult:
    """Result of a single CR runtime dry-run.

    Bundles the combined primitives, the full pipeline result, the resolved
    artifact paths that were written, and the CR-A dispatch plan (pure
    planning — nothing is sent).

    ``dispatch_execution`` is populated only when a local ``dispatch_sink`` is
    supplied to :func:`build_and_write_cr_runtime_dry_run`; it remains ``None``
    otherwise.  Execution targets the injected local sink only — no real
    delivery.

    ``cooldown_audit`` is populated only when ``include_cooldown_audit=True``;
    it remains ``None`` otherwise.  It is an audit-only assembly (PR10e) built
    in memory from the presented candidates — it enforces nothing and writes no
    state.  The proposed next-state entries it holds are never persisted.  When
    an explicit in-memory ``cooldown_prior_snapshot`` is supplied (PR10g), the
    assembly evaluates each candidate against it so the artifacts can show real
    repeat / cooldown decisions.  When an explicit local
    ``cooldown_prior_snapshot_path`` is supplied (PR10h), the snapshot is loaded
    read-only from that caller-provided path through the explicit state-store
    boundary.  No default path, environment/config path, or write-back is used.

    ``cooldown_prior_snapshot_load`` is populated only when
    ``include_cooldown_audit=True`` and a local snapshot path was explicitly
    supplied.  Missing files produce a load result with ``loaded=False`` and
    ``error=None`` and are treated as known-empty prior state.  Malformed or
    invalid files produce ``loaded=False`` with an error and fail closed to no
    prior snapshot.

    ``cooldown_state_transition_preview`` is populated only when
    ``include_cooldown_audit=True``. It previews the next state snapshot in
    memory from the effective prior snapshot and proposed state updates.

    ``cooldown_next_snapshot_save`` is populated only when
    ``include_cooldown_audit=True``, ``cooldown_next_snapshot_path`` is
    explicitly supplied, and the transition preview has a next snapshot to
    persist.  It records the explicit local dry-run write result.  ``None``
    means no write was attempted.

    ``dispatch_plan_json_paths`` records the resolved artifact paths for the
    dispatch plan JSON file.

    ``dispatch_receipt_json_paths`` records the resolved artifact paths for the
    dispatch receipt JSON file.
    """

    primitives: tuple[CRPrimitiveRecord, ...]
    pipeline: CRPipelineResult
    artifact_paths: CRArtifactPaths
    dispatch_plan: CRDispatchPlan
    dispatch_plan_json_paths: CRArtifactPaths
    dispatch_receipt_json_paths: CRArtifactPaths
    dispatch_execution: CRDispatchExecutionResult | None = None
    cooldown_audit: CRCooldownAuditContext | None = None
    cooldown_prior_snapshot_load: CREventStateLoadResult | None = None
    cooldown_state_transition_preview: (
        CREventStateTransitionPreview | None
    ) = None
    cooldown_next_snapshot_save: CREventStateSaveResult | None = None
    cooldown_enforcement: CRCooldownEnforcementResult | None = None
    dispatch_state_save: CREventStateSaveResult | None = None
    quiet_hours: CRQuietHoursEvaluation | None = None
    deferred_queue_load: CRDeferredQueueLoadResult | None = None
    deferred_queue_save: CRDeferredQueueSaveResult | None = None
    input_health: CRInputHealth | None = None


# ---------------------------------------------------------------------------
# Audit-only render config assembly (artifact reporting only)
# ---------------------------------------------------------------------------


def _pipeline_config_with_input_health(
    pipeline_config: CRPipelineConfig | None,
    health: CRInputHealth,
) -> CRPipelineConfig:
    base = pipeline_config or CRPipelineConfig()
    render = base.render
    markdown = replace(
        render.markdown or CRMarkdownRenderConfig(), input_health=health,
    )
    html = replace(render.html or CRHTMLRenderConfig(), input_health=health)
    return replace(base, render=replace(render, markdown=markdown, html=html))


def _pipeline_config_with_cooldown_audit(
    pipeline_config: CRPipelineConfig | None,
    *,
    policy: CRCooldownPolicy,
    seen_event_states: dict[str, CRSeenEventState] | None,
) -> CRPipelineConfig:
    """Return a pipeline config whose Markdown/HTML render configs show the
    audit-only cooldown evidence.

    Pure config assembly: it only flips ``include_repeat_preview`` /
    ``include_cooldown_decision`` on, attaches the cooldown ``policy``, and
    threads through the caller-provided ``seen_event_states``.

    ``seen_event_states`` is derived only from an explicit prior snapshot,
    either supplied in memory or loaded read-only from a caller-provided local
    path.  When it is ``None`` (no usable prior snapshot), the rendered
    repeat/cooldown evidence is ``not_evaluated`` — matching the audit context
    built with ``prior_snapshot=None``.  When it is provided, the artifacts can
    show real ``same_level_repeat`` / ``meaningful_escalation`` evidence.  This
    changes neither the CR-A text config nor any dispatch behavior.
    """
    base_render = (
        pipeline_config.render
        if pipeline_config is not None
        else CRPipelineRenderConfig()
    )
    base_md = (
        base_render.markdown
        if base_render.markdown is not None
        else CRMarkdownRenderConfig()
    )
    base_html = (
        base_render.html
        if base_render.html is not None
        else CRHTMLRenderConfig()
    )

    audit_md = replace(
        base_md,
        include_repeat_preview=True,
        include_cooldown_decision=True,
        seen_event_states=seen_event_states,
        cooldown_policy=policy,
    )
    audit_html = replace(
        base_html,
        include_repeat_preview=True,
        include_cooldown_decision=True,
        seen_event_states=seen_event_states,
        cooldown_policy=policy,
    )
    audit_render = replace(base_render, markdown=audit_md, html=audit_html)

    if pipeline_config is None:
        return CRPipelineConfig(render=audit_render)
    return replace(pipeline_config, render=audit_render)


def _pipeline_result_with_state_transition_preview(
    pipeline_result: CRPipelineResult,
    pipeline_config: CRPipelineConfig | None,
    *,
    transition_preview: CREventStateTransitionPreview,
    urgent_threshold: float,
) -> CRPipelineResult:
    """Return a pipeline result with Markdown/HTML re-rendered to include the
    run-level state transition preview.
    """
    base_render = (
        pipeline_config.render
        if pipeline_config is not None
        else CRPipelineRenderConfig()
    )
    base_md = (
        base_render.markdown
        if base_render.markdown is not None
        else CRMarkdownRenderConfig()
    )
    base_html = (
        base_render.html
        if base_render.html is not None
        else CRHTMLRenderConfig()
    )
    md_cfg = replace(
        base_md,
        include_state_transition_preview=True,
        state_transition_preview=transition_preview,
    )
    html_cfg = replace(
        base_html,
        include_state_transition_preview=True,
        state_transition_preview=transition_preview,
    )
    return replace(
        pipeline_result,
        markdown_audit_text=render_cr_markdown_audit(
            list(pipeline_result.presented_candidates),
            run_label=pipeline_result.run_label,
            config=md_cfg,
            urgent_threshold=urgent_threshold,
        ),
        html_audit_text=render_cr_html_audit(
            list(pipeline_result.presented_candidates),
            run_label=pipeline_result.run_label,
            config=html_cfg,
            urgent_threshold=urgent_threshold,
        ),
    )


# ---------------------------------------------------------------------------
# Dispatch / queue helpers
# ---------------------------------------------------------------------------


def _plan_for_candidates(
    pipeline_result: CRPipelineResult,
    candidates: tuple,
    *,
    text_config: object = None,
    total_eligible_count: int | None = None,
    high_score_suppressed_count: int | None = None,
) -> CRDispatchPlan:
    from trendradar.cr.presentation import CRPresentationRun, render_cr_a_text

    suppressed_count = (
        pipeline_result.high_score_suppressed_count
        if high_score_suppressed_count is None
        else high_score_suppressed_count
    )
    run = CRPresentationRun(
        run_label=pipeline_result.run_label,
        candidates=list(candidates),
        coverage_warning=pipeline_result.coverage_warning,
        total_eligible_count=(
            len(candidates) if total_eligible_count is None else total_eligible_count
        ),
        high_score_suppressed_count=suppressed_count,
    )
    filtered = CRPipelineResult(
        run_label=pipeline_result.run_label,
        primitives=pipeline_result.primitives,
        candidates=pipeline_result.candidates,
        score_results=pipeline_result.score_results,
        decisions=pipeline_result.decisions,
        presented_candidates=pipeline_result.presented_candidates,
        cr_a_candidates=candidates,
        cr_a_text=render_cr_a_text(run, config=text_config),
        markdown_audit_text=pipeline_result.markdown_audit_text,
        html_audit_text=pipeline_result.html_audit_text,
        high_score_suppressed_count=suppressed_count,
        coverage_warning=pipeline_result.coverage_warning,
    )
    return build_cr_a_dispatch_plan(filtered)


def _count_high_score_cooldown_suppressed(
    candidates: tuple,
    eligible_candidates: tuple,
    *,
    urgent_threshold: float,
) -> int:
    """Count urgent-score candidates removed by cooldown/repeat enforcement."""
    eligible_event_keys = {
        stable_event_key_for_candidate(pc) for pc in eligible_candidates
    }
    return sum(
        1
        for pc in candidates
        if stable_event_key_for_candidate(pc) not in eligible_event_keys
        and pc.total_score >= urgent_threshold
    )


def _count_fresh_high_score_suppressed(
    presented_candidates: list,
    *,
    urgent_threshold: float,
) -> int:
    """Count decision-layer suppressions backed by current-run evidence."""
    return sum(
        1
        for pc in presented_candidates
        if pc.decision_level == DECISION_SUPPRESS
        and pc.total_score >= urgent_threshold
    )


def _single_candidate_message(
    pc: object,
    *,
    run_label: str,
    high_score_suppressed_count: int,
    coverage_warning: str | None = None,
) -> CRDispatchMessage:
    from trendradar.cr.presentation import CRPresentationRun, render_cr_a_text

    run = CRPresentationRun(
        run_label=run_label,
        candidates=[pc],
        high_score_suppressed_count=high_score_suppressed_count,
        coverage_warning=coverage_warning,
    )
    level = getattr(pc, "decision_level", None)
    return CRDispatchMessage(
        text=render_cr_a_text(run),
        format="plain_text",
        candidate_count=1,
        run_label=run_label,
        urgent_count=1 if level == DECISION_URGENT else 0,
        high_score_suppressed_count=high_score_suppressed_count,
    )


def _candidate_payload(pc: object) -> dict[str, object]:
    return {
        "candidate_id": getattr(pc, "candidate_id", None),
        "event_key": stable_event_key_for_candidate(pc),
        "title": getattr(pc, "display_title", None),
        "level": getattr(pc, "decision_level", None),
        "score": getattr(pc, "total_score", None),
        "representative_url": getattr(pc, "representative_url", None),
        "trigger_reasons": list(getattr(pc, "trigger_reasons", []) or []),
        "suppress_labels": list(getattr(pc, "suppress_labels", []) or []),
    }


def _deferred_entry_for_candidate(
    pc: object,
    *,
    deferred_at: str,
    deferred_until: str,
    run_label: str,
    high_score_suppressed_count: int,
    coverage_warning: str | None = None,
) -> CRDeferredDispatchEntry:
    event_key = stable_event_key_for_candidate(pc)
    message = _single_candidate_message(
        pc,
        run_label=run_label,
        high_score_suppressed_count=high_score_suppressed_count,
        coverage_warning=coverage_warning,
    )
    return CRDeferredDispatchEntry(
        entry_id=stable_deferred_entry_id(event_key),
        event_key=event_key,
        candidate_id=getattr(pc, "candidate_id"),
        title=getattr(pc, "display_title"),
        level=getattr(pc, "decision_level"),
        score=float(getattr(pc, "total_score")),
        deferred_at=deferred_at,
        deferred_until=deferred_until,
        reason="quiet_hours",
        message_text=message.text,
        candidate_payload=_candidate_payload(pc),
        last_seen_at=deferred_at,
    )


def _queue_with_candidates(
    queue: CRDeferredDispatchQueue,
    candidates: tuple,
    *,
    deferred_at: str,
    deferred_until: str,
    run_label: str,
    high_score_suppressed_count: int,
    coverage_warning: str | None = None,
) -> tuple[CRDeferredDispatchQueue, tuple[CRDeferredQueueUpsertResult, ...]]:
    updated = queue
    outcomes: list[CRDeferredQueueUpsertResult] = []
    for pc in candidates:
        entry = _deferred_entry_for_candidate(
            pc,
            deferred_at=deferred_at,
            deferred_until=deferred_until,
            run_label=run_label,
            high_score_suppressed_count=high_score_suppressed_count,
            coverage_warning=coverage_warning,
        )
        result = upsert_deferred_entry(updated, entry)
        updated = result.queue
        outcomes.append(result)
    return updated, tuple(outcomes)


def _deferred_receipts_for_upserts(
    outcomes: tuple[CRDeferredQueueUpsertResult, ...],
    *,
    deferred_until: str | None,
    queue_state_current: bool,
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    for index, outcome in enumerate(outcomes):
        if outcome.outcome == "skipped":
            status = STATUS_SKIPPED_DEFERRED_QUEUE_UPSERT
            detail = outcome.reason
        elif queue_state_current:
            status = STATUS_DEFERRED_QUIET_HOURS
            detail = f"quiet_hours_{outcome.outcome}"
        else:
            status = STATUS_SKIPPED_DEFERRED_QUEUE_ERROR
            detail = "deferred_queue_save_failed"
        receipts.append({
            "message_index": index,
            "attempted": False,
            "accepted": False,
            "status": status,
            "detail": detail,
            "transport": None,
            "http_status": None,
            "sink_ok": None,
            "exception_type": None,
            "exception_message": None,
            "deferred_until": deferred_until,
            "deferred_upsert_outcome": outcome.outcome,
            "deferred_upsert_reason": outcome.reason,
            "event_key": outcome.event_key,
            "candidate_id": outcome.candidate_id,
        })
    return receipts


def _flush_receipt_entry(
    *,
    message_index: int,
    attempted: bool,
    accepted: bool,
    status: str,
    detail: str,
    entry: CRDeferredDispatchEntry,
) -> dict[str, object]:
    return {
        "message_index": message_index,
        "attempted": attempted,
        "accepted": accepted,
        "status": status,
        "detail": detail,
        "transport": None,
        "http_status": None,
        "sink_ok": None,
        "exception_type": None,
        "exception_message": None,
        "source": "deferred_queue",
        "event_key": entry.event_key,
        "candidate_id": entry.candidate_id,
    }


def _flush_deferred_queue(
    queue: CRDeferredDispatchQueue,
    *,
    sink: CRDispatchSink | None,
    run_label: str,
) -> tuple[list[dict[str, object]], set[str]]:
    receipts: list[dict[str, object]] = []
    accepted_event_keys: set[str] = set()
    for index, entry in enumerate(ordered_entries_for_flush(queue)):
        if sink is None:
            receipts.append(
                _flush_receipt_entry(
                    message_index=index,
                    attempted=False,
                    accepted=False,
                    status="not_configured",
                    detail="deferred_flush_not_configured",
                    entry=entry,
                )
            )
            continue
        message = CRDispatchMessage(
            text=entry.message_text,
            format="plain_text",
            candidate_count=1,
            run_label=run_label,
            urgent_count=1 if entry.level == DECISION_URGENT else 0,
            high_score_suppressed_count=0,
        )
        try:
            sink_receipt = sink.submit(message, message_index=index)
        except TRANSPORT_EXCEPTIONS as exc:
            receipts.append(
                _flush_receipt_entry(
                    message_index=index,
                    attempted=True,
                    accepted=False,
                    status="failed_transport",
                    detail=type(exc).__name__,
                    entry=entry,
                )
            )
            continue
        status = sink_receipt.status
        if status not in {
            "accepted",
            "accepted_partial",
            "rejected",
            "failed_transport",
            "http_error",
        }:
            status = "unknown"
        detail = "flushed_deferred" if sink_receipt.accepted else sink_receipt.detail
        receipts.append(
            _flush_receipt_entry(
                message_index=index,
                attempted=True,
                accepted=sink_receipt.accepted,
                status=status,
                detail=detail,
                entry=entry,
            )
        )
        if sink_receipt.accepted:
            accepted_event_keys.add(entry.event_key)
    return receipts, accepted_event_keys


def _state_entries_for_candidates(
    candidates: tuple,
    *,
    seen_at: str,
) -> list[CREventStateEntry]:
    return [
        CREventStateEntry(
            event_key=stable_event_key_for_candidate(pc),
            decision_level=pc.decision_level,
            score=pc.total_score,
            seen_at=seen_at,
            title=pc.display_title,
            candidate_id=pc.candidate_id,
        )
        for pc in candidates
    ]


def _state_entries_for_queue(
    entries: tuple[CRDeferredDispatchEntry, ...],
    *,
    accepted_keys: set[str],
    seen_at: str,
) -> list[CREventStateEntry]:
    return [
        CREventStateEntry(
            event_key=build_cr_event_identity_from_input(
                CREventIdentityInput(title=entry.title)
            ).event_key,
            decision_level=entry.level,
            score=entry.score,
            seen_at=seen_at,
            title=entry.title,
            candidate_id=entry.candidate_id,
        )
        for entry in entries
        if entry.event_key in accepted_keys
    ]


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


def build_and_write_cr_runtime_dry_run(
    *,
    hotlist_stats: list[dict] | None = None,
    rss_stats: list[dict] | None = None,
    run_label: str,
    run_context: CRRunContext | None = None,
    pipeline_config: CRPipelineConfig | None = None,
    artifact_config: CRArtifactConfig | None = None,
    urgent_threshold: float = DEFAULT_CR_URGENT_THRESHOLD,
    dispatch_sink: CRDispatchSink | None = None,
    dispatch_mode: str | None = None,
    dispatch_state_path: str | Path | None = None,
    include_cooldown_audit: bool = False,
    cooldown_policy: CRCooldownPolicy | None = None,
    cooldown_prior_snapshot: CREventStateSnapshot | None = None,
    cooldown_prior_snapshot_path: str | Path | None = None,
    cooldown_next_snapshot_path: str | Path | None = None,
    quiet_hours_env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    deferred_queue_path: str | Path | None = None,
) -> CRRuntimeDryRunResult:
    """Convert real runtime stats and write CR audit artifacts (dry-run).

    Steps:
      1. Convert ``hotlist_stats`` to primitives via :func:`adapt_hotlist_stats`.
      2. Convert ``rss_stats`` to primitives via :func:`adapt_rss_stats`.
      3. Combine deterministically (hotlist first, then RSS).
      4. Build the CR pipeline via :func:`build_cr_pipeline_from_primitives`.
      5. Write artifacts via :func:`write_cr_pipeline_artifacts`.
      6. Plan CR-A dispatch via :func:`build_cr_a_dispatch_plan` (pure — sends
         nothing).
      7. Optionally execute the plan against a local ``dispatch_sink`` when one
         is supplied (injected local sink only — no real delivery).
      8. Return a :class:`CRRuntimeDryRunResult`.

    Parameters
    ----------
    hotlist_stats:
        Output of the runtime's keyword-frequency stats (``count_frequency``
        / ``count_word_frequency``).  ``None`` means no hotlist input.
    rss_stats:
        Output of the runtime's RSS stats (``count_rss_frequency`` /
        matched RSS items).  ``None`` means no RSS input.
    run_label:
        Human-readable run label (e.g. ``"2026-06-10 09:00"``).
    run_context:
        Run-level adapter context (mode / first_crawl_of_day).  Defaults to a
        neutral ``CRRunContext()`` (mode ``"unknown"``) when omitted.
    pipeline_config:
        Optional pipeline config; lower-layer defaults are used when ``None``.
    artifact_config:
        Optional artifact config; CR artifact defaults are used when ``None``.
    urgent_threshold:
        Score threshold passed through to the pipeline.
    dispatch_sink:
        Optional injected local sink.  When provided, the dispatch plan is
        executed against it and the result is stored in ``dispatch_execution``.
        When ``None`` (default), dispatch is not executed and
        ``dispatch_execution`` is ``None``.  No real delivery either way.
    dispatch_mode:
        Active CR dispatch mode (``artifact``, ``shadow``, or ``live``).
        When provided, the dispatch plan and receipt JSON are written with
        this mode recorded.  When ``None`` (default), the mode field defaults
        to ``artifact``.
    dispatch_state_path:
        Path to the CR dispatch state JSON file.  When provided, cooldown
        enforcement reads prior dispatch state from this path and (for live
        mode only) writes updated state after accepted dispatch.  When
        ``None`` (default), ``DEFAULT_DISPATCH_STATE_PATH`` is used.
    include_cooldown_audit:
        Opt-in, artifact-only flag (default ``False``).  When ``True``, the
        Markdown / HTML audit artifacts additionally render repeat-preview and
        cooldown-policy-preview evidence, and ``cooldown_audit`` is populated
        with the PR10e audit context.  This is observability only: prior state
        is used only when explicitly supplied in memory or loaded read-only
        from an explicit local path, no state is written, the CR-A text and
        dispatch plan are unaffected, and nothing is enforced or suppressed.
        When ``False`` (default), artifact output is byte-for-byte unchanged.
    cooldown_policy:
        Optional cooldown policy used only when ``include_cooldown_audit`` is
        ``True``.  Defaults to ``CRCooldownPolicy()``.  Ignored otherwise.
    cooldown_prior_snapshot:
        Optional explicit, in-memory prior event state snapshot (PR10g) used
        only when ``include_cooldown_audit`` is ``True``.  When provided, each
        candidate's repeat preview and cooldown decision are evaluated against
        it, so the artifacts can show real ``same_level_repeat`` /
        ``meaningful_escalation`` evidence.  When ``None`` (default), behavior
        is identical to PR10f (``not_evaluated``) unless
        ``cooldown_prior_snapshot_path`` is supplied.  Ignored when
        ``include_cooldown_audit`` is ``False``.
    cooldown_prior_snapshot_path:
        Optional explicit local JSON path (PR10h) used only when
        ``include_cooldown_audit`` is ``True`` and
        ``cooldown_prior_snapshot`` is ``None``.  The path is loaded read-only
        through ``load_cr_event_state_snapshot``.  Missing files are treated as
        a known-empty prior state; malformed or invalid files fail closed to no
        prior snapshot.  No default path, environment/config path, or
        write-back is used.  Ignored when ``include_cooldown_audit`` is
        ``False``.
    cooldown_next_snapshot_path:
        Optional explicit local JSON output path (PR10j) used only when
        ``include_cooldown_audit`` is ``True``.  When provided and the
        transition preview has a valid next snapshot, that snapshot is written
        through ``save_cr_event_state_snapshot`` and the result is returned in
        ``cooldown_next_snapshot_save``.  No default path, environment/config
        path, production persistence, dispatch change, or suppression behavior
        is used.  Ignored when ``include_cooldown_audit`` is ``False``.

    Returns
    -------
    CRRuntimeDryRunResult

    Notes
    -----
    Does not score, cluster, decide, or render manually — every transformation
    is delegated to the existing CR layers.  Does not write files except
    through :func:`write_cr_pipeline_artifacts` and the explicit PR10j
    ``cooldown_next_snapshot_path`` state-store boundary.  Does not catch or
    suppress structural pipeline errors.

    If neither stats source is provided, an empty primitive tuple is produced
    and an empty (but valid) pipeline is still built and written.
    """
    context = run_context if run_context is not None else CRRunContext()

    primitives: list[CRPrimitiveRecord] = []

    # 1. Hotlist primitives first (deterministic ordering preserved by adapter).
    if hotlist_stats is not None:
        primitives.extend(adapt_hotlist_stats(hotlist_stats, context=context))

    # 2. RSS primitives second.
    if rss_stats is not None:
        primitives.extend(adapt_rss_stats(rss_stats, context=context))

    # 3. Freeze combined ordering.
    primitives_tuple = tuple(primitives)

    # 3b. Optionally enable audit-only cooldown evidence in the artifact render
    #     configs.  This is the only effect of ``include_cooldown_audit`` on
    #     rendering; it never touches CR-A text or dispatch.  A prior snapshot
    #     may be supplied directly in memory or loaded read-only from an
    #     explicit local path.  No default path is consulted and no state is
    #     written back.
    cooldown_policy_effective: CRCooldownPolicy | None = None
    effective_pipeline_config = pipeline_config
    input_health = context.input_health
    if input_health is not None:
        effective_pipeline_config = _pipeline_config_with_input_health(
            effective_pipeline_config, input_health,
        )
    cooldown_snapshot_for_audit = cooldown_prior_snapshot
    cooldown_prior_snapshot_load: CREventStateLoadResult | None = None
    if include_cooldown_audit:
        if (
            cooldown_prior_snapshot is not None
            and cooldown_prior_snapshot_path is not None
        ):
            raise ValueError(
                "cooldown_prior_snapshot and cooldown_prior_snapshot_path "
                "are mutually exclusive"
            )

        cooldown_policy_effective = (
            cooldown_policy if cooldown_policy is not None else CRCooldownPolicy()
        )
        if cooldown_prior_snapshot_path is not None:
            cooldown_prior_snapshot_load = load_cr_event_state_snapshot(
                cooldown_prior_snapshot_path
            )
            if cooldown_prior_snapshot_load.error is None:
                cooldown_snapshot_for_audit = cooldown_prior_snapshot_load.snapshot
            else:
                cooldown_snapshot_for_audit = None

        audit_seen_states: dict[str, CRSeenEventState] | None = (
            cr_event_state_snapshot_to_seen_states(cooldown_snapshot_for_audit)
            if cooldown_snapshot_for_audit is not None
            else None
        )
        effective_pipeline_config = _pipeline_config_with_cooldown_audit(
            effective_pipeline_config,
            policy=cooldown_policy_effective,
            seen_event_states=audit_seen_states,
        )

    # 4. Build the pipeline (clustering → scoring → decision → presentation
    #    → Markdown / HTML audit).  Empty input still yields a valid result.
    pipeline_result = build_cr_pipeline_from_primitives(
        primitives_tuple,
        run_label=run_label,
        config=effective_pipeline_config,
        urgent_threshold=urgent_threshold,
        input_health=input_health,
    )
    effective_text_config = (
        effective_pipeline_config.render.text
        if effective_pipeline_config is not None
        else None
    )

    # 4b. Assemble the audit-only cooldown context (PR10e) from the presented
    #     candidates.  The optional prior snapshot is explicit (in memory or
    #     loaded read-only from a caller path).  Proposed updates are in memory
    #     unless the caller also supplies the PR10j explicit next-snapshot
    #     output path below.
    cooldown_audit_context: CRCooldownAuditContext | None = None
    cooldown_state_transition_preview: CREventStateTransitionPreview | None = None
    cooldown_next_snapshot_save: CREventStateSaveResult | None = None
    if include_cooldown_audit:
        cooldown_audit_context = build_cr_cooldown_audit_context(
            pipeline_result.presented_candidates,
            prior_snapshot=cooldown_snapshot_for_audit,
            policy=cooldown_policy_effective,
            seen_at=None,
        )
        cooldown_state_transition_preview = (
            build_cr_event_state_transition_preview(
                prior_snapshot=cooldown_snapshot_for_audit,
                state_updates=cooldown_audit_context.state_updates,
                prior_snapshot_loaded=(
                    cooldown_prior_snapshot_load.loaded
                    if cooldown_prior_snapshot_load is not None
                    else None
                ),
                prior_snapshot_error=(
                    cooldown_prior_snapshot_load.error
                    if cooldown_prior_snapshot_load is not None
                    else None
                ),
            )
        )
        pipeline_result = _pipeline_result_with_state_transition_preview(
            pipeline_result,
            effective_pipeline_config,
            transition_preview=cooldown_state_transition_preview,
            urgent_threshold=urgent_threshold,
        )
        if cooldown_next_snapshot_path is not None:
            next_snapshot = cooldown_state_transition_preview.next_snapshot
            if next_snapshot is not None:
                cooldown_next_snapshot_save = save_cr_event_state_snapshot(
                    next_snapshot,
                    cooldown_next_snapshot_path,
                )

    # 5. Write artifacts only through the existing artifact writer.
    artifact_paths = write_cr_pipeline_artifacts(
        pipeline_result, artifact_config=artifact_config
    )

    # 6. Plan CR-A dispatch (pure — nothing is sent).
    dispatch_plan = build_cr_a_dispatch_plan(pipeline_result)
    effective_high_score_suppressed_count = (
        pipeline_result.high_score_suppressed_count
    )
    effective_dispatch_mode = dispatch_mode or "artifact"
    effective_now = now if now is not None else datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        effective_now = effective_now.replace(tzinfo=timezone.utc)
    now_iso = effective_now.isoformat()
    health_json = (
        input_health_to_json_dict(input_health)
        if input_health is not None else None
    )
    health_blocked = False
    eligible_cr_a_candidates = pipeline_result.cr_a_candidates
    if input_health is not None:
        from trendradar.cr.presentation import (
            count_cr_a_eligible,
            select_cr_a_candidates,
        )

        fresh_presented = [
            pc for pc in pipeline_result.presented_candidates
            if candidate_has_fresh_input(pc)
        ]
        fresh_selected = tuple(
            select_cr_a_candidates(
                fresh_presented, config=effective_text_config
            )
        )
        fresh_suppressed_count = _count_fresh_high_score_suppressed(
            fresh_presented,
            urgent_threshold=urgent_threshold,
        )
        effective_high_score_suppressed_count = fresh_suppressed_count
        if input_health.fail_closed:
            health_blocked = True
        elif fresh_selected or fresh_suppressed_count > 0:
            eligible_cr_a_candidates = fresh_selected
            dispatch_plan = _plan_for_candidates(
                pipeline_result,
                fresh_selected,
                text_config=effective_text_config,
                total_eligible_count=count_cr_a_eligible(fresh_presented),
                high_score_suppressed_count=fresh_suppressed_count,
            )
        else:
            health_blocked = True
        if health_blocked:
            dispatch_plan = CRDispatchPlan(
                should_dispatch=False,
                messages=(),
                reason=input_health.dispatch_block_reason,
                run_label=dispatch_plan.run_label,
                candidate_count=dispatch_plan.candidate_count,
                urgent_count=dispatch_plan.urgent_count,
                high_score_suppressed_count=(
                    effective_high_score_suppressed_count
                ),
            )
    quiet_hours = evaluate_cr_quiet_hours(
        quiet_hours_env,
        now=effective_now,
    )
    effective_queue_path = deferred_queue_path or DEFAULT_DEFERRED_QUEUE_PATH

    # 6a. Load prior dispatch state and enforce cooldown (PR-CR-A4).
    effective_state_path = dispatch_state_path or DEFAULT_DISPATCH_STATE_PATH
    dispatch_state_load = (
        CREventStateLoadResult(
            snapshot=empty_cr_event_state_snapshot(),
            loaded=False,
            error=None,
            path=str(effective_state_path),
        )
        if health_blocked
        else load_cr_event_state_snapshot(effective_state_path)
    )
    prior_snapshot_provided = dispatch_state_load.loaded
    state_load_error: str | None = dispatch_state_load.error
    seen_states: dict[str, CRSeenEventState] | None = None
    if dispatch_state_load.error is None:
        seen_states = cr_event_state_snapshot_to_seen_states(
            dispatch_state_load.snapshot
        )

    deferred_queue_load: CRDeferredQueueLoadResult | None = None
    deferred_queue_save: CRDeferredQueueSaveResult | None = None
    pre_receipts: list[dict[str, object]] = []
    override_receipts: list[dict[str, object]] | None = None
    queue_error_reason: str | None = None
    state_update_entries: list[CREventStateEntry] = []

    # 6b. Live post-quiet flush happens before current-run cooldown checks so
    #     accepted flushes become prior state for the current run.
    if (
        effective_dispatch_mode == "live"
        and not health_blocked
        and quiet_hours.enabled
        and quiet_hours.decision != "quiet_hours_config_error"
        and not quiet_hours.in_quiet_hours
    ):
        deferred_queue_load = load_deferred_dispatch_queue(effective_queue_path)
        if deferred_queue_load.error is not None:
            queue_error_reason = "skipped_deferred_queue_error"
            dispatch_plan = CRDispatchPlan(
                should_dispatch=False,
                messages=(),
                reason=queue_error_reason,
                run_label=dispatch_plan.run_label,
                candidate_count=dispatch_plan.candidate_count,
                urgent_count=dispatch_plan.urgent_count,
                high_score_suppressed_count=dispatch_plan.high_score_suppressed_count,
            )
            override_receipts = [{
                "message_index": 0,
                "attempted": False,
                "accepted": False,
                "status": "skipped_deferred_queue_error",
                "detail": "deferred_queue_error",
                "transport": None,
                "http_status": None,
                "sink_ok": None,
                "exception_type": None,
                "exception_message": None,
            }]
        elif deferred_queue_load.queue.entries:
            queue_before_flush = deferred_queue_load.queue
            queue_for_flush = queue_before_flush
            if input_health is not None:
                fresh_event_keys = {
                    stable_event_key_for_candidate(pc)
                    for pc in eligible_cr_a_candidates
                }
                queue_for_flush = replace(
                    queue_before_flush,
                    entries=tuple(
                        entry for entry in queue_before_flush.entries
                        if entry.event_key in fresh_event_keys
                    ),
                )
            pre_receipts, accepted_flush_keys = _flush_deferred_queue(
                queue_for_flush,
                sink=dispatch_sink,
                run_label=run_label,
            )
            if accepted_flush_keys:
                flushed_entries = ordered_entries_for_flush(queue_for_flush)
                state_update_entries.extend(
                    _state_entries_for_queue(
                        flushed_entries,
                        accepted_keys=accepted_flush_keys,
                        seen_at=now_iso,
                    )
                )
                updated_snapshot = merge_cr_event_state_entries(
                    dispatch_state_load.snapshot,
                    tuple(state_update_entries),
                )
                dispatch_state_load = replace(
                    dispatch_state_load,
                    snapshot=updated_snapshot,
                    loaded=True,
                    error=None,
                )
                seen_states = cr_event_state_snapshot_to_seen_states(
                    updated_snapshot
                )
                deferred_queue_save = save_deferred_dispatch_queue(
                    remove_deferred_entries(
                        queue_before_flush, accepted_flush_keys
                    ),
                    effective_queue_path,
                )

    cooldown_enforcement: CRCooldownEnforcementResult | None = None
    cooldown_override_reason: str | None = None
    if (
        dispatch_plan.should_dispatch
        and eligible_cr_a_candidates
        and queue_error_reason is None
        and quiet_hours.decision != "quiet_hours_config_error"
    ):
        cooldown_enforcement = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=eligible_cr_a_candidates,
            seen_states=seen_states,
            prior_snapshot_provided=prior_snapshot_provided,
            state_error=state_load_error,
            policy=cooldown_policy,
            now=effective_now,
        )
        candidates_before_cooldown = eligible_cr_a_candidates
        # Blocker 5: use per-candidate eligible set.
        eligible_cr_a_candidates = cooldown_enforcement.eligible_candidates
        cooldown_suppressed_count = 0
        if cooldown_enforcement.state_error is None:
            cooldown_suppressed_count = _count_high_score_cooldown_suppressed(
                candidates_before_cooldown,
                eligible_cr_a_candidates,
                urgent_threshold=urgent_threshold,
            )
        combined_suppressed_count = (
            effective_high_score_suppressed_count
            + cooldown_suppressed_count
        )
        effective_high_score_suppressed_count = combined_suppressed_count
        if not cooldown_enforcement.should_dispatch:
            if (
                combined_suppressed_count > 0
                and cooldown_enforcement.state_error is None
            ):
                dispatch_plan = _plan_for_candidates(
                    pipeline_result,
                    (),
                    text_config=effective_text_config,
                    high_score_suppressed_count=combined_suppressed_count,
                )
            else:
                cooldown_override_reason = cooldown_enforcement.override_reason
                dispatch_plan = CRDispatchPlan(
                    should_dispatch=False,
                    messages=(),
                    reason=cooldown_override_reason or "skipped_cooldown",
                    run_label=dispatch_plan.run_label,
                    candidate_count=dispatch_plan.candidate_count,
                    urgent_count=dispatch_plan.urgent_count,
                    high_score_suppressed_count=combined_suppressed_count,
                )
        elif (
            eligible_cr_a_candidates != pipeline_result.cr_a_candidates
            or combined_suppressed_count
            != dispatch_plan.high_score_suppressed_count
        ):
            dispatch_plan = _plan_for_candidates(
                pipeline_result,
                eligible_cr_a_candidates,
                text_config=effective_text_config,
                high_score_suppressed_count=combined_suppressed_count,
            )

    # 6c. Apply quiet-hours live policy after cooldown eligibility.
    quiet_bypass_applied = False
    quiet_suppression_summary_deferred = False
    quiet_deferred_candidates: tuple = ()
    quiet_receipts: list[dict[str, object]] = []
    quiet_upsert_outcomes: dict[str, CRDeferredQueueUpsertResult] = {}
    deferred_event_keys: set[str] = set()
    dispatch_execution = None
    execution_state_candidates: tuple = ()

    if not health_blocked and quiet_hours.decision == "quiet_hours_config_error":
        dispatch_plan = CRDispatchPlan(
            should_dispatch=False,
            messages=(),
            reason="quiet_hours_config_error",
            run_label=dispatch_plan.run_label,
            candidate_count=dispatch_plan.candidate_count,
            urgent_count=dispatch_plan.urgent_count,
            high_score_suppressed_count=dispatch_plan.high_score_suppressed_count,
        )
        override_receipts = [{
            "message_index": 0,
            "attempted": False,
            "accepted": False,
            "status": "quiet_hours_config_error",
            "detail": "quiet_hours_config_error",
            "transport": None,
            "http_status": None,
            "sink_ok": None,
            "exception_type": None,
            "exception_message": None,
        }]
    elif (
        effective_dispatch_mode == "live"
        and not health_blocked
        and quiet_hours.enabled
        and quiet_hours.in_quiet_hours
        and queue_error_reason is None
        and cooldown_override_reason is None
        and dispatch_plan.reason == "ready_suppressed_only"
    ):
        # A count-only observability message has no candidate payload to queue
        # and never bypasses quiet hours.  A later non-quiet run may emit a new
        # summary if suppression is still observed then.
        quiet_suppression_summary_deferred = True
        dispatch_plan = replace(
            dispatch_plan,
            should_dispatch=False,
            messages=(),
            reason="deferred_quiet_hours",
        )
    elif (
        effective_dispatch_mode == "live"
        and not health_blocked
        and quiet_hours.enabled
        and quiet_hours.in_quiet_hours
        and queue_error_reason is None
        and cooldown_override_reason is None
        and dispatch_plan.should_dispatch
        and eligible_cr_a_candidates
    ):
        deferred_queue_load = load_deferred_dispatch_queue(effective_queue_path)
        if deferred_queue_load.error is not None:
            queue_error_reason = "skipped_deferred_queue_error"
            dispatch_plan = CRDispatchPlan(
                should_dispatch=False,
                messages=(),
                reason=queue_error_reason,
                run_label=dispatch_plan.run_label,
                candidate_count=dispatch_plan.candidate_count,
                urgent_count=dispatch_plan.urgent_count,
                high_score_suppressed_count=dispatch_plan.high_score_suppressed_count,
            )
            override_receipts = [{
                "message_index": 0,
                "attempted": False,
                "accepted": False,
                "status": "skipped_deferred_queue_error",
                "detail": "deferred_queue_error",
                "transport": None,
                "http_status": None,
                "sink_ok": None,
                "exception_type": None,
                "exception_message": None,
            }]
        else:
            bypass_candidates = tuple(
                pc for pc in eligible_cr_a_candidates
                if pc.decision_level == DECISION_URGENT
                and quiet_hours.allow_urgent_bypass
            )
            quiet_deferred_candidates = tuple(
                pc for pc in eligible_cr_a_candidates
                if pc not in bypass_candidates
            )
            if bypass_candidates:
                dispatch_plan = _plan_for_candidates(
                    pipeline_result,
                    bypass_candidates,
                    text_config=effective_text_config,
                    high_score_suppressed_count=(
                        effective_high_score_suppressed_count
                    ),
                )
                quiet_bypass_applied = True
                execution_state_candidates = bypass_candidates
                if dispatch_sink is not None:
                    dispatch_execution = execute_cr_dispatch_plan(
                        dispatch_plan, sink=dispatch_sink
                    )
                accepted_bypass = (
                    dispatch_execution is not None
                    and dispatch_execution.accepted_count > 0
                    and dispatch_execution.receipts
                    and dispatch_execution.receipts[0].accepted
                )
                if accepted_bypass:
                    state_update_entries.extend(
                        _state_entries_for_candidates(
                            bypass_candidates, seen_at=now_iso
                        )
                    )
                    stale_keys = {stable_event_key_for_candidate(pc) for pc in bypass_candidates}
                    base_queue = deferred_queue_load.queue
                    updated_queue = remove_deferred_entries(
                        base_queue, stale_keys
                    )
                    if updated_queue.entries != base_queue.entries:
                        deferred_queue_save = save_deferred_dispatch_queue(
                            updated_queue,
                            effective_queue_path,
                        )
                        if not deferred_queue_save.saved:
                            queue_error_reason = "skipped_deferred_queue_error"
                else:
                    quiet_deferred_candidates = (
                        quiet_deferred_candidates + bypass_candidates
                    )
            else:
                dispatch_plan = CRDispatchPlan(
                    should_dispatch=False,
                    messages=(),
                    reason="deferred_quiet_hours",
                    run_label=dispatch_plan.run_label,
                    candidate_count=dispatch_plan.candidate_count,
                    urgent_count=dispatch_plan.urgent_count,
                    high_score_suppressed_count=dispatch_plan.high_score_suppressed_count,
                )

            if quiet_deferred_candidates:
                deferred_until = (
                    quiet_hours.deferred_until.isoformat()
                    if quiet_hours.deferred_until is not None
                    else now_iso
                )
                updated_queue, upsert_outcomes = _queue_with_candidates(
                    deferred_queue_load.queue,
                    quiet_deferred_candidates,
                    deferred_at=now_iso,
                    deferred_until=deferred_until,
                    run_label=run_label,
                    high_score_suppressed_count=(
                        effective_high_score_suppressed_count
                    ),
                    coverage_warning=pipeline_result.coverage_warning,
                )
                queue_changed = (
                    updated_queue.entries != deferred_queue_load.queue.entries
                )
                queue_state_current = not queue_changed
                if queue_changed:
                    deferred_queue_save = save_deferred_dispatch_queue(
                        updated_queue, effective_queue_path
                    )
                    queue_state_current = deferred_queue_save.saved
                    if not queue_state_current:
                        queue_error_reason = "skipped_deferred_queue_error"
                        dispatch_plan = replace(
                            dispatch_plan,
                            reason=queue_error_reason,
                        )
                quiet_receipts = _deferred_receipts_for_upserts(
                    upsert_outcomes,
                    deferred_until=deferred_until,
                    queue_state_current=queue_state_current,
                )
                quiet_upsert_outcomes = {
                    outcome.event_key: outcome for outcome in upsert_outcomes
                }
                if queue_state_current:
                    deferred_event_keys = {
                        outcome.event_key
                        for outcome in upsert_outcomes
                        if outcome.outcome != "skipped"
                    }
                if upsert_outcomes and all(
                    outcome.outcome == "skipped" for outcome in upsert_outcomes
                ) and not bypass_candidates:
                    dispatch_plan = replace(
                        dispatch_plan,
                        reason="skipped_deferred_queue_upsert",
                    )
                if quiet_receipts:
                    if not bypass_candidates:
                        override_receipts = quiet_receipts
                    else:
                        pre_receipts.extend(quiet_receipts)

    # 6d. Build cooldown context for plan JSON (per-candidate entries).
    cooldown_context: dict[str, object] | None = None
    if cooldown_enforcement is not None and cooldown_enforcement.entries:
        eligible_keys = {stable_event_key_for_candidate(pc) for pc in eligible_cr_a_candidates}
        entries_list: list[dict[str, object]] = []
        for e in cooldown_enforcement.entries:
            last_dispatched_at = None
            if seen_states and e.event_key in seen_states:
                last_dispatched_at = seen_states[e.event_key].seen_at
            is_eligible = e.event_key in eligible_keys
            entries_list.append({
                "candidate_id": e.candidate_id,
                "event_key": e.event_key,
                "current_level": e.current_level,
                "last_level": e.previous_level,
                "last_dispatched_at": last_dispatched_at,
                "cooldown_seconds": e.cooldown_seconds,
                "cooldown_remaining_seconds": e.cooldown_remaining_seconds,
                "is_escalation": e.is_escalation,
                "allowed_by_escalation": e.is_escalation and is_eligible,
                "suppressed_by_cooldown": not is_eligible,
                "decision": e.cooldown_action if is_eligible else (
                    cooldown_enforcement.override_reason
                    or cooldown_override_reason
                    or "skipped_cooldown"
                ),
            })
        cooldown_context = {
            "state_available": cooldown_enforcement.state_available,
            "state_error": cooldown_enforcement.state_error,
            "policy_version": "cr-cooldown-v1",
            "entries": entries_list,
        }

    # 6e. Build quiet-hours context for plan JSON.
    quiet_entries: list[dict[str, object]] = []
    for pc in eligible_cr_a_candidates:
        event_key = stable_event_key_for_candidate(pc)
        is_deferred = event_key in deferred_event_keys
        upsert_outcome = quiet_upsert_outcomes.get(event_key)
        allowed = (
            pc.decision_level == DECISION_URGENT
            and quiet_hours.allow_urgent_bypass
            and quiet_hours.in_quiet_hours
        )
        quiet_entries.append({
            "candidate_id": pc.candidate_id,
            "event_key": event_key,
            "level": pc.decision_level,
            "title": pc.display_title,
            "allowed_by_urgent_bypass": allowed,
            "deferred": is_deferred,
            "deferred_until": (
                quiet_hours.deferred_until.isoformat()
                if is_deferred and quiet_hours.deferred_until is not None
                else None
            ),
            "deferred_upsert_outcome": (
                upsert_outcome.outcome if upsert_outcome is not None else None
            ),
            "deferred_upsert_reason": (
                upsert_outcome.reason if upsert_outcome is not None else None
            ),
        })
    quiet_decision = None
    quiet_reason = None
    if quiet_hours.decision == "quiet_hours_config_error":
        quiet_decision = "quiet_hours_config_error"
        quiet_reason = "quiet_hours_config_error"
    elif queue_error_reason is not None:
        quiet_decision = "skipped_deferred_queue_error"
        quiet_reason = "deferred_queue_error"
    elif quiet_suppression_summary_deferred:
        quiet_decision = "deferred_quiet_hours"
        quiet_reason = "quiet_hours_active"
    elif deferred_event_keys:
        quiet_decision = "deferred_quiet_hours"
        quiet_reason = "quiet_hours_active"
    elif quiet_upsert_outcomes:
        quiet_decision = "skipped_deferred_queue_upsert"
        quiet_reason = "deferred_queue_upsert_rejected"
    elif quiet_bypass_applied:
        quiet_decision = "urgent_bypass"
        quiet_reason = "urgent_bypass_allowed"
    quiet_hours_context = quiet_hours_evaluation_to_plan_dict(
        quiet_hours,
        decision=quiet_decision,
        reason=quiet_reason,
        bypass_applied=quiet_bypass_applied,
        deferred_count=len(deferred_event_keys),
        entries=quiet_entries,
    )

    # 6f. Write dispatch plan JSON (PR-CR-A2 + contexts).
    dispatch_plan_json_dict = cr_dispatch_plan_to_json_dict(
        dispatch_plan,
        dispatch_mode=effective_dispatch_mode,
        presented_candidates=pipeline_result.presented_candidates,
        cr_a_candidates=eligible_cr_a_candidates,
        created_at=now_iso,
        cooldown_context=cooldown_context,
        quiet_hours_context=quiet_hours_context,
        input_health=health_json,
    )
    dispatch_plan_json_paths = write_dispatch_plan_json(
        dispatch_plan_json_dict,
        run_label=run_label,
        config=artifact_config,
    )

    # 7. Optionally execute current-run plan when it has not already been
    #    executed by urgent quiet-hours bypass handling.
    if (
        dispatch_execution is None
        and dispatch_sink is not None
        and effective_dispatch_mode == "live"
        and not health_blocked
    ):
        if (
            cooldown_override_reason is None
            and queue_error_reason is None
            and quiet_hours.decision != "quiet_hours_config_error"
            and not (
                quiet_hours.enabled
                and quiet_hours.in_quiet_hours
                and override_receipts is not None
            )
        ):
            execution_state_candidates = eligible_cr_a_candidates
            dispatch_execution = execute_cr_dispatch_plan(
                dispatch_plan, sink=dispatch_sink
            )

    # 7b. Build and write dispatch receipt JSON (PR-CR-A3 + PR-CR-A4 cooldown).
    cooldown_entries_for_receipt = cooldown_context.get("entries") if cooldown_context else None
    dispatch_receipt_json_dict = build_dispatch_receipts_json(
        dispatch_plan,
        dispatch_mode=effective_dispatch_mode,
        execution=dispatch_execution,
        created_at=now_iso,
        cooldown_override_reason=cooldown_override_reason,
        cooldown_entries=cooldown_entries_for_receipt,
        pre_receipts=pre_receipts or None,
        override_receipts=override_receipts,
        input_health=health_json,
    )
    dispatch_receipt_json_paths = write_dispatch_receipts_json(
        dispatch_receipt_json_dict,
        run_label=run_label,
        config=artifact_config,
    )

    # 7c. Update dispatch state on live+accepted only.
    dispatch_state_save: CREventStateSaveResult | None = None
    if (
        effective_dispatch_mode == "live"
        and not health_blocked
        and cooldown_override_reason is None
        and queue_error_reason is None
        and quiet_hours.decision != "quiet_hours_config_error"
        and dispatch_execution is not None
        and dispatch_execution.accepted_count > 0
        and dispatch_execution.receipts
        and dispatch_execution.receipts[0].accepted
    ):
        state_update_entries.extend(
            _state_entries_for_candidates(
                execution_state_candidates,
                seen_at=now_iso,
            )
        )
        if state_update_entries:
            updated_snapshot = merge_cr_event_state_entries(
                dispatch_state_load.snapshot,
                tuple(state_update_entries),
            )
            dispatch_state_save = save_cr_event_state_snapshot(
                updated_snapshot, effective_state_path
            )
    elif (
        state_update_entries and effective_dispatch_mode == "live"
        and not health_blocked
    ):
        updated_snapshot = merge_cr_event_state_entries(
            dispatch_state_load.snapshot,
            tuple(state_update_entries),
        )
        dispatch_state_save = save_cr_event_state_snapshot(
            updated_snapshot, effective_state_path
        )

    # 8. Return.
    return CRRuntimeDryRunResult(
        primitives=primitives_tuple,
        pipeline=pipeline_result,
        artifact_paths=artifact_paths,
        dispatch_plan=dispatch_plan,
        dispatch_plan_json_paths=dispatch_plan_json_paths,
        dispatch_receipt_json_paths=dispatch_receipt_json_paths,
        dispatch_execution=dispatch_execution,
        cooldown_audit=cooldown_audit_context,
        cooldown_prior_snapshot_load=cooldown_prior_snapshot_load,
        cooldown_state_transition_preview=cooldown_state_transition_preview,
        cooldown_next_snapshot_save=cooldown_next_snapshot_save,
        cooldown_enforcement=cooldown_enforcement,
        dispatch_state_save=dispatch_state_save,
        quiet_hours=quiet_hours,
        deferred_queue_load=deferred_queue_load,
        deferred_queue_save=deferred_queue_save,
        input_health=input_health,
    )
