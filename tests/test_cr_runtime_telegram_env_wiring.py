# coding=utf-8
"""
Tests for CR Telegram env-gated runtime wiring (PR-CR-A1 update).

PR-CR-A1 replaces the PTILOPSIS_CR_DRY_RUN gate with
``resolve_cr_dispatch_mode`` in ``trendradar/__main__.py``.  The Telegram
sink factory is now reachable only through the ``live`` dispatch mode path.

These tests inspect the source by path (no import of ``trendradar.__main__``,
which requires third-party runtime deps) and assert:

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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_PATH = PROJECT_ROOT / "trendradar" / "__main__.py"

MODE_RESOLVE_TOKEN = "resolve_cr_dispatch_mode"
MODE_GATE_TOKEN = "_cr_mode != CR_DISPATCH_OFF"
LIVE_GATE_TOKEN = "_cr_mode == CR_DISPATCH_LIVE"
FACTORY_NAME = "build_cr_telegram_sink_from_env"
FACTORY_IMPORT = "from trendradar.cr.telegram_env import"


def _main_source() -> str:
    return MAIN_PATH.read_text(encoding="utf-8")


def _hook_region(source: str) -> str:
    """Extract the CR-A dispatch hook region from __main__.py.

    The region is the ``if _cr_mode != CR_DISPATCH_OFF:`` block plus the
    contiguous comment lines and the ``resolve_cr_dispatch_mode`` call above
    it.  Extraction is indentation-based.
    """
    lines = source.splitlines()
    gate_idx = next(i for i, line in enumerate(lines) if MODE_GATE_TOKEN in line)
    gate_indent = len(lines[gate_idx]) - len(lines[gate_idx].lstrip())

    # Walk backwards to include the resolve call and comments above the gate.
    start = gate_idx
    while start > 0 and (
        lines[start - 1].strip().startswith("#")
        or MODE_RESOLVE_TOKEN in lines[start - 1]
        or not lines[start - 1].strip()
    ):
        start -= 1

    end = gate_idx + 1
    while end < len(lines):
        line = lines[end]
        if not line.strip():
            end += 1
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= gate_indent:
            break
        end += 1

    return "\n".join(lines[start:end])


# ---------------------------------------------------------------------------
# Test Group A — Source wiring
# ---------------------------------------------------------------------------


class TestSourceWiring(unittest.TestCase):
    """Group A: required wiring tokens are present in __main__.py."""

    REQUIRED_TOKENS = (
        "resolve_cr_dispatch_mode",
        "CR_DISPATCH_OFF",
        "CR_DISPATCH_LIVE",
        "build_and_write_cr_runtime_dry_run",
    )

    def test_required_tokens_present(self) -> None:
        source = _main_source()
        for token in self.REQUIRED_TOKENS:
            self.assertIn(
                token, source, f"required wiring token {token!r} missing"
            )

    def test_dispatch_sink_conditionally_built_for_live(self) -> None:
        source = _main_source()
        self.assertIn("_cr_mode == CR_DISPATCH_LIVE", source)

    def test_sink_passed_into_dry_run_call(self) -> None:
        region = _hook_region(_main_source())
        self.assertIn("build_and_write_cr_runtime_dry_run(", region)
        self.assertIn("dispatch_sink=_dispatch_sink", region)


# ---------------------------------------------------------------------------
# Test Group B — Lazy import boundary
# ---------------------------------------------------------------------------


class TestLazyImportBoundary(unittest.TestCase):
    """Group B: factory import stays lazy, inside the dispatch-mode gate."""

    def test_factory_import_present_and_after_gate(self) -> None:
        source = _main_source()
        self.assertIn(FACTORY_IMPORT, source)
        gate_pos = source.index(MODE_GATE_TOKEN)
        self.assertGreater(
            source.index(FACTORY_NAME),
            gate_pos,
            "factory must first appear after the dispatch-mode gate",
        )

    def test_no_top_level_telegram_import_via_ast(self) -> None:
        tree = ast.parse(_main_source())
        for node in tree.body:  # module-level statements only
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn("telegram_env", module)
                self.assertNotIn("telegram_sink", module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn("telegram_env", alias.name)
                    self.assertNotIn("telegram_sink", alias.name)

    def test_every_telegram_env_reference_is_indented(self) -> None:
        for line in _main_source().splitlines():
            if "telegram_env" in line:
                self.assertTrue(
                    line.startswith(" "),
                    f"telegram_env referenced at top level: {line!r}",
                )

    def test_factory_import_inside_gated_block(self) -> None:
        region = _hook_region(_main_source())
        self.assertIn(FACTORY_IMPORT, region)


# ---------------------------------------------------------------------------
# Test Group C — No independent Telegram runtime path
# ---------------------------------------------------------------------------


class TestNoIndependentTelegramPath(unittest.TestCase):
    """Group C: Telegram is reachable only through the CR live-mode hook."""

    def test_send_gate_name_not_used_as_code_in_main(self) -> None:
        # The send gate is checked inside the PR9o factory, never in
        # __main__.py code — so no separate runtime branch can exist on it.
        # Comments and docstrings are allowed as documentation.
        import ast
        tree = ast.parse(_main_source())
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
        source = _main_source()
        region = _hook_region(source)
        self.assertEqual(
            source.count(FACTORY_NAME),
            region.count(FACTORY_NAME),
            "factory referenced outside the CR dispatch hook region",
        )
        # Exactly two references: the lazy import and the single call.
        self.assertEqual(region.count(FACTORY_NAME), 2)


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
        region = _hook_region(_main_source())
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token,
                region,
                f"forbidden token {token!r} present in CR dispatch hook region",
            )

    def test_hook_region_imports_only_cr_modules(self) -> None:
        region = _hook_region(_main_source())
        for line in region.splitlines():
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")):
                self.assertIn(
                    "trendradar.cr.",
                    stripped,
                    f"hook region import outside trendradar.cr: {stripped!r}",
                )


if __name__ == "__main__":
    unittest.main()
