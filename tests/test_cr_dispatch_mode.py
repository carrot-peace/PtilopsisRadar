# coding=utf-8
"""
Tests for CR-A dispatch mode resolution (PR-CR-A1).

Covers:
  Group A — Mode resolution from env vars
  Group B — Runtime behavior wiring (source-level checks)
  Group C — Source boundary (no legacy push, no independent Telegram path)

No real network calls.  No real tokens.  No environment mutation.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from trendradar.cr.dispatch_mode import resolve_cr_dispatch_mode


# ---------------------------------------------------------------------------
# Test Group A — Mode resolution
# ---------------------------------------------------------------------------


class TestModeResolution(unittest.TestCase):
    """Group A: resolve_cr_dispatch_mode returns the correct mode."""

    def test_env_unset_returns_off(self) -> None:
        self.assertEqual(resolve_cr_dispatch_mode({}), "off")

    def test_explicit_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "off"}),
            "off",
        )

    def test_explicit_artifact(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "artifact"}),
            "artifact",
        )

    def test_explicit_shadow(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "shadow"}),
            "shadow",
        )

    def test_explicit_live(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "live"}),
            "live",
        )

    def test_invalid_value_returns_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "bogus"}),
            "off",
        )

    def test_empty_value_returns_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": ""}),
            "off",
        )

    def test_whitespace_only_returns_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "   "}),
            "off",
        )

    def test_case_insensitive(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "ARTIFACT"}),
            "artifact",
        )
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "Live"}),
            "live",
        )

    def test_stripped_value(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "  shadow  "}),
            "shadow",
        )


# ---------------------------------------------------------------------------
# Test Group A2 — Compatibility alias (PTILOPSIS_CR_DRY_RUN)
# ---------------------------------------------------------------------------


class TestDryRunCompatAlias(unittest.TestCase):
    """Group A2: PTILOPSIS_CR_DRY_RUN=1 maps to artifact."""

    def test_dry_run_one_maps_to_artifact(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": "1"}),
            "artifact",
        )

    def test_dry_run_zero_is_ignored(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": "0"}),
            "off",
        )

    def test_dry_run_other_value_is_ignored(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": "true"}),
            "off",
        )

    def test_dry_run_empty_is_ignored(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": ""}),
            "off",
        )


# ---------------------------------------------------------------------------
# Test Group A3 — Precedence
# ---------------------------------------------------------------------------


class TestPrecedence(unittest.TestCase):
    """Group A3: explicit PTILOPSIS_CR_DISPATCH_MODE wins over DRY_RUN."""

    def test_dispatch_mode_wins_over_dry_run(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "live",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            "live",
        )

    def test_dispatch_mode_off_wins_over_dry_run(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "off",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            "off",
        )

    def test_dispatch_mode_artifact_wins_over_dry_run(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "artifact",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            "artifact",
        )

    def test_invalid_dispatch_mode_wins_over_dry_run(self) -> None:
        """Invalid dispatch mode → off, even when DRY_RUN=1 is set."""
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "invalid",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            "off",
        )


# ---------------------------------------------------------------------------
# Test Group B — Runtime behavior (source-level)
# ---------------------------------------------------------------------------


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_PATH = PROJECT_ROOT / "trendradar" / "__main__.py"


def _main_source() -> str:
    return MAIN_PATH.read_text(encoding="utf-8")


class TestRuntimeBehavior(unittest.TestCase):
    """Group B: source-level checks for dispatch mode wiring."""

    def test_main_uses_resolve_cr_dispatch_mode(self) -> None:
        source = _main_source()
        self.assertIn("resolve_cr_dispatch_mode", source)

    def test_main_checks_off_mode(self) -> None:
        source = _main_source()
        self.assertIn('_cr_mode != "off"', source)

    def test_main_checks_live_mode_for_sink(self) -> None:
        source = _main_source()
        self.assertIn('_cr_mode == "live"', source)

    def test_main_does_not_use_dry_run_as_gate(self) -> None:
        """The old PTILOPSIS_CR_DRY_RUN gate is replaced by dispatch mode."""
        source = _main_source()
        # The old pattern: if os.environ.get("PTILOPSIS_CR_DRY_RUN") == "1":
        self.assertNotIn(
            'os.environ.get("PTILOPSIS_CR_DRY_RUN") == "1"',
            source,
        )

    def test_dry_run_still_referenced_in_dispatch_mode_module(self) -> None:
        """dispatch_mode.py references DRY_RUN for compatibility."""
        dm_path = PROJECT_ROOT / "trendradar" / "cr" / "dispatch_mode.py"
        source = dm_path.read_text(encoding="utf-8")
        self.assertIn("PTILOPSIS_CR_DRY_RUN", source)

    def test_artifact_and_shadow_do_not_build_sink(self) -> None:
        """In __main__.py, the sink is only built inside the live check."""
        source = _main_source()
        # Find the live-mode block
        live_pos = source.index('_cr_mode == "live"')
        sink_build_pos = source.index("build_cr_telegram_sink_from_env", live_pos)
        # The sink build must be after the live check
        self.assertGreater(sink_build_pos, live_pos)

    def test_dispatch_sink_default_is_none(self) -> None:
        """_dispatch_sink defaults to None before the live check."""
        source = _main_source()
        self.assertIn("_dispatch_sink = None", source)


# ---------------------------------------------------------------------------
# Test Group C — Source boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """Group C: no legacy push or independent Telegram path in dispatch hook."""

    def test_no_legacy_push_tokens_in_dispatch_hook(self) -> None:
        """The dispatch hook region must not reference legacy push."""
        source = _main_source()
        lines = source.splitlines()
        # Find the dispatch hook block
        gate_idx = next(
            i for i, line in enumerate(lines) if '_cr_mode != "off"' in line
        )
        gate_indent = len(lines[gate_idx]) - len(lines[gate_idx].lstrip())
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
        region = "\n".join(lines[gate_idx:end])

        forbidden = (
            "_send_notification_if_needed",
            "dispatch_all",
            "send_to_telegram",
            "trendradar.notification",
            "NotificationDispatcher",
        )
        for token in forbidden:
            self.assertNotIn(
                token,
                region,
                f"legacy push token {token!r} in dispatch hook region",
            )

    def test_no_ptilopsis_cr_telegram_send_code_in_main(self) -> None:
        """PTILOPSIS_CR_TELEGRAM_SEND must not appear as code in __main__.py.

        Comments are allowed (documentation).  String literals and code
        references are not.
        """
        import ast
        tree = ast.parse(_main_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "PTILOPSIS_CR_TELEGRAM_SEND" in node.value:
                    self.fail(
                        "PTILOPSIS_CR_TELEGRAM_SEND found in string literal "
                        f"in __main__.py: {node.value!r}"
                    )


if __name__ == "__main__":
    unittest.main()
