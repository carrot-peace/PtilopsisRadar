"""Command-line application shell with injected runtime dependencies."""

import argparse
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence


@dataclass(frozen=True, slots=True)
class CLIApplication:
    load_config: Callable
    analyzer_factory: Callable
    check_versions: Callable
    run_doctor: Callable
    show_schedule: Callable
    version: str

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Ptilopsis Radar - 热点新闻聚合与分析工具",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
调度状态命令:
  --show-schedule        显示当前调度状态（时间段、行为开关）
诊断命令:
  --doctor               运行环境与配置体检

示例:
  python -m trendradar                    # 正常运行
  python -m trendradar --show-schedule    # 查看当前调度状态
  python -m trendradar --doctor           # 运行一键体检
""",
        )
        parser.add_argument(
            "--show-schedule",
            action="store_true",
            help="显示当前调度状态",
        )
        parser.add_argument(
            "--doctor",
            action="store_true",
            help="运行环境与配置体检",
        )
        return parser

    def run(self, argv: Optional[Sequence[str]] = None) -> int:
        args = self._parser().parse_args(argv)
        debug_mode = False
        try:
            if args.doctor:
                return 0 if self.run_doctor() else 1

            config = self.load_config()
            if args.show_schedule:
                self.show_schedule(config)
                return 0

            version_url = config.get("VERSION_CHECK_URL", "")
            configs_version_url = config.get(
                "CONFIGS_VERSION_CHECK_URL",
                "",
            )
            need_update = False
            remote_version = None
            if version_url:
                need_update, remote_version = self.check_versions(
                    version_url,
                    configs_version_url,
                )

            analyzer = self.analyzer_factory(config=config)
            if (
                analyzer.is_github_actions
                and need_update
                and remote_version
            ):
                analyzer.update_info = {
                    "current_version": self.version,
                    "remote_version": remote_version,
                }

            debug_mode = analyzer.ctx.config.get("DEBUG", False)
            analyzer.run()
            return 0
        except FileNotFoundError as exc:
            print(f"[失败] 配置文件错误: {exc}")
            print("\n请确保以下文件存在:")
            print("  • config/config.yaml")
            print("  • config/frequency_words.txt")
            print("\n参考项目文档进行正确配置")
            return 1
        except Exception as exc:
            print(f"[失败] 程序运行错误: {exc}")
            if debug_mode:
                raise
            return 1
