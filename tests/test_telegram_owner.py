# coding=utf-8
"""Tests for deployment Telegram owner resolution."""

import unittest

from trendradar.deployment.telegram_owner import resolve_telegram_owner_chat_ids


class TestTelegramOwnerResolution(unittest.TestCase):
    def test_explicit_owner_ids_are_trimmed_and_deduplicated(self):
        self.assertEqual(
            resolve_telegram_owner_chat_ids(
                {"TELEGRAM_OWNER_CHAT_IDS": " 111,222,111, "}
            ),
            ["111", "222"],
        )

    def test_legacy_single_chat_id_is_not_command_authority(self):
        self.assertEqual(
            resolve_telegram_owner_chat_ids({"TELEGRAM_CHAT_ID": "-100123456789"}),
            [],
        )

    def test_legacy_single_chat_id_does_not_merge_with_explicit_owners(self):
        self.assertEqual(
            resolve_telegram_owner_chat_ids(
                {
                    "TELEGRAM_CHAT_ID": "111;222",
                    "TELEGRAM_OWNER_CHAT_IDS": "222,333",
                }
            ),
            ["222", "333"],
        )

    def test_missing_owner_configuration_is_empty(self):
        self.assertEqual(resolve_telegram_owner_chat_ids({}), [])


if __name__ == "__main__":
    unittest.main()
