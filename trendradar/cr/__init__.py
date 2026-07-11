# coding=utf-8
"""
CR (Current Report) primitive layer.

PR9b: primitive models + input adapter.
PR9c: topic clustering / true CRCandidate.
PR9d: scoring.
PR9e: decision policy.
PR9f: presentation layer.
PR9g: Markdown audit renderer.
PR9h: artifact path resolver / writer.
PR9i: canonical HTML audit renderer.
PR10c: CR-A event state snapshot boundary.
PR10d: CR-A cooldown policy decision layer.
PR10e: CR-A cooldown audit assembly.
PR10i: CR-A state transition preview.
"""

from trendradar.cr.models import (
    CRSourceItem,
    CRPrimitiveRecord,
    CRRunContext,
    CRCandidate,
    CRClusterConfig,
    RANK_SENTINELS,
    is_visible_rank,
)
from trendradar.cr.adapter import (
    adapt_hotlist_stats,
    adapt_rss_stats,
)
from trendradar.cr.cluster import (
    build_cr_candidates,
)
from trendradar.cr.scoring import (
    CRScoringProfile,
    CRComponentScore,
    CRScoreResult,
    DEFAULT_CR_SCORING_PROFILE,
    clamp_score,
    make_component_score,
    score_growth_raw,
    score_current_heat_raw,
    score_cross_layer_raw,
    combine_cr_scores,
    score_cr_candidate,
)
from trendradar.cr.decision import (
    CRDecisionPolicy,
    CRDecision,
    CRDecisionLevel,
    DEFAULT_CR_DECISION_POLICY,
    apply_cr_decision,
    decide_cr_candidates,
    count_high_score_suppressed,
)
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    CRPresentationRun,
    CRTextPresentationConfig,
    bind_cr_presented_candidates,
    sort_cr_presented_candidates,
    select_cr_a_candidates,
    render_cr_a_text,
    render_cr_a_text_from_parts,
)
from trendradar.cr.event_identity import (
    CR_EVENT_IDENTITY_KEY_VERSION,
    CREventIdentityInput,
    CREventIdentity,
    normalize_cr_event_title,
    normalize_cr_event_url,
    build_cr_event_identity_from_input,
    build_cr_event_identity_from_candidate,
)
from trendradar.cr.repeat_preview import (
    CRRepeatPreviewStatus,
    CRDecisionLevelComparison,
    CRSeenEventState,
    CRRepeatPreview,
    normalize_cr_decision_level,
    compare_cr_decision_level,
    preview_cr_repeat,
    preview_cr_repeats,
)
from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
    empty_cr_event_state_snapshot,
    cr_event_state_snapshot_to_seen_states,
    cr_event_state_snapshot_to_json_dict,
    cr_event_state_snapshot_from_json_dict,
    merge_cr_event_state_entries,
    build_cr_event_state_entry_from_presented_candidate,
    build_cr_event_state_entries_from_presented_candidates,
)
from trendradar.cr.state_store import (
    CREventStateLoadResult,
    CREventStateSaveResult,
    load_cr_event_state_snapshot,
    save_cr_event_state_snapshot,
)
from trendradar.cr.cooldown_policy import (
    CRCooldownAction,
    CRCooldownPolicy,
    CRCooldownDecision,
    DEFAULT_CR_COOLDOWN_POLICY,
    decide_cr_cooldown,
    decide_cr_cooldowns,
)
from trendradar.cr.cooldown_audit import (
    CRCooldownAuditCandidate,
    CRCooldownAuditContext,
    build_cr_cooldown_audit_context,
)
from trendradar.cr.state_transition_preview import (
    CREventStateTransitionPreview,
    build_cr_event_state_transition_preview,
)
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.html import (
    CRHTMLRenderConfig,
    render_cr_html_audit,
)
from trendradar.cr.artifacts import (
    CRArtifactConfig,
    CRArtifactPaths,
    sanitize_artifact_label,
    resolve_cr_artifact_paths,
    write_text_artifact,
    write_cr_artifact_bundle,
    write_cr_markdown_audit_artifact,
    write_cr_html_artifact,
    render_and_write_cr_artifacts,
)
from trendradar.cr.pipeline import (
    CRPipelineRenderConfig,
    CRPipelineConfig,
    CRPipelineResult,
    CRPipelineArtifactResult,
    build_cr_pipeline_from_primitives,
    write_cr_pipeline_artifacts,
    build_and_write_cr_pipeline_from_primitives,
)
from trendradar.cr.dispatch_plan import (
    CRDispatchMessage,
    CRDispatchPlan,
    build_cr_a_dispatch_plan,
)
from trendradar.cr.dispatch_executor import (
    CRDispatchReceipt,
    CRDispatchExecutionResult,
    CRDispatchSink,
    CRMemoryDispatchSink,
    CRNoopDispatchSink,
    execute_cr_dispatch_plan,
)
from trendradar.cr.telegram_sink import (
    CRTelegramSinkConfig,
    CRTelegramHTTPResponse,
    CRTelegramHTTPClient,
    CRUrllibTelegramHTTPClient,
    CRTelegramSink,
)
from trendradar.cr.telegram_env import (
    cr_telegram_send_enabled,
    build_cr_telegram_sink_config_from_env,
    build_cr_telegram_sink_from_env,
)
from trendradar.cr.dispatch_mode import (
    CRDispatchMode,
    CR_DISPATCH_OFF,
    CR_DISPATCH_ARTIFACT,
    CR_DISPATCH_SHADOW,
    CR_DISPATCH_LIVE,
    resolve_cr_dispatch_mode,
)
from trendradar.cr.quiet_hours import (
    CRQuietHoursEvaluation,
    evaluate_cr_quiet_hours,
    quiet_hours_evaluation_to_plan_dict,
)
from trendradar.cr.deferred_queue import (
    DEFERRED_QUEUE_SCHEMA_VERSION,
    DEFAULT_DEFERRED_QUEUE_PATH,
    CRDeferredDispatchEntry,
    CRDeferredDispatchQueue,
    CRDeferredQueueLoadResult,
    CRDeferredQueueSaveResult,
    CRDeferredQueueUpsertResult,
    empty_deferred_dispatch_queue,
    stable_deferred_entry_id,
    load_deferred_dispatch_queue,
    save_deferred_dispatch_queue,
    upsert_deferred_entry,
    remove_deferred_entries,
    ordered_entries_for_flush,
)
from trendradar.cr.runtime_dry_run import (
    CRRuntimeDryRunResult,
    build_and_write_cr_runtime_dry_run,
)

