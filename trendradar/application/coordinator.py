"""Application run coordinator independent of CLI and concrete services."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True, slots=True)
class RunResult:
    status: str
    plan: Any = None
    html_file: Optional[str] = None
    reason: Optional[str] = None


class RunCoordinator:
    """Own one complete run's ordering, state reset, and resource lifecycle."""

    def __init__(self, application):
        self._application = application

    def run(self) -> RunResult:
        application = self._application
        run_retention_maintenance = False
        plan = None
        try:
            if not application._initialize_and_check_config():
                return RunResult(
                    status="skipped",
                    reason="configuration disabled the run",
                )

            plan = application._resolve_run_plan()
            if not plan.collect:
                print("[调度] 当前时间段不执行数据采集，跳过分析流水线")
                return RunResult(
                    status="skipped",
                    plan=plan,
                    reason="collection disabled by schedule",
                )
            run_retention_maintenance = True
            application.run_state = application._new_run_state()

            results, id_to_name, failed_ids = application._crawl_data()
            (
                rss_items,
                rss_new_items,
                raw_rss_items,
                rss_new_urls,
            ) = application._crawl_rss_data(plan)
            html_file = application._execute_mode_strategy(
                plan,
                results,
                id_to_name,
                failed_ids,
                rss_items=rss_items,
                rss_new_items=rss_new_items,
                raw_rss_items=raw_rss_items,
                rss_new_urls=rss_new_urls,
            )
            return RunResult(
                status="completed",
                plan=plan,
                html_file=html_file,
            )
        except Exception as exc:
            print(f"分析流程执行出错: {exc}")
            raise
        finally:
            try:
                if run_retention_maintenance:
                    application.ctx.run_retention_maintenance()
            finally:
                application.ctx.close()
