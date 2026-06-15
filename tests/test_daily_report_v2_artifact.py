# coding=utf-8
"""
Daily Report v2 — artifact-only model/renderer tests (PR-D).

These tests prove DR v2 is a Generation Plane artifact product only:
- it does not import the notification package or call any legacy sender;
- it does not use the CR Telegram sink / env;
- it applies the seven DR v2 artifact-quality rules
  (overview, item body, risk separation, noise demotion, domestic confidence,
  suppressed compactness, raw cap).

The DR v2 module is loaded via the lightweight _bootstrap loader so the suite
runs under the user's minimal interpreter without third-party deps or network.
"""

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

_BOOT = _bootstrap.load_all()  # registers trendradar.ai.evidence / analyzer / ...
AIAnalysisResult = _BOOT.analyzer.AIAnalysisResult

_bootstrap._ensure_pkg("trendradar.report")
DV2 = _bootstrap._load_file(
    "trendradar.report.daily_v2", "trendradar/report/daily_v2.py"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Tokens that DR / report / generation code must never import or call.
_FORBIDDEN_TOKENS = (
    "trendradar.notification",
    "NotificationDispatcher",
    "dispatch_all",
    "send_to_telegram",
    "send_telegram_document",
    "telegram_sink",
    "telegram_env",
    "PTILOPSIS_CR_TELEGRAM_SEND",
    "CRDispatchPlan",
)


# ─────────────────────────────────────────────────────────────
# Test data helpers
# ─────────────────────────────────────────────────────────────


def _detail(
    *,
    tiers=("D",),
    sources_by_tier=None,
    d_count=1,
    platform_count=1,
    samples=None,
):
    by_tier = sources_by_tier or {t: [f"src-{t}"] for t in tiers}
    return {
        "topic_group": "T",
        "source_tiers_present": list(tiers),
        "sources_by_tier": by_tier,
        "d_tier_platform_count": d_count,
        "platform_count": platform_count,
        "sample_titles": samples or [],
    }


def _entry(
    topic,
    *,
    summary="",
    analysis="",
    verification_status="高热待核实",
    factual_boundary="边界提示",
    risk_note=None,
    sentiment_flag=False,
    source_layers="D",
    platform_count=1,
    highest_heat="微博 第3名",
    detail=None,
    samples=None,
):
    e = {
        "topic": topic,
        "summary": summary,
        "analysis": analysis,
        "source_layers": source_layers,
        "platforms": "微博",
        "platform_count": platform_count,
        "highest_heat": highest_heat,
        "verification_status": verification_status,
        "factual_boundary": factual_boundary,
        "sentiment_flag": sentiment_flag,
        "evidence_detail": detail or _detail(samples=samples),
    }
    if risk_note is not None:
        e["risk_note"] = risk_note
    return e


def _ai(**fields):
    base = dict(success=True, report_style="environment", overview="今日盘面平稳")
    base.update(fields)
    return AIAnalysisResult(**base)


# ─────────────────────────────────────────────────────────────
# Test 1: Artifact-only boundary
# ─────────────────────────────────────────────────────────────


class TestArtifactOnlyBoundary(unittest.TestCase):
    def _sources(self):
        roots = [
            PROJECT_ROOT / "trendradar" / "report",
            PROJECT_ROOT / "trendradar" / "ai",
            PROJECT_ROOT / "trendradar" / "core",
        ]
        files = []
        for root in roots:
            if root.exists():
                files.extend(
                    p for p in root.rglob("*.py") if "__pycache__" not in p.parts
                )
        return files

    def test_daily_v2_source_has_no_forbidden_tokens(self):
        src = (PROJECT_ROOT / "trendradar" / "report" / "daily_v2.py").read_text(
            encoding="utf-8"
        )
        for token in _FORBIDDEN_TOKENS:
            self.assertNotIn(token, src, token)

    def test_generation_plane_does_not_reference_forbidden_tokens(self):
        offenders = []
        for path in self._sources():
            text = path.read_text(encoding="utf-8")
            for token in _FORBIDDEN_TOKENS:
                if token in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}::{token}")
        self.assertEqual([], offenders)

    def test_daily_v2_imports_no_notification_or_transport(self):
        tree = ast.parse(
            (PROJECT_ROOT / "trendradar" / "report" / "daily_v2.py").read_text(
                encoding="utf-8"
            )
        )
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        for mod in imported:
            self.assertNotIn("notification", mod)
            self.assertNotIn(".cr", mod)
            self.assertNotIn("telegram", mod)


