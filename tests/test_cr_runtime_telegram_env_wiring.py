# coding=utf-8
"""
Tests for CR Telegram env-gated runtime wiring (PR-CR-A1 update).

PR-CR-A1 replaces the PTILOPSIS_CR_DRY_RUN gate with
``resolve_cr_dispatch_mode`` in ``trendradar/__main__.py``.  The Telegram
sink factory is now reachable only through the ``live`` dispatch mode path.

These tests inspect the parsed syntax tree (without importing
``trendradar.__main__``, which requires third-party runtime deps) and assert:

  Group A — the wiring tokens are present;
  Group B — the factory import stays lazy, inside the dispatch-mode gate,
            never at module top level;
  Group C — no independent Telegram runtime branch exists: the send gate
            name never appears in __main__.py, and the factory is reachable
            only through the live-mode hook;
  Group D — the hook region introduces no forbidden subsystem tokens.

No real network calls.  No real tokens.  No environment mutation.
"""

from __future__ import annotations

import ast
import unittest

from tests.cr_main_ast import (
    calls,
    import_from_nodes,
    load_cr_dispatch_hook,
)


FACTORY_NAME = "build_cr_telegram_sink_from_env"


# ---------------------------------------------------------------------------
# Test Group A — Source wiring
# ---------------------------------------------------------------------------


class TestSourceWiring(unittest.TestCase):
    """Group A: resolver, mode gates, and runtime call are structurally wired."""

    def test_dispatch_mode_is_resolved_from_environment(self) -> None:
        hook = load_cr_dispatch_hook()
        call = hook.resolve_assignment.value
        self.assertIsInstance(call, ast.Call)
        self.assertEqual(len(call.args), 1)
        argument = call.args[0]
        self.assertIsInstance(argument, ast.Attribute)
        self.assertEqual(argument.attr, "environ")
        self.assertIsInstance(argument.value, ast.Name)
        self.assertEqual(argument.value.id, "os")

    def test_dispatch_sink_conditionally_built_for_live(self) -> None:
        hook = load_cr_dispatch_hook()
        self.assertEqual(len(calls(hook.live_gate, FACTORY_NAME)), 1)

    def test_sink_passed_into_dry_run_call(self) -> None:
        hook = load_cr_dispatch_hook()
        dispatch_sink = next(
            (
                keyword.value
                for keyword in hook.runtime_call.keywords
                if keyword.arg == "dispatch_sink"
            ),
            None,
        )
        self.assertIsInstance(dispatch_sink, ast.Name)
        self.assertEqual(dispatch_sink.id, "_dispatch_sink")


# ---------------------------------------------------------------------------
# Test Group B — Lazy import boundary
# ---------------------------------------------------------------------------


class TestLazyImportBoundary(unittest.TestCase):
    """Group B: factory import stays lazy, inside the dispatch-mode gate."""

    def test_factory_import_inside_live_gate(self) -> None:
        hook = load_cr_dispatch_hook()
        imports = import_from_nodes(
            hook.live_gate, "trendradar.cr.telegram_env"
        )
        self.assertEqual(len(imports), 1)
        self.assertIn(FACTORY_NAME, [alias.name for alias in imports[0].names])

    def test_no_top_level_telegram_import_via_ast(self) -> None:
        tree = load_cr_dispatch_hook().tree
        for node in tree.body:  # module-level statements only
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn("telegram_env", module)
                self.assertNotIn("telegram_sink", module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("telegram_env", alias.name)
                    self.assertNotIn("telegram_sink", alias.name)

    def test_factory_references_exist_only_inside_live_gate(self) -> None:
        hook = load_cr_dispatch_hook()
        all_calls = calls(hook.tree, FACTORY_NAME)
        live_calls = calls(hook.live_gate, FACTORY_NAME)
        all_imports = import_from_nodes(
            hook.tree, "trendradar.cr.telegram_env"
        )
        live_imports = import_from_nodes(
            hook.live_gate, "trendradar.cr.telegram_env"
        )
        self.assertEqual(all_calls, live_calls)
        self.assertEqual(all_imports, live_imports)


# ---------------------------------------------------------------------------
# Test Group C — No independent Telegram runtime path
# ---------------------------------------------------------------------------


class TestNoIndependentTelegramPath(unittest.TestCase):
    """Group C: Telegram is reachable only through the CR live-mode hook."""

    def test_send_gate_name_not_used_as_code_in_main(self) -> None:
        # The send gate is checked inside the PR9o factory, never in
        # __main__.py code — so no separate runtime branch can exist on it.
        # Comments and docstrings are allowed as documentation.
        tree = load_cr_dispatch_hook().tree
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "os"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "PTILOPSIS_CR_TELEGRAM_SEND"
            ):
                self.fail("PTILOPSIS_CR_TELEGRAM_SEND read via os.environ.get")
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "os"
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "PTILOPSIS_CR_TELEGRAM_SEND"
            ):
                self.fail("PTILOPSIS_CR_TELEGRAM_SEND read via os.environ[]")

    def test_factory_only_referenced_inside_hook_region(self) -> None:
        hook = load_cr_dispatch_hook()
        self.assertEqual(len(calls(hook.tree, FACTORY_NAME)), 1)
        self.assertEqual(
            len(import_from_nodes(hook.tree, "trendradar.cr.telegram_env")),
            1,
        )


# ---------------------------------------------------------------------------
# Test Group D — Forbidden subsystem boundary (hook region scoped)
# ---------------------------------------------------------------------------


class TestHookRegionBoundary(unittest.TestCase):
    """Group D: the hook region introduces no forbidden subsystem tokens.

    Scoped to the hook region because __main__.py as a whole legitimately
    uses storage / ai / requests for the normal runtime.
    """

    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "requests",
        "httpx",
        "aiohttp",
        "cooldown",
        "dedupe",
        "alert_state",
    )

    def test_no_forbidden_tokens_in_hook_region(self) -> None:
        region = ast.unparse(load_cr_dispatch_hook().off_gate)
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token,
                region,
                f"forbidden token {token!r} present in CR dispatch hook region",
            )

    def test_hook_region_imports_only_cr_modules(self) -> None:
        hook = load_cr_dispatch_hook()
        for node in ast.walk(hook.off_gate):
            if isinstance(node, ast.ImportFrom):
                self.assertTrue(
                    (node.module or "").startswith("trendradar.cr."),
                    f"hook import outside trendradar.cr: {node.module!r}",
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertTrue(
                        alias.name.startswith("trendradar.cr."),
                        f"hook import outside trendradar.cr: {alias.name!r}",
                    )


if __name__ == "__main__":
    unittest.main()
