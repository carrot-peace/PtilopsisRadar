import ast
import unittest
from pathlib import Path

from tests.test_cr_repeat_preview_rendering import _event_key, _make_presented
from trendradar.cr.decision import DECISION_ALERT
from trendradar.cr.repeat_preview import CRSeenEventState


ROOT = Path(__file__).parents[1]


class CRRenderModelTests(unittest.TestCase):
    def test_builder_produces_typed_identity_repeat_and_cooldown_views(self):
        from trendradar.cr.render_model import (
            CRAuditRenderModel,
            build_cr_audit_render_model,
        )

        candidate = _make_presented(total_score=67.0)
        key = _event_key(candidate)

        model = build_cr_audit_render_model(
            [candidate],
            run_label="T",
            include_event_identity=True,
            include_repeat_preview=True,
            include_cooldown_decision=True,
            seen_event_states={
                key: CRSeenEventState(
                    event_key=key,
                    decision_level=DECISION_ALERT,
                    score=65.0,
                )
            },
        )

        self.assertIsInstance(model, CRAuditRenderModel)
        self.assertEqual(model.run_label, "T")
        self.assertEqual(len(model.candidates), 1)
        view = model.candidates[0]
        self.assertEqual(view.identity.event_key, key)
        self.assertEqual(
            view.repeat_preview.status,
            "same_level_repeat",
        )
        self.assertIsNotNone(view.cooldown_decision)
        self.assertEqual(model.sections[1].level, DECISION_ALERT)
        self.assertEqual(model.sections[1].candidates, (view,))

    def test_pure_renderers_consume_the_same_precomputed_model(self):
        from trendradar.cr.html import (
            CRHTMLRenderConfig,
            render_cr_html_model,
        )
        from trendradar.cr.markdown import (
            CRMarkdownRenderConfig,
            render_cr_markdown_model,
        )
        from trendradar.cr.render_model import build_cr_audit_render_model

        candidate = _make_presented()
        model = build_cr_audit_render_model(
            [candidate],
            run_label="T",
            include_event_identity=True,
        )

        markdown = render_cr_markdown_model(
            model,
            config=CRMarkdownRenderConfig(),
        )
        html = render_cr_html_model(
            model,
            config=CRHTMLRenderConfig(),
        )

        self.assertIn("#### Event Identity", markdown)
        self.assertIn('class="event-identity"', html)
        self.assertIn(
            model.candidates[0].identity.event_key,
            markdown,
        )
        self.assertIn(
            model.candidates[0].identity.event_key,
            html,
        )

    def test_renderer_modules_do_not_run_domain_evidence_functions(self):
        forbidden = {
            "build_cr_event_identity_from_candidate",
            "preview_cr_repeat",
            "decide_cr_cooldown",
            "input_health_to_json_dict",
            "sort_cr_presented_candidates",
        }
        for relative in (
            "trendradar/cr/markdown.py",
            "trendradar/cr/html.py",
        ):
            tree = ast.parse(
                (ROOT / relative).read_text(encoding="utf-8")
            )
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            self.assertTrue(
                forbidden.isdisjoint(imported),
                f"{relative} still computes domain evidence",
            )


if __name__ == "__main__":
    unittest.main()