# ─────────────────────────────────────────────────────────────
# Test 2: Missing overview produces degraded artifact state
# ─────────────────────────────────────────────────────────────


class TestMissingOverviewDegraded(unittest.TestCase):
    def test_ai_backed_missing_overview_marks_degraded(self):
        ai = _ai(overview="")  # AI-backed but no overview
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        self.assertTrue(model.ai_backed)
        self.assertTrue(model.degraded)
        self.assertEqual(model.degraded_notice, DV2.DEGRADED_OVERVIEW_NOTICE)

    def test_degraded_notice_rendered_not_normal_report(self):
        ai = _ai(overview="")
        html = DV2.render_daily_report_v2({"stats": []}, ai_analysis=ai)
        self.assertIn(DV2.DEGRADED_OVERVIEW_NOTICE, html)
        self.assertIn("degraded-notice", html)

    def test_present_overview_is_not_degraded(self):
        ai = _ai(overview="今日信息环境整体平稳")
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        self.assertFalse(model.degraded)
        self.assertEqual(model.overview, "今日信息环境整体平稳")

    def test_no_ai_uses_no_ai_notice_not_degraded_overview(self):
        model = DV2.build_daily_report_v2(None, {"stats": []})
        self.assertFalse(model.ai_backed)
        self.assertFalse(model.degraded)
        self.assertEqual(model.degraded_notice, DV2.NO_AI_NOTICE)


# ─────────────────────────────────────────────────────────────
# Test 3: Generic risk template is not accepted as item body
# ─────────────────────────────────────────────────────────────


