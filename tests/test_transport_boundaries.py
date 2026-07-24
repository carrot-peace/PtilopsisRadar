"""Current transport allowlist and removed-surface regression guards."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = PROJECT_ROOT / "trendradar"
MAIN_PATH = RUNTIME_ROOT / "__main__.py"
SCHEDULER_PATH = RUNTIME_ROOT / "core" / "scheduler.py"
TIMELINE_PATH = PROJECT_ROOT / "config" / "timeline.yaml"

TELEGRAM_HTTP_ALLOWLIST = {
    "trendradar/telegram/transport.py",
}
FORBIDDEN_RUNTIME_SYMBOLS = {
    "NotificationDispatcher",
    "dispatch_all",
    "send_to_telegram",
    "_send_notification_if_needed",
    "create_notification_dispatcher",
}


def _python_sources() -> list[Path]:
    return sorted(
        path for path in RUNTIME_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_telegram_http_primitives_are_confined_to_explicit_senders() -> None:
    actual: set[str] = set()
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if any(
            token in text
            for token in (
                "api.telegram.org",
                "urllib.request",
                "multipart/form-data",
            )
        ):
            actual.add(path.relative_to(PROJECT_ROOT).as_posix())

    assert actual == TELEGRAM_HTTP_ALLOWLIST


def test_generic_notification_package_and_runtime_symbols_stay_absent() -> None:
    assert not (RUNTIME_ROOT / "notification").exists()

    offenders: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
                if any(name.startswith("trendradar.notification") for name in names):
                    offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("trendradar.notification"):
                    offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in FORBIDDEN_RUNTIME_SYMBOLS:
                    offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
            elif isinstance(node, ast.Name):
                if node.id in FORBIDDEN_RUNTIME_SYMBOLS:
                    offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
            elif isinstance(node, ast.Attribute):
                if node.attr in FORBIDDEN_RUNTIME_SYMBOLS:
                    offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_operational_transport_remains_owner_only() -> None:
    for relpath in (
        "trendradar/deployment/notification.py",
        "trendradar/deployment/operator_alert.py",
    ):
        text = (PROJECT_ROOT / relpath).read_text(encoding="utf-8")
        assert "owner_chat_ids" in text
        assert "receiver_chat_ids" not in text


def test_inbound_telegram_surface_is_narrow_and_explicit() -> None:
    bot_path = RUNTIME_ROOT / "telegram" / "bot.py"
    store_path = RUNTIME_ROOT / "telegram" / "subscriptions.py"
    assert bot_path.is_file()
    assert store_path.is_file()
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8") for path in _python_sources()
    )
    for command in (
        '"/start"',
        '"/help"',
        '"/token"',
        '"/subscribe"',
        '"/unsubscribe"',
    ):
        assert command in bot_path.read_text(encoding="utf-8")
    for removed_config in (
        "TELEGRAM_RECEIVER_CHAT_IDS",
        "TELEGRAM_COMMAND_CHAT_IDS",
        "TELEGRAM_COMMANDS_ENABLED",
        "TELEGRAM_UNAUTHORIZED_BEHAVIOR",
    ):
        assert removed_config not in runtime_text


def test_repository_config_has_no_generic_transport_sections() -> None:
    text = (PROJECT_ROOT / "config" / "config.yaml").read_text(encoding="utf-8")
    for top_level_key in ("notification:", "alert:", "telegram_attachments:"):
        assert f"\n{top_level_key}" not in text


def test_runtime_entrypoint_has_no_generic_delivery_controls() -> None:
    source = MAIN_PATH.read_text(encoding="utf-8")
    for token in (
        "--test-notification",
        "_run_test_notification",
        "LEGACY_PUSH_REMOVED_MSG",
        "should_send_notification",
    ):
        assert token not in source


def test_scheduler_and_timeline_have_no_delivery_controls() -> None:
    tree = ast.parse(SCHEDULER_PATH.read_text(encoding="utf-8"))
    schedule_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ResolvedSchedule"
    )
    fields = {
        node.target.id
        for node in schedule_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert fields.isdisjoint({"push", "once_push"})

    timeline_lines = TIMELINE_PATH.read_text(encoding="utf-8").splitlines()
    assert not any(line.strip().startswith("push:") for line in timeline_lines)


def test_storage_schema_has_no_delivery_execution_state() -> None:
    rss_schema = (RUNTIME_ROOT / "storage" / "rss_schema.sql").read_text(
        encoding="utf-8"
    )
    assert "rss_push_records" not in rss_schema
    assert "push_window" not in rss_schema

    execution_sources = "\n".join(
        (RUNTIME_ROOT / relpath).read_text(encoding="utf-8")
        for relpath in (
            "storage/base.py",
            "storage/sqlite_mixin.py",
            "storage/schema.sql",
        )
    )
    assert "analyze / push" not in execution_sources
    assert "analyze | push" not in execution_sources


def test_transport_boundary_document_exists() -> None:
    text = (PROJECT_ROOT / "docs" / "transport_boundaries.md").read_text(
        encoding="utf-8"
    )
    for term in ("CR dispatch", "DR dispatch", "Deployment and operator alerts"):
        assert term in text
