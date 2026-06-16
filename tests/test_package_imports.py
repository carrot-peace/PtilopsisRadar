# coding=utf-8
"""
包初始化与 AppContext 惰性导出测试。

验证 import trendradar / trendradar.core.analyzer 不会因为 package init
而提前拉起 trendradar.context，同时 `from trendradar import AppContext` 仍可用。
"""

import importlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 受关注的、本应被惰性化、不该在 package init 阶段出现的模块。
LAZY_MODULES = ("trendradar.context",)


def _purge(prefix):
    """从 sys.modules 中移除 prefix 及其子模块，避免测试间互相污染。"""
    for name in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
        del sys.modules[name]


class PackageImportTest(unittest.TestCase):
    def setUp(self):
        # 每个用例从干净状态开始，确保 import 真实发生而非命中缓存。
        for prefix in ("trendradar",):
            _purge(prefix)

    def tearDown(self):
        # 清理本测试引入的模块，避免污染其他测试。
        for prefix in ("trendradar",):
            _purge(prefix)

    def test_import_trendradar_does_not_pull_context_or_notification(self):
        importlib.import_module("trendradar")
        for mod in LAZY_MODULES:
            self.assertNotIn(
                mod,
                sys.modules,
                f"import trendradar 不应把 {mod} 加入 sys.modules",
            )

    def test_import_core_analyzer_does_not_pull_context_or_notification(self):
        importlib.import_module("trendradar.core.analyzer")
        for mod in LAZY_MODULES:
            self.assertNotIn(
                mod,
                sys.modules,
                f"import trendradar.core.analyzer 不应把 {mod} 加入 sys.modules",
            )

    def test_appcontext_lazy_export_still_works(self):
        import trendradar

        self.assertNotIn(
            "trendradar.context",
            sys.modules,
            "仅 import trendradar 时不应已经导入 trendradar.context",
        )

        from trendradar import AppContext

        # 访问后允许 lazy import trendradar.context。
        from trendradar.context import AppContext as RealAppContext

        self.assertIs(AppContext, RealAppContext)
        self.assertIn("trendradar.context", sys.modules)

    def test_unknown_attribute_raises_attribute_error(self):
        import trendradar

        with self.assertRaises(AttributeError):
            trendradar.__getattr__("missing")


if __name__ == "__main__":
    unittest.main()
