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

"""Independent positive, malformed-policy and filesystem boundary fixtures."""

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src/license_check.py"
SPEC = importlib.util.spec_from_file_location("license_check", SOURCE)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class CheckerTests(unittest.TestCase):
    """Use invented evidence rather than treating a real license as a test oracle."""

    def setUp(self):
        """Prepare a small tracked repository with explicit license evidence."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.license = (
            "This fixture grants imaginary testing permissions only. " * 8
        ).encode()
        self.policy = {
            "schema": 1,
            "licenses": {
                "Test-License": {
                    "path": "LICENSE",
                    "sha256": hashlib.sha256(self.license).hexdigest(),
                }
            },
            "notice": {"path": "NOTICE", "required_text": ["Example Authors"]},
            "rules": [
                {
                    "paths": ["*"],
                    "kind": "first_party",
                    "license": "Test-License",
                    "header": "root",
                }
            ],
        }
        self.write("LICENSE", self.license)
        self.write(
            "NOTICE", "Copyright Example Authors. Fixture only, not legal terms."
        )
        self.write(
            "main.py", "# SPDX-License-Identifier: Test-License\nprint('example')\n"
        )
        self.git("-c", "init.templateDir=", "init", "-q")
        self.save()
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "fixture",
        )

    def git(self, *args):
        """Execute Git against the fixture only."""
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True
        )

    def write(self, name, data):
        """Write fixture bytes without changing the implementation."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)

    def save(self):
        """Persist policy and stage the complete fixture inventory."""
        self.write(".license-policy.json", json.dumps(self.policy))
        self.git("add", ".")

    def inspect(self):
        """Inspect the fixture with the production entry point."""
        return checker.inspect(self.root, ".license-policy.json")

    def reserved_fixture(self):
        """Declare synthetic retained rights without copying real corporate assets."""
        self.write("logo.bin", b"synthetic-logo")
        self.write(
            "RIGHTS", "Example Studio retains all rights. No OSS permission is granted."
        )
        self.policy["rules"][0]["paths"] = [
            "LICENSE",
            "NOTICE",
            "main.py",
            "RIGHTS",
            ".license-policy.json",
        ]
        rule = {
            "paths": ["logo.bin"],
            "kind": "rights_reserved",
            "owner": "Example Studio",
            "reason": "Synthetic brand asset",
            "evidence": "RIGHTS",
            "required_text": ["retains all rights", "No OSS permission"],
        }
        self.policy["rules"].append(rule)
        return rule

    def test_reserved_rights_pass_without_oss_grant(self):
        self.reserved_fixture()
        self.save()
        report = self.inspect()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["counts"]["rights_reserved"], 1)
        entry = report["rights_reserved_no_oss_grant"][0]
        self.assertFalse(entry["license_grant"])
        self.assertFalse(entry["oss_permission"])
        self.assertEqual(entry["path"], "logo.bin")

    def test_reserved_rights_required_fields(self):
        rule = self.reserved_fixture()
        for field in ("owner", "reason", "evidence", "required_text"):
            with self.subTest(field=field):
                value = rule.pop(field)
                self.save()
                with self.assertRaises(ValueError):
                    self.inspect()
                rule[field] = value

    def test_reserved_rights_invalid_text(self):
        rule = self.reserved_fixture()
        for field in ("owner", "reason"):
            original = rule[field]
            for value in (None, 3, "", "   ", "x" * 2049):
                with self.subTest(field=field, value=value):
                    rule[field] = value
                    self.save()
                    with self.assertRaises(ValueError):
                        self.inspect()
            rule[field] = original

    def test_reserved_rights_invalid_markers(self):
        rule = self.reserved_fixture()
        for value in (None, "text", [], [""], [4], ["missing clause"]):
            with self.subTest(value=value):
                rule["required_text"] = value
                self.save()
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_reserved_rights_evidence_missing(self):
        rule = self.reserved_fixture()
        rule["evidence"] = "missing.txt"
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_reserved_rights_cannot_claim_license(self):
        rule = self.reserved_fixture()
        rule["license"] = "Test-License"
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_reserved_rights_unknown_exception_stays_incomplete(self):
        self.reserved_fixture()
        self.write("unknown.bin", b"synthetic-unknown")
        self.policy["rules"].append(
            {
                "paths": ["unknown.bin"],
                "kind": "exception",
                "evidence": "RIGHTS",
                "owner": "Unknown",
                "reason": "Await rights evidence",
            }
        )
        self.save()
        self.assertEqual(self.inspect()["status"], "INCOMPLETE")
        self.assertEqual(
            checker.main(
                ["--root", str(self.root), "--policy", ".license-policy.json"]
            ),
            1,
        )

    def test_valid(self):
        self.assertEqual(self.inspect()["status"], "PASS")
        self.assertEqual(self.inspect()["tracked_files"], 4)

    def test_unknown_schema(self):
        self.policy["schema"] = 2
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_boolean_schema(self):
        self.policy["schema"] = True
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_unknown_key(self):
        self.policy["execute"] = "bad"
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_duplicate_key(self):
        self.write(".license-policy.json", '{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):
            self.inspect()

    def test_unclassified(self):
        self.policy["rules"][0]["paths"] = ["LICENSE", "NOTICE", ".license-policy.json"]
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_ambiguous(self):
        self.policy["rules"].append(dict(self.policy["rules"][0]))
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_stale_rule(self):
        self.policy["rules"][0]["paths"].append("missing/*")
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_unknown_license(self):
        self.policy["rules"][0]["license"] = "Other-License"
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_missing_license(self):
        (self.root / "LICENSE").unlink()
        with self.assertRaises(OSError):
            self.inspect()

    def test_wrong_digest(self):
        self.write("LICENSE", self.license + b"changed")
        with self.assertRaises(ValueError):
            self.inspect()

    def test_placeholder(self):
        data = b"TODO " * 100
        self.write("LICENSE", data)
        self.policy["licenses"]["Test-License"]["sha256"] = hashlib.sha256(
            data
        ).hexdigest()
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_pending_is_not_license(self):
        data = b"License selection pending. This is not a license grant. " * 8
        self.write("LICENSE", data)
        self.policy["licenses"]["Test-License"]["sha256"] = hashlib.sha256(
            data
        ).hexdigest()
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_invalid_license_type(self):
        self.policy["rules"][0]["license"] = []
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_canonical_kol_is_accepted(self):
        data = (SOURCE.parents[1] / "LICENSE").read_bytes()
        self.write("LICENSE", data)
        self.policy["licenses"]["Test-License"]["sha256"] = hashlib.sha256(
            data
        ).hexdigest()
        self.save()
        self.assertEqual(self.inspect()["status"], "PASS")

    def test_notice_missing_attribution(self):
        self.write("NOTICE", "Different authors and attribution text for this fixture.")
        with self.assertRaises(ValueError):
            self.inspect()

    def test_no_notice_required(self):
        self.policy["notice"] = None
        self.save()
        self.assertEqual(self.inspect()["status"], "PASS")

    def test_absolute_path(self):
        self.policy["licenses"]["Test-License"]["path"] = "/etc/passwd"
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_parent_escape(self):
        self.policy["rules"][0]["paths"] = ["../*"]
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_tracked_symlink(self):
        (self.root / "linked").symlink_to("LICENSE")
        self.save()
        with self.assertRaises(ValueError):
            self.inspect()

    def test_replaced_file_symlink(self):
        (self.root / "main.py").unlink()
        (self.root / "main.py").symlink_to("LICENSE")
        with self.assertRaises(OSError):
            self.inspect()

    def test_replaced_file_fifo(self):
        (self.root / "main.py").unlink()
        os.mkfifo(self.root / "main.py")
        result = subprocess.run(
            [
                "python3",
                "-I",
                "-B",
                str(SOURCE),
                "--root",
                str(self.root),
                "--policy",
                ".license-policy.json",
            ],
            capture_output=True,
            timeout=3,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_dirty_marker(self):
        self.assertFalse(self.inspect()["tracked_worktree_dirty"])
        self.write("main.py", "# changed")
        self.assertTrue(self.inspect()["tracked_worktree_dirty"])

    def test_directory_symlink(self):
        self.write("dir/file", "data")
        self.save()
        (self.root / "dir/file").unlink()
        (self.root / "dir").rmdir()
        (self.root / "dir").symlink_to(".")
        with self.assertRaises(OSError):
            self.inspect()

    def test_empty_inventory(self):
        self.git("rm", "-r", "--cached", ".")
        with self.assertRaises(ValueError):
            self.inspect()

    def split_main(self, rule):
        """Assign one file an explicit alternative category."""
        self.policy["rules"][0]["paths"] = [
            "LICENSE",
            "NOTICE",
            ".license-policy.json",
            "evidence.md",
        ]
        self.write(
            "evidence.md",
            "Reviewed external origin and license evidence for this fixture.",
        )
        self.policy["rules"].append({"paths": ["main.py"], **rule})
        self.save()

    def test_spdx_present(self):
        self.split_main(
            {"kind": "first_party", "license": "Test-License", "header": "spdx"}
        )
        self.assertEqual(self.inspect()["status"], "PASS")

    def test_utf8_header_boundary(self):
        self.test_header_marker_present()
        prefix = b"# SPDX-License-Identifier: Test-License\n"
        for width in (2, 3, 4):
            char = {2: "\u00e9", 3: "\u3042", 4: "\U0001f600"}[width]
            for split in range(1, width):
                data = prefix + b"x" * (8192 - split - len(prefix))
                self.write("main.py", data + char.encode() + b"\n")
                self.assertEqual(self.inspect()["status"], "PASS")

    def test_invalid_utf8_after_header_limit(self):
        self.test_spdx_present()
        self.write(
            "main.py",
            b"# SPDX-License-Identifier: Test-License\n" + b"x" * 8192 + b"\xff",
        )
        with self.assertRaises(UnicodeDecodeError):
            self.inspect()

    def test_incomplete_utf8_at_eof(self):
        self.test_spdx_present()
        self.write(
            "main.py", b"# SPDX-License-Identifier: Test-License\n" + b"\xe3\x81"
        )
        with self.assertRaises(UnicodeDecodeError):
            self.inspect()

    def test_header_beyond_byte_limit_rejected(self):
        self.test_spdx_present()
        self.write(
            "main.py",
            ("\u3042" * 2800 + "\n# SPDX-License-Identifier: Test-License\n").encode(),
        )
        with self.assertRaises(ValueError):
            self.inspect()

    def test_spdx_missing(self):
        self.test_spdx_present()
        self.write("main.py", "print('no header')")
        with self.assertRaises(ValueError):
            self.inspect()

    def test_third_party(self):
        self.split_main(
            {
                "kind": "third_party",
                "license": "Test-License",
                "origin": "https://example.invalid/source",
                "evidence": "evidence.md",
            }
        )
        self.assertEqual(self.inspect()["counts"]["third_party"], 1)

    def test_third_party_evidence_missing(self):
        self.test_third_party()
        (self.root / "evidence.md").unlink()
        with self.assertRaises(OSError):
            self.inspect()

    def test_exception_not_green(self):
        self.split_main(
            {
                "kind": "exception",
                "reason": "Ownership review pending",
                "owner": "Maintainer",
                "evidence": "evidence.md",
            }
        )
        report = self.inspect()
        self.assertEqual(report["status"], "INCOMPLETE")
        self.assertEqual(len(report["exceptions"]), 1)
        self.assertEqual(
            checker.main(
                ["--root", str(self.root), "--policy", ".license-policy.json"]
            ),
            1,
        )

    def test_header_marker_present(self):
        self.split_main(
            {
                "kind": "first_party",
                "license": "Test-License",
                "header": "spdx",
                "header_markers": ["SPDX-License-Identifier: Test-License"],
            }
        )
        self.assertEqual(self.inspect()["status"], "PASS")

    def test_header_marker_missing(self):
        self.split_main(
            {
                "kind": "first_party",
                "license": "Test-License",
                "header": "spdx",
                "header_markers": ["Copyright Absent Author"],
            }
        )
        with self.assertRaises(ValueError):
            self.inspect()

    def test_exact_sidecar(self):
        self.split_main(
            {
                "kind": "first_party",
                "license": "Test-License",
                "header": "root",
                "evidence": "evidence.md",
            }
        )
        self.write("evidence.md", "Test-License applies to this exact fixture source.")
        self.assertEqual(self.inspect()["status"], "PASS")

    def test_sidecar_missing_reference(self):
        self.split_main(
            {
                "kind": "first_party",
                "license": "Test-License",
                "header": "root",
                "evidence": "evidence.md",
            }
        )
        with self.assertRaises(ValueError):
            self.inspect()

    def metadata_fixture(self):
        self.split_main(
            {
                "kind": "generated_metadata",
                "evidence": "evidence.md",
                "reason": "Generated dependency inventory, not bundled source",
                "origin": "Fixture package manager",
                "format": "json",
            }
        )
        self.policy["rules"][-1]["paths"] = ["package-lock.json"]
        (self.root / "main.py").unlink()
        self.write("package-lock.json", '{"lockfileVersion": 3}')
        self.save()

    def test_generated_metadata(self):
        self.metadata_fixture()
        report = self.inspect()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["metadata_not_license_assessed"]), 1)

    def test_metadata_cannot_be_source(self):
        self.split_main(
            {
                "kind": "generated_metadata",
                "evidence": "evidence.md",
                "reason": "Not valid metadata",
                "origin": "Fixture",
                "format": "json",
            }
        )
        with self.assertRaises(ValueError):
            self.inspect()

    def test_metadata_empty(self):
        self.metadata_fixture()
        self.write("package-lock.json", "{}")
        with self.assertRaises(ValueError):
            self.inspect()

    def test_report_no_overwrite(self):
        report = self.root / "result.json"
        report.write_text("keep")
        self.assertEqual(
            checker.main(
                [
                    "--root",
                    str(self.root),
                    "--policy",
                    ".license-policy.json",
                    "--report",
                    str(report),
                ]
            ),
            1,
        )
        self.assertEqual(report.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
