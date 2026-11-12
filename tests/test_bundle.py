# KISS Open License Version 1.0 (KOL-v1)
#
# SPDX-FileCopyrightText: 2026 I-plusplus Inc.
# SPDX-License-Identifier: LicenseRef-KOL-v1
#
# Copyright remains with its respective holders; original copyright and attribution notices must be preserved.
# Contributors may add copyright notices for their own original modifications.
# Distributed modifications must be identified as required by Section 4(c) of KOL-v1.
#
# Use, modification, distribution, and incorporation into commercial or proprietary software are permitted
# without license fees or source disclosure, subject to all terms of the complete KOL-v1 license.
#
# Contributors grant the patent permissions stated in KOL-v1. Outputs are not covered merely because a
# KOL-licensed tool produced them; embedded licensed material remains subject to applicable license terms.
#
# THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OR LIABILITY TO THE EXTENT PERMITTED BY APPLICABLE LAW.
#
# This header is a summary, not a separate license or an amendment to KOL-v1.
# All terms and conditions of KOL-v1 apply. See the accompanying LICENSE file for the complete license text.

"""Verify reproducibility and the execution contract of the distribution bundle."""

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BundleTests(unittest.TestCase):
    """Build outside the repository; generated files are never tracked."""

    def test_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = [Path(directory) / "first.pyz", Path(directory) / "second.pyz"]
            for output in outputs:
                subprocess.run(
                    [
                        "python3",
                        "-B",
                        str(ROOT / "tools/build_bundle.py"),
                        "--output",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                )
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            with zipfile.ZipFile(outputs[0]) as archive:
                self.assertEqual(
                    set(archive.namelist()), {"__main__.py", "LICENSE", "NOTICE"}
                )
                self.assertEqual(
                    archive.read("LICENSE"), (ROOT / "LICENSE").read_bytes()
                )
                self.assertNotIn(str(ROOT).encode(), archive.read("__main__.py"))
            result = subprocess.run(
                ["python3", "-I", "-B", str(outputs[0]), "--help"], capture_output=True
            )
            self.assertEqual(result.returncode, 0)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.pyz"
            output.write_bytes(b"keep")
            result = subprocess.run(
                [
                    "python3",
                    "-B",
                    str(ROOT / "tools/build_bundle.py"),
                    "--output",
                    str(output),
                ],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
