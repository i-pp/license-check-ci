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

# Added 2026-11-12: latest release verification candidate.

"""Run a real synthetic zipapp through the composite action's bootstrap."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipapp

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bootstrap", ROOT / "tools/latest_checker.py"
)
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class IntegrationTests(unittest.TestCase):
    def run_zipapp(self, report_status="PASS", exit_code=0, relative=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src"
            source.mkdir()
            (source / "__main__.py").write_text(
                """import argparse, json, os
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--root'); p.add_argument('--policy'); p.add_argument('--report')
a = p.parse_args()
assert Path(a.root).is_absolute()
assert a.root.endswith("root with spaces;$(not-a-command)")
assert a.policy == "policy with spaces.json"
assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ
Path(a.report).write_text(json.dumps({'schema': 1, 'status': %r}))
raise SystemExit(%d)
"""
                % (report_status, exit_code)
            )
            archive = root / "checker.pyz"
            zipapp.create_archive(source, archive)
            raw = archive.read_bytes()
            tag = "v0.1.1"
            url = b.REPO + "/releases/download/" + tag + "/" + b.ASSET
            metadata = {
                "id": 1,
                "draft": False,
                "prerelease": False,
                "tag_name": tag,
                "html_url": b.REPO + "/releases/tag/" + tag,
                "assets": [
                    {
                        "id": 2,
                        "name": b.ASSET,
                        "state": "uploaded",
                        "size": len(raw),
                        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                        "browser_download_url": url,
                    }
                ],
            }
            calls = []

            def fetch(url, limit, token=None):
                calls.append((url, token))
                return json.dumps(metadata).encode() if url == b.API else raw

            with patch.dict(
                os.environ,
                {
                    "GH_TOKEN": "synthetic-token",
                    "GITHUB_TOKEN": "other-token",
                    "GITHUB_WORKSPACE": str(root),
                },
            ):
                b.execute(
                    (
                        Path("root with spaces;$(not-a-command)")
                        if relative
                        else root / "root with spaces;$(not-a-command)"
                    ),
                    "policy with spaces.json",
                    fetch,
                )
            self.assertEqual(calls, [(b.API, "synthetic-token"), (url, None)])

    def test_real_zipapp_pass_and_argv_and_credentials(self):
        self.run_zipapp()

    def test_real_zipapp_relative_checkout(self):
        self.run_zipapp(relative=True)

    def test_real_zipapp_nonzero_with_pass_report(self):
        with self.assertRaises(ValueError):
            self.run_zipapp(exit_code=1)

    def test_real_zipapp_incomplete_with_zero_exit(self):
        with self.assertRaises(ValueError):
            self.run_zipapp(report_status="INCOMPLETE")

    def test_action_contract(self):
        # No executable expression interpolation; inputs travel through quoted env.
        action = (ROOT / "action.yml").read_text()
        script = action.split("      run: |\n", 1)[1]
        self.assertNotIn("${{", script)
        self.assertIn("${{ github.action_path }}", action)
        self.assertIn('"$LICENSE_ACTION_PATH/tools/latest_checker.py"', script)
        self.assertIn('--root "$LICENSE_ROOT" --policy "$LICENSE_POLICY"', script)
        self.assertNotIn("permissions:", action)
        self.assertNotIn("curl ", action)


if __name__ == "__main__":
    unittest.main()
