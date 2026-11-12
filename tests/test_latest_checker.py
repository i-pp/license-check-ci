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

"""Offline adversarial tests for latest-release bootstrap contracts."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, MagicMock
from urllib.request import Request
import importlib.util

MODULE = Path(__file__).resolve().parents[1] / "tools" / "latest_checker.py"
SPEC = importlib.util.spec_from_file_location("latest_checker", MODULE)
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)

RAW = b"fake executable bytes"


def metadata():
    return {
        "id": 1,
        "draft": False,
        "prerelease": False,
        "tag_name": "v0.1.1",
        "html_url": b.REPO + "/releases/tag/v0.1.1",
        "assets": [
            {
                "id": 2,
                "name": b.ASSET,
                "state": "uploaded",
                "size": len(RAW),
                "digest": "sha256:" + hashlib.sha256(RAW).hexdigest(),
                "browser_download_url": b.REPO + "/releases/download/v0.1.1/" + b.ASSET,
            }
        ],
    }


class Tests(unittest.TestCase):
    def test_metadata_rejections(self):
        cases = [
            ("draft", True),
            ("prerelease", True),
            ("draft", None),
            ("id", True),
            ("id", -1),
            ("tag_name", "../other"),
            ("tag_name", "v1.2.3-rc1"),
            ("html_url", "https://github.com/attacker/repo/releases/tag/v0.1.1"),
            ("assets", []),
            ("assets", [None]),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                data = metadata()
                data[key] = value
                with self.assertRaises(ValueError):
                    b.resolve(data)

    def test_asset_rejections(self):
        cases = [
            ("id", True),
            ("id", 0),
            ("name", "license-check-0.1.1.pyz"),
            ("state", "new"),
            ("size", 0),
            ("size", b.LIMIT + 1),
            ("size", True),
            ("digest", None),
            ("digest", "sha512:" + "a" * 64),
            ("browser_download_url", b.REPO + "/releases/download/v0.1.0/" + b.ASSET),
        ]
        for key, value in cases:
            with self.subTest(key=key):
                data = metadata()
                data["assets"][0][key] = value
                with self.assertRaises(ValueError):
                    b.resolve(data)

    def test_duplicate_asset(self):
        data = metadata()
        data["assets"] *= 2
        with self.assertRaises(ValueError):
            b.resolve(data)

    def test_duplicate_json(self):
        with self.assertRaises(ValueError):
            b.parse_json('{"id":1,"id":2}')

    def test_redirect_rejections(self):
        handler = b.Redirects()
        for request, url in [
            (Request(b.API), "https://api.github.com/else"),
            (
                Request(b.REPO, headers={"Authorization": "Bearer secret"}),
                "https://release-assets.githubusercontent.com/x",
            ),
            (Request(b.REPO), "http://github.com/x"),
            (Request(b.REPO), "https://evil.example/x"),
            (Request(b.REPO), "https://token@github.com/x"),
            (Request(b.REPO), "https://github.com:444/x"),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "", {}, url)

    def test_safe_redirect_has_no_auth(self):
        request = b.Redirects().redirect_request(
            Request(b.REPO),
            None,
            302,
            "",
            {},
            "https://release-assets.githubusercontent.com/x?q=signed",
        )
        self.assertFalse(request.has_header("Authorization"))

    def run_case(self, data=None, raw=RAW, code=0, report=None, error=None):
        calls = []

        def fetch(url, limit, token=None):
            calls.append((url, token))
            if error:
                raise error
            return json.dumps(data or metadata()).encode() if url == b.API else raw

        def run(argv, **kwargs):
            self.assertNotIn("GH_TOKEN", kwargs["env"])
            self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
            if report is not False:
                Path(argv[-1]).write_text(
                    json.dumps(
                        report
                        if report is not None
                        else {"schema": 1, "status": "PASS"}
                    )
                )
            return subprocess.CompletedProcess(argv, code)

        with patch.dict(os.environ, {"GH_TOKEN": "secret", "GITHUB_TOKEN": "secret2"}):
            b.execute(Path("."), ".github/license-policy.json", fetch, run)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], (b.API, "secret"))
        self.assertIsNone(calls[1][1])

    def test_success_once_and_token_separation(self):
        self.run_case()

    def test_hash_mismatch(self):
        with self.assertRaises(ValueError):
            self.run_case(raw=b"X" * len(RAW))

    def test_size_mismatch(self):
        with self.assertRaises(ValueError):
            self.run_case(raw=b"X")

    def test_exit_nonzero_even_pass_report(self):
        with self.assertRaises(ValueError):
            self.run_case(code=1)

    def test_no_report(self):
        with self.assertRaises(ValueError):
            self.run_case(report=False)

    def test_report_rejections(self):
        for report in [
            {"schema": 1, "status": "FAIL"},
            {"schema": 1, "status": "INCOMPLETE"},
            {"schema": True, "status": "PASS"},
            {"schema": 2, "status": "PASS"},
            {},
            [],
        ]:
            with self.subTest(report=report), self.assertRaises(ValueError):
                self.run_case(report=report)

    def test_network_fail_closed(self):
        for error in [TimeoutError(), OSError("rate limit/network")]:
            with self.subTest(error=error), self.assertRaises(type(error)):
                self.run_case(error=error)

    def test_http_limits_and_status(self):
        for status, body in [(429, b""), (200, b"12345")]:
            response = MagicMock()
            response.__enter__.return_value = response
            response.status = status
            response.read.return_value = body
            opener = MagicMock()
            opener.open.return_value = response
            with patch.object(b.urllib.request, "build_opener", return_value=opener):
                with self.subTest(status=status), self.assertRaises(ValueError):
                    b.fetch(b.API, 4)

    def test_asset_token_rejected(self):
        with self.assertRaises(ValueError):
            b.fetch(b.REPO, 1, "secret")


class RootInputTests(unittest.TestCase):
    def test_relative_checkout_uses_workspace(self):
        self.assertEqual(
            b.normalize_root(Path("source"), "/workspace"), Path("/workspace/source")
        )

    def test_dot_uses_workspace(self):
        self.assertEqual(b.normalize_root(Path("."), "/workspace"), Path("/workspace"))

    def test_absolute_root_is_unchanged(self):
        self.assertEqual(
            b.normalize_root(Path("/source"), "/workspace"), Path("/source")
        )

    def test_relative_without_workspace_uses_cwd(self):
        self.assertEqual(b.normalize_root(Path("source")), Path.cwd() / "source")

    def test_relative_workspace_is_rejected(self):
        with self.assertRaises(ValueError):
            b.normalize_root(Path("source"), "relative-workspace")


if __name__ == "__main__":
    unittest.main()
