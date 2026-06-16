# coding=utf-8

import sys
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


def test_telegram_test_notification_path_fails_closed(monkeypatch, capsys):
    calls = []
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
    assert ok is False
    assert calls == []
    assert "Legacy Push has been removed from runtime" in out
    assert "Use CR-New canary / CR dry-run Telegram sink instead" in out
    assert "Telegram 通知连通性测试" not in out
    assert "测试成功" not in out


def test_non_telegram_test_notification_path_no_longer_advertised(monkeypatch, capsys):
    monkeypatch.setattr(main, "AppContext", FakeAppContext)

    ok = main._run_test_notification({"SLACK_WEBHOOK_URL": "https://example.test/slack"})

    out = capsys.readouterr().out
    assert ok is False
    assert "Legacy Push has been removed from runtime" in out
    assert "可用渠道" not in out
    assert "测试成功" not in out