__all__ = [
    "CRSourceItem",
    "CRPrimitiveRecord",
    "CRRunContext",
    "CRCandidate",
    "CRClusterConfig",
    "RANK_SENTINELS",
    "is_visible_rank",
    "adapt_hotlist_stats",
    "adapt_rss_stats",
    "build_cr_candidates",
    "CRScoringProfile",
    "CRComponentScore",
    "CRScoreResult",
    "DEFAULT_CR_SCORING_PROFILE",
    "clamp_score",
    "make_component_score",
    "score_growth_raw",
    "score_current_heat_raw",
    "score_cross_layer_raw",
    "combine_cr_scores",
    "score_cr_candidate",
    "CRDecisionPolicy",
    "CRDecision",
    "CRDecisionLevel",
    "DEFAULT_CR_DECISION_POLICY",
    "apply_cr_decision",
    "decide_cr_candidates",
    "count_high_score_suppressed",
    "CR_EVENT_IDENTITY_KEY_VERSION",
    "CREventIdentityInput",
    "CREventIdentity",
    "normalize_cr_event_title",
    "normalize_cr_event_url",
    "build_cr_event_identity_from_input",
    "build_cr_event_identity_from_candidate",
    "CRRepeatPreviewStatus",
    "CRDecisionLevelComparison",
    "CRSeenEventState",
    "CRRepeatPreview",
    "normalize_cr_decision_level",
    "compare_cr_decision_level",
    "preview_cr_repeat",
    "preview_cr_repeats",
    "CR_EVENT_STATE_SCHEMA_VERSION",
    "CREventStateEntry",
    "CREventStateSnapshot",
    "empty_cr_event_state_snapshot",
    "cr_event_state_snapshot_to_seen_states",
    "cr_event_state_snapshot_to_json_dict",
    "cr_event_state_snapshot_from_json_dict",
    "merge_cr_event_state_entries",
    "build_cr_event_state_entry_from_presented_candidate",
    "build_cr_event_state_entries_from_presented_candidates",
    "CREventStateLoadResult",
    "CREventStateSaveResult",
    "load_cr_event_state_snapshot",
    "save_cr_event_state_snapshot",
    "CRCooldownAction",
    "CRCooldownPolicy",
    "CRCooldownDecision",
    "DEFAULT_CR_COOLDOWN_POLICY",
    "decide_cr_cooldown",
    "decide_cr_cooldowns",
    "CRCooldownAuditCandidate",
    "CRCooldownAuditContext",
    "build_cr_cooldown_audit_context",
    "CREventStateTransitionPreview",
    "build_cr_event_state_transition_preview",
    "CRPresentedCandidate",
    "CRPresentationRun",
    "CRTextPresentationConfig",
    "bind_cr_presented_candidates",
    "sort_cr_presented_candidates",
    "select_cr_a_candidates",
    "render_cr_a_text",
    "render_cr_a_text_from_parts",
    "CRMarkdownRenderConfig",
    "render_cr_markdown_audit",
    "CRHTMLRenderConfig",
    "render_cr_html_audit",
    "CRArtifactConfig",
    "CRArtifactPaths",
    "sanitize_artifact_label",
    "resolve_cr_artifact_paths",
    "write_text_artifact",
    "write_cr_artifact_bundle",
    "write_cr_markdown_audit_artifact",
    "write_cr_html_artifact",
    "render_and_write_cr_artifacts",
    "CRPipelineRenderConfig",
    "CRPipelineConfig",
    "CRPipelineResult",
    "CRPipelineArtifactResult",
    "build_cr_pipeline_from_primitives",
    "write_cr_pipeline_artifacts",
    "build_and_write_cr_pipeline_from_primitives",
    "CRDispatchMessage",
    "CRDispatchPlan",
    "build_cr_a_dispatch_plan",
    "CRDispatchReceipt",
    "CRDispatchExecutionResult",
    "CRDispatchSink",
    "CRMemoryDispatchSink",
    "CRNoopDispatchSink",
    "execute_cr_dispatch_plan",
    "CRTelegramSinkConfig",
    "CRTelegramHTTPResponse",
    "CRTelegramHTTPClient",
    "CRUrllibTelegramHTTPClient",
    "CRTelegramSink",
    "cr_telegram_send_enabled",
    "build_cr_telegram_sink_config_from_env",
    "build_cr_telegram_sink_from_env",
    "CRDispatchMode",
    "CR_DISPATCH_OFF",
    "CR_DISPATCH_ARTIFACT",
    "CR_DISPATCH_SHADOW",
    "CR_DISPATCH_LIVE",
    "resolve_cr_dispatch_mode",
    "CRQuietHoursEvaluation",
    "evaluate_cr_quiet_hours",
    "quiet_hours_evaluation_to_plan_dict",
    "DEFERRED_QUEUE_SCHEMA_VERSION",
    "DEFAULT_DEFERRED_QUEUE_PATH",
    "CRDeferredDispatchEntry",
    "CRDeferredDispatchQueue",
    "CRDeferredQueueLoadResult",
    "CRDeferredQueueSaveResult",
    "CRDeferredQueueUpsertResult",
    "empty_deferred_dispatch_queue",
    "stable_deferred_entry_id",
    "load_deferred_dispatch_queue",
    "save_deferred_dispatch_queue",
    "upsert_deferred_entry",
    "remove_deferred_entries",
    "ordered_entries_for_flush",
    "CRRuntimeDryRunResult",
    "build_and_write_cr_runtime_dry_run",
]
