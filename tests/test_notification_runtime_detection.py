# coding=utf-8

import sys
import types
from types import SimpleNamespace

# Earlier-collected test modules install partial `trendradar` trees into
# sys.modules at import time: bare package stubs (via _bootstrap.load_all() /
# _stub_pkg) mixed with real submodules loaded by file path. Under full-suite
# collection order that leaves `trendradar` resolvable only as a stub (no real
# __path__ / __version__) and a few real submodules attached to it, so the
# `import trendradar.__main__` below fails (ModuleNotFoundError /
# "cannot import name '__version__'"). Drop the whole `trendradar` subtree so the
# import resolves cleanly and consistently against the real installed package.
for _stale in [
    _name
    for _name in list(sys.modules)
    if _name == "trendradar" or _name.startswith("trendradar.")
]:
    del sys.modules[_stale]

import trendradar.__main__ as main  # noqa: E402


class FakeAppContext:
    def __init__(self, config):
        self.config = config
        self.timezone = "Asia/Shanghai"

    def cleanup(self):
        pass

    def get_time(self):
        from datetime import datetime

        return datetime(2026, 6, 6, 12, 0, 0)

    def split_content(self, content, max_length=None):
        return [content]

    def format_date(self):
        return "2026-06-06"

    def format_time(self):
        return "120000"


def _analyzer_with_config(config):
    analyzer = main.NewsAnalyzer.__new__(main.NewsAnalyzer)
    analyzer.ctx = SimpleNamespace(config=config)
    return analyzer


def test_only_feishu_config_does_not_count_as_notification_configured():
    analyzer = _analyzer_with_config({"FEISHU_WEBHOOK_URL": "https://example.test/feishu"})

    assert analyzer._has_notification_configured() is False


def test_only_email_config_does_not_count_as_notification_configured():
    analyzer = _analyzer_with_config(
        {
            "EMAIL_FROM": "from@example.test",
            "EMAIL_PASSWORD": "secret",
            "EMAIL_TO": "to@example.test",
        }
    )

    assert analyzer._has_notification_configured() is False


def test_only_slack_config_does_not_count_as_notification_configured():
    analyzer = _analyzer_with_config({"SLACK_WEBHOOK_URL": "https://example.test/slack"})

    assert analyzer._has_notification_configured() is False


def test_valid_telegram_config_counts_as_notification_configured():
    analyzer = _analyzer_with_config(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "111",
        }
    )

    assert analyzer._has_notification_configured() is True


def test_telegram_test_notification_path_remains_available(monkeypatch, capsys):
    calls = []

    class FakeDispatcher:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs["config"]))

        def dispatch_all(self, **kwargs):
            calls.append(("dispatch", kwargs))
            return {"Telegram": True}

    notification_stub = types.ModuleType("trendradar.notification")
    notification_stub.NotificationDispatcher = FakeDispatcher

    monkeypatch.setitem(sys.modules, "trendradar.notification", notification_stub)
    monkeypatch.setattr(main, "AppContext", FakeAppContext)
    monkeypatch.setattr(main, "_create_test_html_file", lambda ctx: None)
    monkeypatch.setattr(main, "_build_test_report_data", lambda ctx: {"platform_stats": []})

    ok = main._run_test_notification(
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_ACCESS": {"receiver_chat_ids": ["111"]},
            "DISPLAY": {},
            "USE_PROXY": False,
        }
    )

    out = capsys.readouterr().out
    assert ok is True
    assert calls and calls[0][0] == "init"
    assert "Telegram 通知连通性测试" in out
    assert "Telegram: 测试成功" in out


def test_non_telegram_test_notification_path_no_longer_advertised(monkeypatch, capsys):
    class FakeDispatcher:
        def __init__(self, **kwargs):
            raise AssertionError("non-Telegram configs must not create a dispatcher")

    notification_stub = types.ModuleType("trendradar.notification")
    notification_stub.NotificationDispatcher = FakeDispatcher

    monkeypatch.setitem(sys.modules, "trendradar.notification", notification_stub)
    monkeypatch.setattr(main, "AppContext", FakeAppContext)

    ok = main._run_test_notification({"SLACK_WEBHOOK_URL": "https://example.test/slack"})

    out = capsys.readouterr().out
    assert ok is False
    assert "未配置 Telegram 通知" in out
    assert "非 Telegram 通知配置已不再作为运行时通知渠道" in out
    assert "已忽略旧通知配置: Slack" in out
    assert "可用渠道" not in out
    assert "测试成功" not in out
