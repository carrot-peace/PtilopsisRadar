"""DR notification orchestration behind a narrow application service."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class DRNotificationResult:
    mode: str
    executed: bool
    reason: str
    accepted_count: int = 0
    artifact_paths: Any = None


class DRNotificationService:
    """Resolve, deduplicate, deliver, and audit one DR notification."""

    def __init__(
        self,
        context,
        *,
        environ: Optional[Mapping[str, str]] = None,
        public_html_path: Path = Path("output/public/daily/full.html"),
    ):
        self._context = context
        self._environ = os.environ if environ is None else environ
        self._public_html_path = public_html_path

    def run(
        self,
        *,
        ai_result,
        html_file: str,
        schedule=None,
    ) -> DRNotificationResult:
        from trendradar.dr.dispatch_mode import (
            DR_DISPATCH_ARTIFACT,
            DR_DISPATCH_LIVE,
            DR_DISPATCH_OFF,
            resolve_dr_dispatch_mode,
        )

        dispatch_mode = resolve_dr_dispatch_mode(self._environ)
        if dispatch_mode == DR_DISPATCH_OFF:
            return DRNotificationResult(
                mode=dispatch_mode,
                executed=False,
                reason="dispatch disabled",
            )

        schedule_scheduler = None
        date_str = self._context.format_date()
        once_live_period = bool(
            dispatch_mode == DR_DISPATCH_LIVE
            and schedule is not None
            and getattr(schedule, "once_analyze", False)
            and getattr(schedule, "period_key", None)
        )
        if once_live_period:
            from trendradar.dr.dispatch_schedule import (
                should_run_scheduled_live_dispatch,
            )

            schedule_scheduler = self._context.create_scheduler()
            if not should_run_scheduled_live_dispatch(
                schedule=schedule,
                scheduler=schedule_scheduler,
                date_str=date_str,
                has_analysis_result=ai_result is not None,
            ):
                print("[DR] live dispatch skipped: once-only period already handled")
                return DRNotificationResult(
                    mode=dispatch_mode,
                    executed=False,
                    reason="once-only period already handled",
                )

        from trendradar.dr.artifacts import write_dr_dispatch_artifacts
        from trendradar.dr.dispatch_executor import (
            DRDispatchExecutionResult,
            dr_dispatch_receipts_to_json_dict,
            execute_dr_dispatch_plan,
        )
        from trendradar.dr.dispatch_plan import (
            build_dr_dispatch_plan,
            dr_dispatch_plan_to_json_dict,
        )
        from trendradar.dr.formatter import render_dr_telegram_text

        now = self._context.get_time()
        run_label = f"dr-{now:%Y%m%d-%H%M%S}"
        text = render_dr_telegram_text(ai_result, date=date_str, now=now)
        raw_attach = self._environ.get("PTILOPSIS_DR_TELEGRAM_ATTACH_HTML")
        attach_html = (
            True
            if raw_attach is None
            else raw_attach.strip().lower() not in {"0", "false", "no", "off"}
        )
        plan = build_dr_dispatch_plan(
            text=text,
            html_path=(
                self._public_html_path
                if self._public_html_path.exists()
                else html_file
            ),
            run_label=run_label,
            date=date_str,
            attach_html=attach_html,
        )

        execution: DRDispatchExecutionResult | None = None
        if dispatch_mode == DR_DISPATCH_ARTIFACT:
            print("[DR] dispatch artifact mode: plan/receipt only")
        elif dispatch_mode == DR_DISPATCH_LIVE:
            from trendradar.dr.telegram_env import build_dr_telegram_sink_from_env

            sink = None
            try:
                sink = build_dr_telegram_sink_from_env(self._environ)
            except ValueError as exc:
                print(
                    f"[DR] live Telegram sink not configured: {exc}",
                    file=sys.stderr,
                )
            execution = execute_dr_dispatch_plan(plan, sink=sink)
            print(
                f"[DR] dispatch live result: {execution.reason}, "
                f"accepted={execution.accepted_count}"
            )
            if execution.accepted_count > 0 and schedule_scheduler is not None:
                from trendradar.dr.dispatch_schedule import (
                    record_scheduled_live_dispatch,
                )

                try:
                    record_scheduled_live_dispatch(
                        schedule=schedule,
                        scheduler=schedule_scheduler,
                        date_str=date_str,
                    )
                except Exception as exc:
                    print(
                        f"[DR] failed to record live dispatch dedupe: {exc}",
                        file=sys.stderr,
                    )

        created_at = now.isoformat()
        plan_json = dr_dispatch_plan_to_json_dict(
            plan,
            dispatch_mode=dispatch_mode,
            created_at=created_at,
        )
        receipt_json = dr_dispatch_receipts_to_json_dict(
            plan=plan,
            dispatch_mode=dispatch_mode,
            execution=execution,
            created_at=created_at,
        )
        paths = write_dr_dispatch_artifacts(
            plan_json=plan_json,
            receipt_json=receipt_json,
            run_label=run_label,
        )
        print(f"[DR] dispatch artifacts written: {paths.latest_plan_path}")
        return DRNotificationResult(
            mode=dispatch_mode,
            executed=True,
            reason=(
                execution.reason
                if execution is not None
                else "artifact mode"
            ),
            accepted_count=(
                execution.accepted_count
                if execution is not None
                else 0
            ),
            artifact_paths=paths,
        )
