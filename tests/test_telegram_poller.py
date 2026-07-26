# coding=utf-8
"""Telegram subscription poller runner tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from trendradar.telegram.commands import SubscriptionCommandHandler
from trendradar.telegram.poller import (
    FatalPollingError,
    InstanceLock,
    TelegramPollingRunner,
    build_runner,
    run_poller,
)
from trendradar.telegram.recipients import resolve_owner_chat_ids
from trendradar.telegram.subscriptions import SubscriptionStore
from trendradar.telegram.transport import (
    TelegramHTTPResponse,
)


def _response(status: int = 200, result: object = None) -> TelegramHTTPResponse:
    return TelegramHTTPResponse(
        status,
        json.dumps({"ok": 200 <= status < 300, "result": result}),
    )


def _update(update_id: int, chat_id: int, text: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False},
            "text": text,
        },
    }


class FakeTransport:
    def __init__(self) -> None:
        self.webhook = _response(result={"url": ""})
        self.webhook_responses: list[
            TelegramHTTPResponse | BaseException
        ] = []
        self.webhook_calls = 0
        self.poll_responses: list[TelegramHTTPResponse | BaseException] = []
        self.sent: list[tuple[str, str]] = []
        self.send_response = _response(result={})
        self.offsets: list[int] = []

    def get_webhook_info(self):
        self.webhook_calls += 1
        if self.webhook_responses:
            value = self.webhook_responses.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        return self.webhook

    def get_updates(self, *, offset, timeout_seconds):
        del timeout_seconds
        self.offsets.append(offset)
        value = self.poll_responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def send_message(self, *, chat_id, text, **kwargs):
        del kwargs
        self.sent.append((chat_id, text))
        return self.send_response


class PollerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = SubscriptionStore(
            Path(self.directory.name) / "subscriptions.sqlite3"
        )
        self.transport = FakeTransport()
        self.handler = SubscriptionCommandHandler(
            self.store,
            frozenset({"1"}),
        )
        self.runner = TelegramPollingRunner(
            self.transport,  # type: ignore[arg-type]
            self.handler,
            self.store,
            sleep=lambda _seconds: None,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()


class TestPollingRunner(PollerFixture):
    def test_poll_once_replies_and_advances_offset(self) -> None:
        self.transport.poll_responses = [_response(result=[_update(4, 20, "/start")])]
        self.runner.poll_once()
        self.assertEqual(self.transport.offsets, [0])
        self.assertEqual(self.store.last_update_id(), 4)
        self.assertEqual(self.transport.sent[0][0], "20")

    def test_webhook_and_auth_conflicts_are_fatal(self) -> None:
        self.transport.webhook = _response(result={"url": "https://hook.test"})
        with self.assertRaises(FatalPollingError):
            self.runner.assert_no_webhook()
        for status in (401, 409):
            self.transport.poll_responses = [_response(status=status)]
            with self.assertRaises(FatalPollingError):
                self.runner.poll_once()

    def test_invalid_result_is_transient_failure(self) -> None:
        self.transport.poll_responses = [_response(result={})]
        with self.assertRaises(ConnectionError):
            self.runner.poll_once()

    def test_reply_failure_keeps_committed_offset_and_hides_token(self) -> None:
        self.transport.poll_responses = [_response(result=[_update(1, 1, "/token")])]
        self.transport.send_response = _response(status=500)
        with self.assertRaises(ConnectionError) as raised:
            self.runner.poll_once()
        self.assertEqual(self.store.last_update_id(), 1)
        self.assertNotIn("token_urlsafe", str(raised.exception))
        self.assertEqual(str(raised.exception), "command reply rejected with HTTP 500")

    def test_backoff_caps_at_thirty_seconds(self) -> None:
        sleeps: list[float] = []
        self.runner.sleep = sleeps.append
        self.transport.poll_responses = [
            ConnectionError("transient") for _ in range(7)
        ] + [_response(status=401)]
        with self.assertRaises(FatalPollingError):
            self.runner.run_forever()
        self.assertEqual(sleeps, [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0])

    def test_webhook_inspection_retries_before_polling(self) -> None:
        sleeps: list[float] = []
        self.runner.sleep = sleeps.append
        self.transport.webhook_responses = [
            ConnectionError("transient"),
            _response(status=500),
            _response(result={"url": ""}),
        ]
        self.transport.poll_responses = [_response(status=401)]

        with self.assertRaises(FatalPollingError):
            self.runner.run_forever()

        self.assertEqual(sleeps, [1.0, 2.0])
        self.assertEqual(self.transport.webhook_calls, 3)
        self.assertEqual(self.transport.offsets, [0])


class TestPollingConfiguration(unittest.TestCase):
    def test_disabled_poller_has_no_filesystem_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disabled.sqlite3"
            run_poller(
                {
                    "PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH": str(path),
                }
            )
            self.assertFalse(path.exists())

    def test_owner_authority_is_explicit_and_legacy_id_is_ignored(self) -> None:
        owners = resolve_owner_chat_ids(
            {
                "TELEGRAM_OWNER_CHAT_IDS": "1, 2,1",
                "TELEGRAM_CHAT_ID": "legacy-owner",
            }
        )
        self.assertEqual(owners, ("1", "2"))

    def test_build_runner_requires_owner_before_creating_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subscriptions.sqlite3"
            with self.assertRaises(ValueError):
                build_runner(
                    {
                        "TELEGRAM_BOT_TOKEN": "secret",
                        "PTILOPSIS_TELEGRAM_SUBSCRIPTION_DB_PATH": str(path),
                    }
                )
            self.assertFalse(path.exists())

    def test_single_instance_lock_is_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot.lock"
            with InstanceLock(path):
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
                with self.assertRaises(FatalPollingError):
                    with InstanceLock(path):
                        pass
