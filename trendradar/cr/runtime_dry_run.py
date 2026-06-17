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
    execute_cr_dispatch_plan,
)
from trendradar.cr.dispatch_plan import (
    CRDispatchPlan,
    build_cr_a_dispatch_plan,
    cr_dispatch_plan_to_json_dict,
)
from trendradar.cr.dispatch_receipt import build_dispatch_receipts_json
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
from trendradar.cr.state_snapshot import (
    CREventStateSnapshot,
    cr_event_state_snapshot_to_seen_states,
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


# ---------------------------------------------------------------------------
# Audit-only render config assembly (artifact reporting only)
# ---------------------------------------------------------------------------


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
    urgent_threshold: float = 80.0,
    dispatch_sink: CRDispatchSink | None = None,
    dispatch_mode: str | None = None,
    dispatch_state_path: str | Path | None = None,
    include_cooldown_audit: bool = False,
    cooldown_policy: CRCooldownPolicy | None = None,
    cooldown_prior_snapshot: CREventStateSnapshot | None = None,
    cooldown_prior_snapshot_path: str | Path | None = None,
    cooldown_next_snapshot_path: str | Path | None = None,
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
            pipeline_config,
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
    effective_dispatch_mode = dispatch_mode or "artifact"
    now = datetime.now(timezone.utc)

    # 6a. Load prior dispatch state and enforce cooldown (PR-CR-A4).
    effective_state_path = dispatch_state_path or DEFAULT_DISPATCH_STATE_PATH
    dispatch_state_load = load_cr_event_state_snapshot(effective_state_path)
    prior_snapshot_provided = dispatch_state_load.loaded
    state_load_error: str | None = dispatch_state_load.error
    seen_states: dict[str, CRSeenEventState] | None = None
    if dispatch_state_load.error is None:
        seen_states = cr_event_state_snapshot_to_seen_states(
            dispatch_state_load.snapshot
        )

    cooldown_enforcement: CRCooldownEnforcementResult | None = None
    cooldown_override_reason: str | None = None
    eligible_cr_a_candidates = pipeline_result.cr_a_candidates  # default: all
    if dispatch_plan.should_dispatch and pipeline_result.cr_a_candidates:
        cooldown_enforcement = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=pipeline_result.cr_a_candidates,
            seen_states=seen_states,
            prior_snapshot_provided=prior_snapshot_provided,
            state_error=state_load_error,
            policy=cooldown_policy,
            now=now,
        )
        # Blocker 5: use per-candidate eligible set.
        eligible_cr_a_candidates = cooldown_enforcement.eligible_candidates
        if not cooldown_enforcement.should_dispatch:
            cooldown_override_reason = cooldown_enforcement.override_reason
            dispatch_plan = CRDispatchPlan(
                should_dispatch=False,
                messages=(),
                reason=cooldown_override_reason or "skipped_cooldown",
                run_label=dispatch_plan.run_label,
                candidate_count=dispatch_plan.candidate_count,
                urgent_count=dispatch_plan.urgent_count,
                high_score_suppressed_count=dispatch_plan.high_score_suppressed_count,
            )
        elif eligible_cr_a_candidates != pipeline_result.cr_a_candidates:
            # Some candidates filtered out — rebuild plan with eligible only.
            # Regenerate cr_a_text from filtered candidates.
            from trendradar.cr.pipeline import CRPipelineResult
            from trendradar.cr.presentation import (
                CRPresentationRun,
                render_cr_a_text,
            )
            eligible_run = CRPresentationRun(
                run_label=pipeline_result.run_label,
                candidates=list(eligible_cr_a_candidates),
                high_score_suppressed_count=pipeline_result.high_score_suppressed_count,
            )
            filtered_cr_a_text = render_cr_a_text(eligible_run)
            filtered_pipeline = CRPipelineResult(
                run_label=pipeline_result.run_label,
                primitives=pipeline_result.primitives,
                candidates=pipeline_result.candidates,
                score_results=pipeline_result.score_results,
                decisions=pipeline_result.decisions,
                presented_candidates=pipeline_result.presented_candidates,
                cr_a_candidates=eligible_cr_a_candidates,
                cr_a_text=filtered_cr_a_text,
                markdown_audit_text=pipeline_result.markdown_audit_text,
                html_audit_text=pipeline_result.html_audit_text,
                high_score_suppressed_count=pipeline_result.high_score_suppressed_count,
            )
            dispatch_plan = build_cr_a_dispatch_plan(filtered_pipeline)

    # 6b. Build cooldown context for plan JSON (per-candidate entries).
    cooldown_context: dict[str, object] | None = None
    if cooldown_enforcement is not None and cooldown_enforcement.entries:
        eligible_keys = {pc.cluster_key for pc in eligible_cr_a_candidates}
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
                    cooldown_override_reason or "skipped_cooldown"
                ),
            })
        cooldown_context = {
            "state_available": cooldown_enforcement.state_available,
            "state_error": cooldown_enforcement.state_error,
            "policy_version": "cr-cooldown-v1",
            "entries": entries_list,
        }

    # 6c. Write dispatch plan JSON (PR-CR-A2 + PR-CR-A4 cooldown context).
    dispatch_plan_json_dict = cr_dispatch_plan_to_json_dict(
        dispatch_plan,
        dispatch_mode=effective_dispatch_mode,
        presented_candidates=pipeline_result.presented_candidates,
        cr_a_candidates=eligible_cr_a_candidates,
        created_at=now.isoformat(),
        cooldown_context=cooldown_context,
    )
    dispatch_plan_json_paths = write_dispatch_plan_json(
        dispatch_plan_json_dict,
        run_label=run_label,
        config=artifact_config,
    )

    # 7. Optionally execute against an injected local sink (no real delivery).
    # Blocker 3: only execute sink in live mode when not cooldown-overridden.
    dispatch_execution = None
    if dispatch_sink is not None and effective_dispatch_mode == "live":
        if cooldown_override_reason is None:
            dispatch_execution = execute_cr_dispatch_plan(
                dispatch_plan, sink=dispatch_sink
            )

    # 7b. Build and write dispatch receipt JSON (PR-CR-A3 + PR-CR-A4 cooldown).
    cooldown_entries_for_receipt = cooldown_context.get("entries") if cooldown_context else None
    dispatch_receipt_json_dict = build_dispatch_receipts_json(
        dispatch_plan,
        dispatch_mode=effective_dispatch_mode,
        execution=dispatch_execution,
        created_at=now.isoformat(),
        cooldown_override_reason=cooldown_override_reason,
        cooldown_entries=cooldown_entries_for_receipt,
    )
    dispatch_receipt_json_paths = write_dispatch_receipts_json(
        dispatch_receipt_json_dict,
        run_label=run_label,
        config=artifact_config,
    )

    # 7c. Update dispatch state on live+accepted (PR-CR-A4).
    # Blocker 4: update all eligible CR-A candidates, not just first.
    dispatch_state_save: CREventStateSaveResult | None = None
    if (
        effective_dispatch_mode == "live"
        and cooldown_override_reason is None
        and dispatch_execution is not None
        and dispatch_execution.accepted_count > 0
        and dispatch_execution.receipts
        and dispatch_execution.receipts[0].accepted
    ):
        from trendradar.cr.state_snapshot import (
            CREventStateEntry,
            merge_cr_event_state_entries,
        )
        # Blocker 2: use pc.cluster_key as canonical event key.
        update_entries: list[CREventStateEntry] = []
        for pc in eligible_cr_a_candidates:
            update_entries.append(CREventStateEntry(
                event_key=pc.cluster_key,
                decision_level=pc.decision_level,
                score=pc.total_score,
                seen_at=now.isoformat(),
                title=pc.display_title,
                candidate_id=pc.candidate_id,
            ))
        if update_entries:
            updated_snapshot = merge_cr_event_state_entries(
                dispatch_state_load.snapshot,
                tuple(update_entries),
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
    )
