"""Current transport allowlist and removed-surface regression guards."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = PROJECT_ROOT / "trendradar"
MAIN_PATH = RUNTIME_ROOT / "__main__.py"
SCHEDULER_PATH = RUNTIME_ROOT / "core" / "scheduler.py"
TIMELINE_PATH = PROJECT_ROOT / "config" / "timeline.yaml"

TELEGRAM_HTTP_ALLOWLIST = {
    "trendradar/telegram/transport.py",
}
TELEGRAM_TRANSPORT_IMPORT_ALLOWLIST = {
    "trendradar/cr/telegram_sink.py",
    "trendradar/deployment/operator_alert.py",
    "trendradar/dr/telegram_sink.py",
    "trendradar/telegram/__init__.py",
}
FORBIDDEN_RUNTIME_SYMBOLS = {
    "NotificationDispatcher",
    "dispatch_all",
    "send_to_telegram",
    "_send_notification_if_needed",
    "create_notification_dispatcher",
}
EXECUTABLE_TELEGRAM_TRANSPORT_SYMBOLS = {
    "TelegramTransport",
    "UrllibTelegramHTTPClient",
    "*",
}


def _python_sources() -> list[Path]:
    return sorted(
        path for path in RUNTIME_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_telegram_http_primitives_are_confined_to_explicit_senders() -> None:
    actual: set[str] = set()
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in ("api.telegram.org", "sendMessage", "sendDocument")):
            actual.add(path.relative_to(PROJECT_ROOT).as_posix())

    assert actual == TELEGRAM_HTTP_ALLOWLIST


def _resolve_import_module(
    node: ast.ImportFrom,
    *,
    source_path: Path | None,
) -> str:
    if node.level == 0:
        return node.module or ""
    if source_path is None:
        return node.module or ""

    relative = source_path.relative_to(PROJECT_ROOT).with_suffix("")
    package_parts = list(relative.parts[:-1])
    parent_hops = node.level - 1
    if parent_hops > len(package_parts):
        return node.module or ""
    resolved = package_parts[: len(package_parts) - parent_hops]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _imports_shared_telegram_transport(
    tree: ast.AST,
    *,
    source_path: Path | None = None,
) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name
                in {"trendradar.telegram", "trendradar.telegram.transport"}
                for alias in node.names
            ):
                return True
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module = _resolve_import_module(node, source_path=source_path)
        imported_names = {alias.name for alias in node.names}
        if (
            module == "trendradar.telegram.transport"
            and imported_names & EXECUTABLE_TELEGRAM_TRANSPORT_SYMBOLS
        ):
            return True
        if (
            module == "trendradar.telegram"
            and imported_names
            & (EXECUTABLE_TELEGRAM_TRANSPORT_SYMBOLS | {"transport"})
        ):
            return True
        if module == "trendradar" and imported_names & {"telegram", "*"}:
            return True
    return False


def test_shared_telegram_transport_imports_are_confined_to_adapters() -> None:
    actual: set[str] = set()
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _imports_shared_telegram_transport(tree, source_path=path):
            actual.add(path.relative_to(PROJECT_ROOT).as_posix())

    assert actual == TELEGRAM_TRANSPORT_IMPORT_ALLOWLIST


def test_shared_telegram_transport_import_detection_covers_module_forms() -> None:
    transport_imports = (
        ("import trendradar.telegram", "trendradar/cr/example.py"),
        (
            "import trendradar.telegram.transport as transport",
            "trendradar/cr/example.py",
        ),
        ("from trendradar import telegram", "trendradar/cr/example.py"),
        (
            "from trendradar.telegram import TelegramTransport",
            "trendradar/cr/example.py",
        ),
        (
            "from trendradar.telegram import transport",
            "trendradar/cr/example.py",
        ),
        (
            "from trendradar.telegram.transport import TelegramTransport",
            "trendradar/cr/example.py",
        ),
        (
            "from trendradar.telegram.transport import "
            "UrllibTelegramHTTPClient",
            "trendradar/cr/example.py",
        ),
        (
            "from ..telegram.transport import TelegramTransport",
            "trendradar/cr/example.py",
        ),
        (
            "from ..telegram.transport import UrllibTelegramHTTPClient",
            "trendradar/cr/example.py",
        ),
        (
            "from ..telegram import transport",
            "trendradar/cr/example.py",
        ),
        (
            "from .transport import UrllibTelegramHTTPClient",
            "trendradar/telegram/example.py",
        ),
    )
    for source, relpath in transport_imports:
        assert _imports_shared_telegram_transport(
            ast.parse(source),
            source_path=PROJECT_ROOT / relpath,
        ), source

    type_only_import = ast.parse(
        "from trendradar.telegram.transport import TelegramHTTPResponse"
    )
    assert not _imports_shared_telegram_transport(type_only_import)


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


def test_inbound_telegram_bot_surface_is_absent() -> None:
    bot_root = RUNTIME_ROOT / "telegram_bot"
    assert not bot_root.exists() or not any(bot_root.glob("*.py"))
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8") for path in _python_sources()
    )
    for token in (
        "TELEGRAM_RECEIVER_CHAT_IDS",
        "TELEGRAM_COMMAND_CHAT_IDS",
        "TELEGRAM_COMMANDS_ENABLED",
        "TELEGRAM_UNAUTHORIZED_BEHAVIOR",
    ):
        assert token not in runtime_text


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


BOUNDARY_CHECKS = (
    test_telegram_http_primitives_are_confined_to_explicit_senders,
    test_shared_telegram_transport_imports_are_confined_to_adapters,
    test_shared_telegram_transport_import_detection_covers_module_forms,
    test_generic_notification_package_and_runtime_symbols_stay_absent,
    test_operational_transport_remains_owner_only,
    test_inbound_telegram_bot_surface_is_absent,
    test_repository_config_has_no_generic_transport_sections,
    test_runtime_entrypoint_has_no_generic_delivery_controls,
    test_scheduler_and_timeline_have_no_delivery_controls,
    test_storage_schema_has_no_delivery_execution_state,
    test_transport_boundary_document_exists,
)


def load_tests(loader, tests, pattern):
    del loader, pattern
    tests.addTests(unittest.FunctionTestCase(check) for check in BOUNDARY_CHECKS)
    return tests
