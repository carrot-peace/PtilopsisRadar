# coding=utf-8
"""Lightweight real-report/context bootstrap shared by routing smoke tests."""

import importlib.util
import os
import sys
import types
from types import SimpleNamespace

import _bootstrap


ROOT = _bootstrap.ROOT


def _attach_getattr(module):
    """Let a stub satisfy imports and annotations with inert placeholder types."""

    def __getattr__(name):
        value = type(name, (), {})
        setattr(module, name, value)
        return value

    module.__getattr__ = __getattr__
    return module


def stub_module(name, *, is_pkg=True):
    """Install or extend a permissive lightweight module stub."""
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    if is_pkg and not hasattr(module, "__path__"):
        module.__path__ = []
    return _attach_getattr(module)


def load_real(name, relpath):
    """Load one repository module by path without importing package init files."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_report_context():
    """Load real report renderers and AppContext with heavy dependencies stubbed."""
    _bootstrap.load_all()

    report_pkg = stub_module("trendradar.report")
    generator = load_real(
        "trendradar.report.generator", "trendradar/report/generator.py"
    )
    report_pkg.prepare_report_data = generator.prepare_report_data
    report_pkg.generate_html_report = generator.generate_html_report

    dashboard = load_real(
        "trendradar.report.dashboard", "trendradar/report/dashboard.py"
    )
    daily_v2 = load_real(
        "trendradar.report.daily_v2", "trendradar/report/daily_v2.py"
    )
    newsletter = load_real(
        "trendradar.report.newsletter", "trendradar/report/newsletter.py"
    )

    for name in (
        "trendradar.utils",
        "trendradar.utils.time",
        "trendradar.core",
        "trendradar.ai",
        "trendradar.ai.filter",
        "trendradar.storage",
    ):
        stub_module(name)

    context = load_real("trendradar.context", "trendradar/context.py")
    return SimpleNamespace(
        context=context,
        generator=generator,
        dashboard=dashboard,
        daily_v2=daily_v2,
        newsletter=newsletter,
    )
