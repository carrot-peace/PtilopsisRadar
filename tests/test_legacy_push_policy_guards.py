# coding=utf-8
"""
Policy guard scaffolding for the Legacy Push removal series.

These tests are intentionally source/doc checks. They do not import runtime
entrypoints, do not perform network I/O, and do not mutate the environment.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = PROJECT_ROOT / "docs" / "legacy_push_removal_plan.md"
CR_TELEGRAM_ENV_PATH = PROJECT_ROOT / "trendradar" / "cr" / "telegram_env.py"
CR_TELEGRAM_SINK_PATH = PROJECT_ROOT / "trendradar" / "cr" / "telegram_sink.py"
MAIN_PATH = PROJECT_ROOT / "trendradar" / "__main__.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _function_node(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function not found: {name}")


def _class_node(source: str, name: str) -> ast.ClassDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Class not found: {name}")


def _method_node(class_node: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Method not found: {class_node.name}.{name}")


def _assigned_dict_literal(class_node: ast.ClassDef, name: str) -> ast.Dict:
    for node in class_node.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Dict):
            return node.value
    raise AssertionError(f"Dict assignment not found: {class_node.name}.{name}")


def _is_exact_one(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "1"


def _is_cr_telegram_send_lookup(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "get":
        return False
    if not isinstance(node.func.value, ast.Name):
        return False
    if node.func.value.id != "env":
        return False
    return bool(node.args) and isinstance(node.args[0], ast.Constant) and (
        node.args[0].value == "PTILOPSIS_CR_TELEGRAM_SEND"
    )


def _compares_cr_telegram_send_to_exact_one(node: ast.AST) -> bool:
    if not isinstance(node, ast.Compare):
        return False
    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    if len(node.comparators) != 1:
        return False
    left = node.left
    right = node.comparators[0]
    return (
        _is_cr_telegram_send_lookup(left)
        and _is_exact_one(right)
        or _is_exact_one(left)
        and _is_cr_telegram_send_lookup(right)
    )


class TestLegacyPushRemovalPlanDoc(unittest.TestCase):
    def test_canonical_doc_exists(self) -> None:
        self.assertTrue(DOC_PATH.exists())

    def test_canonical_doc_contains_required_terms(self) -> None:
        text = _read(DOC_PATH)
        for term in (
            "Generation Plane",
            "Legacy Push",
            "CR-New",
            "PR-A",
            "PR-B",
            "PR-C1",
            "PR-D",
            "PR-C2",
            "PR-E",
            "Production Push",
        ):
            self.assertIn(term, text)

    def test_canonical_doc_records_current_dirty_state(self) -> None:
        text = _read(DOC_PATH)
        for phrase in (
            "Legacy Push is still live",
            "NotificationDispatcher.translate_content",
            "must not be deleted before PR-B",
            "Production Push is out of this series",
        ):
            self.assertIn(phrase, text)


class TestCRTelegramGateSourceGuards(unittest.TestCase):
    def test_cr_telegram_send_gate_requires_exact_one(self) -> None:
        source = _read(CR_TELEGRAM_ENV_PATH)
        function = _function_node(source, "cr_telegram_send_enabled")
        comparisons = [
            node
            for node in ast.walk(function)
            if _compares_cr_telegram_send_to_exact_one(node)
        ]
        self.assertTrue(comparisons)

    def test_cr_telegram_transport_modules_remain_under_cr_package(self) -> None:
        self.assertTrue(CR_TELEGRAM_ENV_PATH.exists())
        self.assertTrue(CR_TELEGRAM_SINK_PATH.exists())
        self.assertIn("trendradar/cr/telegram_env.py", CR_TELEGRAM_ENV_PATH.as_posix())
        self.assertIn("trendradar/cr/telegram_sink.py", CR_TELEGRAM_SINK_PATH.as_posix())

    def test_cr_telegram_send_gate_is_not_used_outside_cr_runtime_package(self) -> None:
        offenders: list[str] = []
        for path in _python_sources(PROJECT_ROOT / "trendradar"):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if rel.startswith("trendradar/cr/"):
                continue
            if "PTILOPSIS_CR_TELEGRAM_SEND" in _read(path):
                offenders.append(rel)
        self.assertEqual([], offenders)


class TestLegacyPushRuntimeDisconnectionGuards(unittest.TestCase):
    def test_normal_runtime_modes_are_artifact_only(self) -> None:
        source = _read(MAIN_PATH)
        analyzer = _class_node(source, "NewsAnalyzer")
        strategies = _assigned_dict_literal(analyzer, "MODE_STRATEGIES")

        by_mode: dict[str, ast.Dict] = {}
        for key, value in zip(strategies.keys, strategies.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Dict):
                by_mode[str(key.value)] = value

        self.assertEqual({"incremental", "current", "daily"}, set(by_mode))
        for mode, strategy in by_mode.items():
            fields = {
                str(key.value): value
                for key, value in zip(strategy.keys, strategy.values)
                if isinstance(key, ast.Constant)
            }
            self.assertIn("should_send_notification", fields, mode)
            self.assertIs(fields["should_send_notification"].value, False)

    def test_execute_mode_strategy_does_not_call_legacy_push(self) -> None:
        source = _read(MAIN_PATH)
        analyzer = _class_node(source, "NewsAnalyzer")
        method = _method_node(analyzer, "_execute_mode_strategy")
        forbidden = {
            "_send_notification_if_needed",
            "dispatch_all",
            "send_to_telegram",
            "record_execution",
        }

        offenders: list[str] = []
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in forbidden:
                    offenders.append(func.id)
                elif isinstance(func, ast.Attribute) and func.attr in forbidden:
                    offenders.append(func.attr)

        self.assertEqual([], offenders)

    def test_test_notification_fails_closed_without_dispatcher(self) -> None:
        source = _read(MAIN_PATH)
        function = _function_node(source, "_run_test_notification")
        forbidden = {"NotificationDispatcher", "dispatch_all", "send_to_telegram"}
        names: set[str] = set()

        for node in ast.walk(function):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)

        self.assertFalse(forbidden & names)
        self.assertTrue(
            any(
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "Legacy Push has been removed from runtime" in node.value
                for node in ast.walk(function)
            )
        )

    @unittest.expectedFailure
    def test_future_runtime_wiring_must_not_construct_notification_dispatcher(self) -> None:
        source = "\n".join(
            (
                _read(PROJECT_ROOT / "trendradar" / "__main__.py"),
                _read(PROJECT_ROOT / "trendradar" / "context.py"),
            )
        )
        self.assertNotIn("NotificationDispatcher", source)

    @unittest.expectedFailure
    def test_future_legacy_fallback_sender_must_be_unreachable(self) -> None:
        source = _read(PROJECT_ROOT / "trendradar" / "notification" / "senders.py")
        self.assertNotIn("fallback", source.lower())


if __name__ == "__main__":
    unittest.main()
