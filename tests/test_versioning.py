# coding=utf-8
"""Tests for PtilopsisRadar product version parsing."""

import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.versioning import compare_version_tuple, parse_version_tuple


class TestVersionParsing(unittest.TestCase):
    def test_plain_semver(self):
        self.assertEqual(parse_version_tuple("0.1.0"), (0, 1, 0))

    def test_prefixed_semver(self):
        self.assertEqual(parse_version_tuple("v0.1.0"), (0, 1, 0))

    def test_suffix_display_version(self):
        self.assertEqual(parse_version_tuple("0.1.0-mcp"), (0, 1, 0))

    def test_existing_upstream_style_version(self):
        self.assertEqual(parse_version_tuple("6.9.1"), (6, 9, 1))

    def test_invalid_version_falls_back_to_zero(self):
        self.assertEqual(parse_version_tuple("not-a-version"), (0, 0, 0))

    def test_suffix_is_ignored_for_ordering(self):
        self.assertEqual(compare_version_tuple("0.1.0-mcp", "0.1.0"), 0)

    def test_numeric_ordering(self):
        self.assertEqual(compare_version_tuple("0.1.0", "0.2.0"), -1)
        self.assertEqual(compare_version_tuple("0.2.0", "0.1.0-mcp"), 1)


if __name__ == "__main__":
    unittest.main()
