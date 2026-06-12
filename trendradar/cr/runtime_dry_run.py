# coding=utf-8
"""
CR runtime dry-run hook (PR9k) v0.1.

CR-internal glue that connects real runtime-produced hotlist / RSS stats to
the offline CR pipeline, then writes Markdown / HTML audit artifacts.

This is a *dry-run* bridge only.  It answers exactly one system question:

    Can the existing runtime produce CR Markdown / HTML artifacts from real
    hotlist / RSS stats without sending anything?

It deliberately stays inside the CR layer: it only converts stats via the
existing CR adapter, runs the existing CR pipeline, and writes through the
existing CR artifact writer.  It performs no delivery, no suppression /
de-duplication, no run-to-run state, no AI-result integration, and reads no
runtime configuration.  CR-A text and JSON outputs are out of scope here.

Design reference: PR9k.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from trendradar.cr.adapter import adapt_hotlist_stats, adapt_rss_stats
from trendradar.cr.artifacts import CRArtifactConfig, CRArtifactPaths
from trendradar.cr.cooldown_audit import (
    CRCooldownAuditContext,
    build_cr_cooldown_audit_context,
)
from trendradar.cr.cooldown_policy import CRCooldownPolicy
from trendradar.cr.dispatch_executor import (
    CRDispatchExecutionResult,
    CRDispatchSink,
    execute_cr_dispatch_plan,
)
from trendradar.cr.dispatch_plan import CRDispatchPlan, build_cr_a_dispatch_plan
from trendradar.cr.html import CRHTMLRenderConfig
from trendradar.cr.markdown import CRMarkdownRenderConfig
from trendradar.cr.models import CRPrimitiveRecord, CRRunContext
from trendradar.cr.pipeline import (
    CRPipelineConfig,
    CRPipelineRenderConfig,
    CRPipelineResult,
    build_cr_pipeline_from_primitives,
    write_cr_pipeline_artifacts,
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
    in memory from the presented candidates — it enforces nothing, reads no
    state file, and writes no state.  The proposed next-state entries it holds
    are never persisted.
    """

    primitives: tuple[CRPrimitiveRecord, ...]
    pipeline: CRPipelineResult
    artifact_paths: CRArtifactPaths
    dispatch_plan: CRDispatchPlan
    dispatch_execution: CRDispatchExecutionResult | None = None
    cooldown_audit: CRCooldownAuditContext | None = None


# ---------------------------------------------------------------------------
# Audit-only render config assembly (artifact reporting only)
# ---------------------------------------------------------------------------


def _pipeline_config_with_cooldown_audit(
    pipeline_config: CRPipelineConfig | None,
    *,
    policy: CRCooldownPolicy,
) -> CRPipelineConfig:
    """Return a pipeline config whose Markdown/HTML render configs show the
    audit-only cooldown evidence.

    Pure config assembly: it only flips ``include_repeat_preview`` /
    ``include_cooldown_decision`` on and attaches the cooldown ``policy``.
    Because no prior snapshot is read here, ``seen_event_states`` is left as
    ``None`` (no prior state provided), so the rendered repeat/cooldown
    evidence is ``not_evaluated`` — matching the audit context built with
    ``prior_snapshot=None``.  It reads no state file and changes neither the
    CR-A text config nor any dispatch behavior.
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
        seen_event_states=None,
        cooldown_policy=policy,
    )
    audit_html = replace(
        base_html,
        include_repeat_preview=True,
        include_cooldown_decision=True,
        seen_event_states=None,
        cooldown_policy=policy,
    )
    audit_render = replace(base_render, markdown=audit_md, html=audit_html)

    if pipeline_config is None:
        return CRPipelineConfig(render=audit_render)
    return replace(pipeline_config, render=audit_render)


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
    include_cooldown_audit: bool = False,
    cooldown_policy: CRCooldownPolicy | None = None,
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
    include_cooldown_audit:
        Opt-in, artifact-only flag (default ``False``).  When ``True``, the
        Markdown / HTML audit artifacts additionally render repeat-preview and
        cooldown-policy-preview evidence, and ``cooldown_audit`` is populated
        with the PR10e audit context.  This is observability only: no prior
        state file is read, no state is written, the CR-A text and dispatch
        plan are unaffected, and nothing is enforced or suppressed.  When
        ``False`` (default), artifact output is byte-for-byte unchanged.
    cooldown_policy:
        Optional cooldown policy used only when ``include_cooldown_audit`` is
        ``True``.  Defaults to ``CRCooldownPolicy()``.  Ignored otherwise.

    Returns
    -------
    CRRuntimeDryRunResult

    Notes
    -----
    Does not score, cluster, decide, or render manually — every transformation
    is delegated to the existing CR layers.  Does not write files except
    through :func:`write_cr_pipeline_artifacts`.  Does not catch or suppress
    structural pipeline errors.

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
    #     rendering; it never touches CR-A text or dispatch and reads no state.
    cooldown_policy_effective: CRCooldownPolicy | None = None
    effective_pipeline_config = pipeline_config
    if include_cooldown_audit:
        cooldown_policy_effective = (
            cooldown_policy if cooldown_policy is not None else CRCooldownPolicy()
        )
        effective_pipeline_config = _pipeline_config_with_cooldown_audit(
            pipeline_config, policy=cooldown_policy_effective
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
    #     candidates.  Built in memory only — no prior snapshot is read, no
    #     state is written, and the proposed next-state entries are never
    #     persisted.
    cooldown_audit_context: CRCooldownAuditContext | None = None
    if include_cooldown_audit:
        cooldown_audit_context = build_cr_cooldown_audit_context(
            pipeline_result.presented_candidates,
            prior_snapshot=None,
            policy=cooldown_policy_effective,
            seen_at=None,
        )

    # 5. Write artifacts only through the existing artifact writer.
    artifact_paths = write_cr_pipeline_artifacts(
        pipeline_result, artifact_config=artifact_config
    )

    # 6. Plan CR-A dispatch (pure — nothing is sent).
    dispatch_plan = build_cr_a_dispatch_plan(pipeline_result)

    # 7. Optionally execute against an injected local sink (no real delivery).
    dispatch_execution = None
    if dispatch_sink is not None:
        dispatch_execution = execute_cr_dispatch_plan(
            dispatch_plan, sink=dispatch_sink
        )

    # 8. Return.
    return CRRuntimeDryRunResult(
        primitives=primitives_tuple,
        pipeline=pipeline_result,
        artifact_paths=artifact_paths,
        dispatch_plan=dispatch_plan,
        dispatch_execution=dispatch_execution,
        cooldown_audit=cooldown_audit_context,
    )