class TestGenericRiskTemplateRejected(unittest.TestCase):
    def test_is_generic_risk_template_detection(self):
        self.assertTrue(DV2.is_generic_risk_template(""))
        self.assertTrue(DV2.is_generic_risk_template("   "))
        self.assertTrue(DV2.is_generic_risk_template("该事件存在传播风险"))
        self.assertTrue(DV2.is_generic_risk_template("事实仍待核验"))
        self.assertTrue(DV2.is_generic_risk_template("需关注后续信息"))
        self.assertTrue(DV2.is_generic_risk_template(DV2.RISK_NOTE_HIGH_HEAT))
        # concrete event content is not a generic template
        self.assertFalse(
            DV2.is_generic_risk_template("某地宣布调整防汛应急响应至二级，多部门已介入")
        )

    def test_generic_body_is_degraded_and_summary_blanked(self):
        ai = _ai(
            high_heat_unverified=[
                _entry("某话题", summary="该事件存在传播风险")
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        self.assertEqual(len(model.main_items), 1)
        item = model.main_items[0]
        self.assertTrue(item.degraded)
        self.assertEqual(item.summary, "")

    def test_risk_note_separated_from_summary(self):
        ai = _ai(
            high_heat_unverified=[
                _entry(
                    "真实事件",
                    summary="某公司宣布召回一批次产品，涉及十万台设备",
                    risk_note=DV2.RISK_NOTE_HIGH_HEAT,
                )
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        item = model.main_items[0]
        self.assertFalse(item.degraded)
        self.assertEqual(item.summary, "某公司宣布召回一批次产品，涉及十万台设备")
        self.assertEqual(item.risk_note, DV2.RISK_NOTE_HIGH_HEAT)
        self.assertNotEqual(item.summary, item.risk_note)

    def test_factual_boundary_falls_into_risk_note_not_body(self):
        ai = _ai(
            high_heat_unverified=[
                _entry(
                    "事件X",
                    summary="",
                    analysis="",
                    factual_boundary="该事件存在传播风险",
                )
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        item = model.main_items[0]
        # body degraded (no concrete summary), boundary text only in risk_note
        self.assertTrue(item.degraded)
        self.assertEqual(item.summary, "")
        self.assertEqual(item.risk_note, "该事件存在传播风险")

    def test_rendered_item_shows_degraded_notice_not_fake_body(self):
        ai = _ai(
            high_heat_unverified=[_entry("空话题", summary="待核验")]
        )
        html = DV2.render_daily_report_v2({"stats": []}, ai_analysis=ai)
        self.assertIn(DV2.DEGRADED_ITEM_NOTICE, html)


# ─────────────────────────────────────────────────────────────
# Test 4: Entertainment / sports / esports noise handling
# ─────────────────────────────────────────────────────────────


class TestNoiseHandling(unittest.TestCase):
    def test_classify_category(self):
        self.assertEqual(DV2.classify_category("某明星新剧官宣"), "entertainment")
        self.assertEqual(DV2.classify_category("世界杯决赛进球集锦"), "sports")
        self.assertEqual(DV2.classify_category("LPL 战队晋级全球总决赛"), "esports")
        self.assertIsNone(DV2.classify_category("某地发布防汛通告"))

    def test_noise_not_promoted_to_main_section(self):
        ai = _ai(
            high_heat_unverified=[
                _entry(
                    "某明星演唱会塌房",
                    summary="某明星演唱会被指假唱，粉丝大量讨论",
                    samples=[{"title": "某明星演唱会塌房上热搜"}],
                )
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        # demoted out of main items
        self.assertEqual(model.main_items, [])
        # appears in suppressed noise
        cats = [g.category for g in model.suppressed]
        self.assertIn("娱乐", cats)

    def test_noise_count_is_real_total_not_capped_examples(self):
        # 10 entertainment noise items, example cap 3 → count==10, examples<=3.
        ai = _ai(
            high_heat_unverified=[
                _entry(
                    f"某明星塌房事件{i}",
                    summary=f"某明星塌房事件{i}，粉丝大量讨论",
                    samples=[{"title": f"某明星塌房事件{i}上热搜"}],
                )
                for i in range(10)
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        self.assertEqual(model.main_items, [])
        noise_groups = [g for g in model.suppressed if g.category == "娱乐"]
        self.assertEqual(len(noise_groups), 1)
        group = noise_groups[0]
        self.assertEqual(group.count, 10)
        self.assertLessEqual(len(group.examples), DV2.SUPPRESSED_EXAMPLE_CAP)
        # logical suppressed total reflects the real 10, not the 3 examples
        self.assertEqual(model.suppressed_count, 10)
        html = DV2.render_daily_report_v2({"stats": []}, ai_analysis=ai)
        self.assertIn("合计 10", html)

    def test_structurally_relevant_entertainment_is_promoted(self):
        ai = _ai(
            high_heat_unverified=[
                _entry(
                    "某综艺被网信办约谈下架",
                    summary="监管部门通报某综艺违规，平台已下架并处罚",
                    samples=[{"title": "网信办约谈某平台 综艺下架"}],
                )
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        topics = [it.topic for it in model.main_items]
        self.assertIn("某综艺被网信办约谈下架", topics)

    def test_is_noise_item_structural_override(self):
        self.assertTrue(DV2.is_noise_item("某球员转会", [{"title": "某球员转会创纪录"}]))
        self.assertFalse(
            DV2.is_noise_item("某球员涉刑事案件被警方立案", None)
        )


# ─────────────────────────────────────────────────────────────
# Test 5: Domestic public event confidence
# ─────────────────────────────────────────────────────────────


class TestDomesticConfidence(unittest.TestCase):
    def test_cd_multiplatform_gets_domestic_status_not_downgraded(self):
        status = DV2.domestic_confidence_status(
            has_A=False, has_B=False, has_C=True, has_D=True,
            d_tier_platform_count=3, platform_count=5,
        )
        self.assertIn(
            status,
            {
                DV2.DOMESTIC_CONFIRMED,
                DV2.DOMESTIC_HIGH_CONFIDENCE,
                DV2.DOMESTIC_PUBLIC_EVENT,
            },
        )
        self.assertEqual(status, DV2.DOMESTIC_CONFIRMED)

    def test_cd_two_platforms_high_confidence(self):
        status = DV2.domestic_confidence_status(
            has_A=False, has_B=False, has_C=True, has_D=True,
            d_tier_platform_count=2, platform_count=3,
        )
        self.assertEqual(status, DV2.DOMESTIC_HIGH_CONFIDENCE)

    def test_no_ab_does_not_force_none_when_domestic_spread(self):
        status = DV2.domestic_confidence_status(
            has_A=False, has_B=False, has_C=True, has_D=True,
            d_tier_platform_count=1, platform_count=2,
        )
        self.assertEqual(status, DV2.DOMESTIC_PUBLIC_EVENT)

    def test_ab_present_returns_none(self):
        status = DV2.domestic_confidence_status(
            has_A=True, has_B=False, has_C=True, has_D=True,
            d_tier_platform_count=3, platform_count=5,
        )
        self.assertIsNone(status)

    def test_item_status_uses_domestic_label(self):
        detail = _detail(
            tiers=("C", "D"),
            sources_by_tier={"C": ["澎湃"], "D": ["微博", "抖音", "贴吧"]},
            d_count=3,
            platform_count=5,
        )
        ai = _ai(
            chinese_only_hot=[
                _entry(
                    "某地公共事件",
                    summary="某地发生公共事件，多家平台与严肃媒体报道",
                    verification_status="中文源呼应(缺A/B背景)",
                    source_layers="C/D",
                    detail=detail,
                )
            ]
        )
        model = DV2.build_daily_report_v2(ai, {"stats": []})
        item = model.main_items[0]
        self.assertEqual(
            item.status, DV2._DOMESTIC_STATUS_LABELS[DV2.DOMESTIC_CONFIRMED]
        )


# ─────────────────────────────────────────────────────────────
# Test 6: Suppressed section compactness
# ─────────────────────────────────────────────────────────────


class TestSuppressedCompactness(unittest.TestCase):
    def _model(self):
        ai = _ai(
            sentiment_heavy=[
                _entry("情绪A", summary="x"),
                _entry("情绪B", summary="y"),
            ],
            background_notes=[
                "议题1（C）", "议题2（C）", "议题3（D）", "议题4（D）", "议题5（C）",
            ],
        )
        return DV2.build_daily_report_v2(ai, {"stats": []})

    def test_one_row_per_category_no_label_explanation_split(self):
        model = self._model()
        cats = [g.category for g in model.suppressed]
        # no duplicate category rows
        self.assertEqual(len(cats), len(set(cats)))

    def test_logical_count_matches_rendered_count(self):
        model = self._model()
        # logical = 2 sentiment + 5 background
        self.assertEqual(model.suppressed_count, 7)
        html = DV2.render_daily_report_v2({"stats": []}, ai_analysis=_ai(
            sentiment_heavy=[_entry("情绪A"), _entry("情绪B")],
            background_notes=["议题1（C）", "议题2（C）", "议题3（D）", "议题4（D）", "议题5（C）"],
        ))
        self.assertIn("合计 7", html)

    def test_examples_are_capped(self):
        model = self._model()
        for g in model.suppressed:
            self.assertLessEqual(len(g.examples), DV2.SUPPRESSED_EXAMPLE_CAP)


# ─────────────────────────────────────────────────────────────
# Test 7: Raw hotlist capped / collapsed
# ─────────────────────────────────────────────────────────────


class TestRawHotlistCapped(unittest.TestCase):
    def _stats(self, n_groups=20, n_titles=12):
        return [
            {
                "word": f"kw{i}",
                "count": n_titles,
                "titles": [
                    {"title": f"t{i}-{j}", "source_name": "微博"}
                    for j in range(n_titles)
                ],
            }
            for i in range(n_groups)
        ]

    def test_groups_capped(self):
        model = DV2.build_daily_report_v2(_ai(), {"stats": self._stats()})
        raw = model.raw_appendix
        self.assertEqual(raw.total_groups, 20)
        self.assertEqual(raw.shown_groups, DV2.RAW_APPENDIX_MAX_GROUPS)
        self.assertTrue(raw.truncated)

    def test_titles_capped_per_group(self):
        model = DV2.build_daily_report_v2(_ai(), {"stats": self._stats()})
        for grp in model.raw_appendix.groups:
            self.assertLessEqual(len(grp["titles"]), DV2.RAW_APPENDIX_MAX_TITLES)
            self.assertTrue(grp["titles_truncated"])

    def test_raw_is_collapsed_in_appendix_not_main_digest(self):
        html = DV2.render_daily_report_v2(
            {"stats": self._stats()}, ai_analysis=_ai()
        )
        # raw lives in a collapsed <details> appendix
        self.assertIn("<details class=\"raw\">", html)
        self.assertTrue(DV2.RawAppendix().collapsed)


# ─────────────────────────────────────────────────────────────
# Test 8: Legacy push remains fail-closed (DR adds no push surface)
# ─────────────────────────────────────────────────────────────


class TestLegacyPushRemainsFailClosed(unittest.TestCase):
    def test_dr_v2_module_defines_no_send_surface(self):
        src = (PROJECT_ROOT / "trendradar" / "report" / "daily_v2.py").read_text(
            encoding="utf-8"
        )
        for token in ("def send", "requests.post", "sendMessage", "sendDocument"):
            self.assertNotIn(token, src, token)

    def test_legacy_guard_suites_present(self):
        # DR v2 must not weaken the PR-A / PR-C1 guard suites.
        self.assertTrue(
            (PROJECT_ROOT / "tests" / "test_legacy_push_policy_guards.py").exists()
        )
        self.assertTrue(
            (PROJECT_ROOT / "tests" / "test_legacy_push_runtime_disconnect.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
