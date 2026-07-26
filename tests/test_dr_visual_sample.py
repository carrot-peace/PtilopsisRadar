# coding=utf-8
"""Reproducible DR visual sample generator tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "render_dr_visual_sample.py"


class TestDRVisualSample(unittest.TestCase):
    def test_generator_writes_deterministic_reader_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            command = [
                sys.executable,
                str(SCRIPT),
                "--output-dir",
                str(output_dir),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            expected = (
                output_dir / "dr-v2-2026-07-13-sample.html",
                output_dir / "dr-v2-2026-07-13-mobile.html",
                output_dir / "dr-v2-2026-07-13-telegram.txt",
            )
            first_render = tuple(path.read_bytes() for path in expected)

            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(
                tuple(path.read_bytes() for path in expected),
                first_render,
            )
            self.assertIn(b"2026-07-13", first_render[0])
            self.assertIn(b"390px", first_render[1])
            self.assertTrue(first_render[2].strip())


if __name__ == "__main__":
    unittest.main()
