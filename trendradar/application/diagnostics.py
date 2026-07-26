"""Environment diagnostics and read-only schedule presentation."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from trendradar import __version__
from trendradar.context import AppContext
from trendradar.core import load_config


DOCTOR_STATUS_LABELS = {
    "pass": "[通过]",
    "warn": "[警告]",
    "fail": "[失败]",
}


def _format_switch_state(enabled: bool) -> str:
    """Return a neutral label for a configured boolean switch."""
    return "[开启]" if enabled else "[关闭]"


def _record_doctor_result(results: List[Tuple[str, str, str]], status: str, item: str, detail: str) -> None:
    """记录并打印 doctor 检查结果"""
    label = DOCTOR_STATUS_LABELS.get(status, "[未知]")
    results.append((status, item, detail))
    print(f"{label} {item}: {detail}")


def _save_doctor_report(
    results: List[Tuple[str, str, str]],
    pass_count: int,
    warn_count: int,
    fail_count: int,
    config_path: Optional[str],
) -> None:
    """保存 doctor 体检报告到 JSON 文件"""
    report = {
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_path": config_path or os.environ.get("CONFIG_PATH", "config/config.yaml"),
        "summary": {
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "ok": fail_count == 0,
        },
        "checks": [
            {"status": status, "item": item, "detail": detail}
            for status, item, detail in results
        ],
    }

    try:
        output_dir = Path("output") / "meta"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "doctor_report.json"
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"体检报告已保存: {output_path}")
    except Exception as e:
        print(f"[警告] 体检报告保存失败: {e}")


def run_doctor(config_path: Optional[str] = None) -> bool:
    """运行环境体检"""
    print("=" * 60)
    print(f"Ptilopsis Radar v{__version__} 环境体检")
    print("=" * 60)

    results: List[Tuple[str, str, str]] = []
    config = None

    # 1) Python 版本检查
    py_ok = sys.version_info >= (3, 10)
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if py_ok:
        _record_doctor_result(results, "pass", "Python版本", f"{py_version} (满足 >= 3.10)")
    else:
        _record_doctor_result(results, "fail", "Python版本", f"{py_version} (不满足 >= 3.10)")

    # 2) 关键文件检查
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config/config.yaml")

    required_files = [
        (config_path, "主配置文件"),
        ("config/frequency_words.txt", "关键词文件"),
    ]
    optional_files = [
        ("config/timeline.yaml", "调度文件"),
    ]

    for path_str, desc in required_files:
        if Path(path_str).exists():
            _record_doctor_result(results, "pass", desc, f"已找到: {path_str}")
        else:
            _record_doctor_result(results, "fail", desc, f"缺失: {path_str}")

    for path_str, desc in optional_files:
        if Path(path_str).exists():
            _record_doctor_result(results, "pass", desc, f"已找到: {path_str}")
        else:
            _record_doctor_result(results, "warn", desc, f"未找到: {path_str}（将使用默认调度模板）")

    # 3) 配置加载检查
    try:
        config = load_config(config_path)
        _record_doctor_result(results, "pass", "配置加载", f"加载成功: {config_path}")
    except Exception as e:
        _record_doctor_result(results, "fail", "配置加载", f"加载失败: {e}")

    # 后续检查依赖配置对象
    if config:
        # 4) 调度配置检查
        schedule_ctx = None
        try:
            schedule_ctx = AppContext(config)
            schedule = schedule_ctx.create_scheduler().resolve()
            detail = f"调度解析成功（report_mode={schedule.report_mode}, ai_mode={schedule.ai_mode}）"
            _record_doctor_result(results, "pass", "调度配置", detail)
        except Exception as e:
            _record_doctor_result(results, "fail", "调度配置", f"解析失败: {e}")
        finally:
            if schedule_ctx is not None:
                schedule_ctx.close()

        # 5) AI 配置检查（按功能场景区分严重级别）
        ai_analysis_enabled = config.get("AI_ANALYSIS", {}).get("ENABLED", False)
        ai_translation_enabled = config.get("AI_TRANSLATION", {}).get("ENABLED", False)
        ai_filter_enabled = config.get("FILTER", {}).get("METHOD", "keyword") == "ai"
        ai_enabled = ai_analysis_enabled or ai_translation_enabled or ai_filter_enabled

        if ai_enabled:
            try:
                from trendradar.ai.client import AIClient
                valid, message = AIClient(config.get("AI", {})).validate_config()
                if valid:
                    _record_doctor_result(results, "pass", "AI配置", f"模型: {config.get('AI', {}).get('MODEL', '')}")
                else:
                    # AI 分析/翻译是硬依赖；AI 筛选缺失时会自动回退关键词匹配
                    if ai_analysis_enabled or ai_translation_enabled:
                        _record_doctor_result(results, "fail", "AI配置", message)
                    else:
                        _record_doctor_result(results, "warn", "AI配置", f"{message}（AI 筛选将回退关键词模式）")
            except Exception as e:
                _record_doctor_result(results, "fail", "AI配置", f"校验异常: {e}")
        else:
            _record_doctor_result(results, "warn", "AI配置", "未启用 AI 功能，跳过校验")

        # 6) 存储配置检查
        storage_ctx = None
        try:
            storage_cfg = config.get("STORAGE", {})
            backend = storage_cfg.get("BACKEND", "auto")
            remote = storage_cfg.get("REMOTE", {})
            missing_remote_keys = [
                k for k in ("BUCKET_NAME", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY", "ENDPOINT_URL")
                if not remote.get(k)
            ]

            if backend == "remote" and missing_remote_keys:
                _record_doctor_result(
                    results, "fail", "存储配置",
                    f"remote 模式缺少配置: {', '.join(missing_remote_keys)}"
                )
            elif backend == "auto" and os.environ.get("GITHUB_ACTIONS") == "true" and missing_remote_keys:
                _record_doctor_result(
                    results, "warn", "存储配置",
                    "GitHub Actions + auto 模式未完整配置远程存储，可能导致数据丢失"
                )
            else:
                storage_ctx = AppContext(config)
                sm = storage_ctx.get_storage_manager()
                _record_doctor_result(results, "pass", "存储配置", f"当前后端: {sm.backend_name}")
        except Exception as e:
            _record_doctor_result(results, "fail", "存储配置", f"检查失败: {e}")
        finally:
            if storage_ctx is not None:
                storage_ctx.close()

        # 7) 输出目录可写检查
        try:
            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)
            probe_file = output_dir / ".doctor_write_probe"
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink(missing_ok=True)
            _record_doctor_result(results, "pass", "输出目录", f"可写: {output_dir}")
        except Exception as e:
            _record_doctor_result(results, "fail", "输出目录", f"不可写: {e}")

    pass_count = sum(1 for status, _, _ in results if status == "pass")
    warn_count = sum(1 for status, _, _ in results if status == "warn")
    fail_count = sum(1 for status, _, _ in results if status == "fail")

    _save_doctor_report(results, pass_count, warn_count, fail_count, config_path)

    print("-" * 60)
    print(
        "体检结果: "
        f"{DOCTOR_STATUS_LABELS['pass']} {pass_count} 项通过  "
        f"{DOCTOR_STATUS_LABELS['warn']} {warn_count} 项警告  "
        f"{DOCTOR_STATUS_LABELS['fail']} {fail_count} 项失败"
    )
    print("=" * 60)

    if fail_count == 0:
        print("体检通过。")
        return True

    print("体检未通过，请先修复失败项。")
    return False


def show_schedule(config: Dict) -> None:
    """处理状态查看命令 - 显示当前调度状态"""
    ctx = AppContext(config)

    print("=" * 60)
    print(f"Ptilopsis Radar v{__version__} 调度状态")
    print("=" * 60)

    try:
        scheduler = ctx.create_scheduler()
        schedule = scheduler.resolve()

        now = ctx.get_time()
        date_str = ctx.format_date()

        print(f"\n 当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} ({ctx.timezone})")
        print(f" 当前日期: {date_str}")

        print(f"\n 调度信息:")
        print(f"  日计划: {schedule.day_plan}")
        if schedule.period_key:
            print(f"  当前时间段: {schedule.period_name or schedule.period_key} ({schedule.period_key})")
        else:
            print(f"  当前时间段: 无（使用默认配置）")

        print(f"\n 行为开关:")
        print(f"  采集数据: {_format_switch_state(schedule.collect)}")
        print(f"  AI 分析:  {_format_switch_state(schedule.analyze)}")
        print(f"  报告模式: {schedule.report_mode}")
        print(f"  AI 模式:  {schedule.ai_mode}")

        if schedule.period_key:
            print("\n一次性控制:")
            if schedule.once_analyze:
                already_analyzed = scheduler.already_executed(schedule.period_key, "analyze", date_str)
                once_state = "[已执行]" if already_analyzed else "[待执行]"
                print(f"  AI 分析:  仅一次 {once_state}")
            else:
                print(f"  AI 分析:  不限次数")

    except Exception as e:
        print(f"\n[失败] 获取调度状态失败: {e}")

    print("\n" + "=" * 60)

    # 状态查看是只读操作，只关闭连接，不运行 retention 删除。
    ctx.close()

