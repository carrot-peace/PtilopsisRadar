"""CR notification hook extracted from the CLI analysis pipeline."""

import logging
import os
import sys
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True, slots=True)
class CRNotificationRequest:
    mode: str
    hotlist_stats: Sequence[Mapping[str, Any]]
    rss_stats: Optional[list[dict]]
    raw_rss_items: Optional[list[dict]]
    hotlist_configured_ids: frozenset[str]
    hotlist_successful_ids: frozenset[str]
    hotlist_failed_ids: frozenset[str]
    rss_configured_ids: frozenset[str]
    rss_successful_ids: frozenset[str]
    rss_failed_ids: frozenset[str]
    observed_item_identities: frozenset[str]
    snapshot_generated_at: Optional[str]
    historical_data_reused: bool


@dataclass(frozen=True, slots=True)
class CRNotificationResult:
    mode: str
    executed: bool
    runtime_result: Any = None


class CRNotificationService:
    """Run CR admission, health evaluation, dispatch, and audit hooks."""

    def __init__(
        self,
        context,
        *,
        environ: Optional[Mapping[str, str]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._context = context
        self._environ = os.environ if environ is None else environ
        self._logger = logger or logging.getLogger(__name__)

    def run(self, request: CRNotificationRequest) -> CRNotificationResult:
        from trendradar.cr.dispatch_mode import (
            CR_DISPATCH_LIVE,
            CR_DISPATCH_OFF,
            resolve_cr_dispatch_mode,
        )

        _cr_mode = resolve_cr_dispatch_mode(self._environ)
        if _cr_mode != CR_DISPATCH_OFF:
            from trendradar.cr.input_health import (
                RECOVERY_STATE_BASELINE,
                RECOVERY_STATE_TRACKED,
                RECOVERY_STATE_UNTRUSTED,
                evaluate_cr_input_health,
                policy_from_env,
            )
            from trendradar.cr.input_health_state import (
                CRInputHealthState,
                DEFAULT_CR_INPUT_HEALTH_STATE_PATH,
                load_cr_input_health_state,
                quarantine_invalid_cr_input_health_state,
                recovered_source_ids,
                save_cr_input_health_state,
            )
            from trendradar.cr.models import CRClusterConfig, CRRunContext
            from trendradar.cr.pipeline import CRPipelineConfig
            from trendradar.cr.runtime_dry_run import (
                build_and_write_cr_runtime_dry_run,
            )
            from trendradar.cr.scoring import (
                CRScoringProfile,
                TIERED_CR_SCORING_PROFILE_VERSION,
            )

            _dispatch_sink = None
            if _cr_mode == CR_DISPATCH_LIVE:
                from trendradar.cr.telegram_env import (
                    build_cr_telegram_sink_from_env,
                )

                try:
                    _dispatch_sink = build_cr_telegram_sink_from_env(
                        self._environ
                    )
                except ValueError as exc:
                    print(
                        f"[CR-A] live Telegram sink not configured: {exc}",
                        file=sys.stderr,
                    )

            _cr_rss_stats = request.rss_stats
            _pipeline_cluster_cfg = CRClusterConfig()
            _pipeline_scoring_cfg = CRScoringProfile(
                profile_version=TIERED_CR_SCORING_PROFILE_VERSION,
                source_tier_resolver=self._context.source_tier_resolver,
            )
            try:
                from trendradar.cr.cross_evidence_ingest import (
                    build_cross_evidence_cluster_config_from_env,
                    merge_rss_stats,
                    select_cross_evidence_rss,
                )
                from trendradar.cr.entity_match import load_entity_resources

                _ce_cfg = build_cross_evidence_cluster_config_from_env(
                    self._environ
                )
                _pipeline_cluster_cfg = replace(
                    _ce_cfg,
                    drop_unmerged_rss=False,
                )
                if (
                    _ce_cfg.cross_evidence_rss_enabled
                    and request.raw_rss_items
                ):
                    _hotlist_titles = [
                        title.get("title", "")
                        for group in (request.hotlist_stats or [])
                        for title in group.get("titles", [])
                    ]
                    _admitted_rss_stats = select_cross_evidence_rss(
                        request.raw_rss_items,
                        _hotlist_titles,
                        resources=load_entity_resources(),
                        now=self._context.get_time(),
                        window_hours=_ce_cfg.cross_evidence_window_hours,
                        max_per_topic=_ce_cfg.cross_evidence_max_per_topic,
                    )
                    _cr_rss_stats = merge_rss_stats(
                        request.rss_stats,
                        _admitted_rss_stats,
                    )
                    _pipeline_cluster_cfg = _ce_cfg
                    _admitted = sum(
                        len(group.get("titles", []))
                        for group in _admitted_rss_stats
                    )
                    self._logger.info(
                        "[CR-A] 跨证据 RSS 准入: %d 条(来自 %d 条原始 RSS)",
                        _admitted,
                        len(request.raw_rss_items),
                    )
            except Exception as exc:
                self._logger.warning(
                    "[CR-A] 跨证据 RSS 准入失败,回退关键词 RSS: %s",
                    exc,
                )
                _cr_rss_stats = request.rss_stats

            _run_label = (
                f"{request.mode}-"
                f"{self._context.get_time():%Y%m%d-%H%M%S}"
            )
            _health_policy, _health_warnings = policy_from_env(
                self._environ
            )
            _health_state_path = self._environ.get(
                "PTILOPSIS_CR_INPUT_HEALTH_STATE_PATH",
                str(DEFAULT_CR_INPUT_HEALTH_STATE_PATH),
            ) or str(DEFAULT_CR_INPUT_HEALTH_STATE_PATH)
            _health_state_load = load_cr_input_health_state(
                _health_state_path
            )
            _hotlist_recovered_ids: tuple[str, ...] = ()
            _rss_recovered_ids: tuple[str, ...] = ()
            _recovery_state_status = RECOVERY_STATE_BASELINE
            _state_can_be_saved = True
            if (
                _health_state_load.loaded
                and _health_state_load.state is not None
            ):
                _recovery_state_status = RECOVERY_STATE_TRACKED
                _hotlist_recovered_ids = recovered_source_ids(
                    _health_state_load.state.hotlist_failed_ids,
                    request.hotlist_successful_ids,
                )
                _rss_recovered_ids = recovered_source_ids(
                    _health_state_load.state.rss_failed_ids,
                    request.rss_successful_ids,
                )
            elif _health_state_load.error is not None:
                _recovery_state_status = RECOVERY_STATE_UNTRUSTED
                _health_warnings += (_health_state_load.error,)
                _state_can_be_saved = (
                    quarantine_invalid_cr_input_health_state(
                        _health_state_path,
                        suffix=self._context.get_time().strftime(
                            "%Y%m%dT%H%M%S"
                        ),
                    )
                )
                if not _state_can_be_saved:
                    _health_warnings += (
                        "unable to quarantine invalid input health state",
                    )

            if _state_can_be_saved:
                _health_state_save = save_cr_input_health_state(
                    CRInputHealthState(
                        recorded_at=self._context.get_time().isoformat(),
                        hotlist_successful_ids=tuple(
                            request.hotlist_successful_ids
                        ),
                        hotlist_failed_ids=tuple(
                            request.hotlist_failed_ids
                        ),
                        rss_successful_ids=tuple(
                            request.rss_successful_ids
                        ),
                        rss_failed_ids=tuple(request.rss_failed_ids),
                    ),
                    _health_state_path,
                )
                if not _health_state_save.saved:
                    _recovery_state_status = RECOVERY_STATE_UNTRUSTED
                    _health_warnings += (
                        _health_state_save.error
                        or "unable to save input health state",
                    )

            _input_health = evaluate_cr_input_health(
                hotlist_configured_ids=request.hotlist_configured_ids,
                hotlist_successful_ids=request.hotlist_successful_ids,
                hotlist_failed_ids=request.hotlist_failed_ids,
                rss_configured_ids=request.rss_configured_ids,
                rss_successful_ids=request.rss_successful_ids,
                rss_failed_ids=request.rss_failed_ids,
                hotlist_recovered_ids=_hotlist_recovered_ids,
                rss_recovered_ids=_rss_recovered_ids,
                observed_item_identities=request.observed_item_identities,
                snapshot_generated_at=request.snapshot_generated_at,
                now=self._context.get_time(),
                historical_data_reused=request.historical_data_reused,
                recovery_state_status=_recovery_state_status,
                policy=_health_policy,
                warnings=_health_warnings,
            )
            for _warning in _input_health.warnings:
                print(
                    f"[CR-A] input health warning: {_warning}",
                    file=sys.stderr,
                )
            _runtime_result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=request.hotlist_stats,
                rss_stats=_cr_rss_stats,
                run_label=_run_label,
                run_context=CRRunContext(
                    mode=request.mode,
                    observed_item_identities=(
                        request.observed_item_identities
                    ),
                    input_health=_input_health,
                ),
                pipeline_config=CRPipelineConfig(
                    cluster=_pipeline_cluster_cfg,
                    scoring=_pipeline_scoring_cfg,
                ),
                dispatch_sink=_dispatch_sink,
                dispatch_mode=_cr_mode,
                quiet_hours_env=self._environ,
            )

            from trendradar.cr.deploy_trace_writer import write_deploy_trace

            try:
                write_deploy_trace(run_label=_run_label)
            except Exception:
                pass

            if self._environ.get("PTILOPSIS_CR_LIFECYCLE_ENABLED") == "1":
                try:
                    from trendradar.cr.lifecycle_runner import main as lifecycle_main

                    lifecycle_main(["--now", self._context.get_time().isoformat()])
                except Exception as exc:
                    print(
                        f"[lifecycle] janitor error: {exc}",
                        file=sys.stderr,
                    )

            return CRNotificationResult(
                mode=_cr_mode,
                executed=True,
                runtime_result=_runtime_result,
            )

        return CRNotificationResult(
            mode=_cr_mode,
            executed=False,
        )
