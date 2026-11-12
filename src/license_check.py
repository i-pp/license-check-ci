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

"""Check declared license evidence without determining legal ownership."""

import argparse
import codecs
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

VERSION = "0.1.1"
LIMIT = 16 * 1024 * 1024
PLACEHOLDER = re.compile(
    r"\b(TODO|TBD|PLACEHOLDER|INSERT LICENSE|YOUR NAME|LICENSE SELECTION PENDING|NOT A LICENSE GRANT)\b",
    re.I,
)


def require(condition, message):
    """Reject an invalid contract with a bounded, non-secret diagnostic."""
    if not condition:
        raise ValueError(message)


def relative_path(value, pattern=False):
    """Require a normalized repository-relative POSIX path."""
    require(isinstance(value, str) and 0 < len(value) <= 1024, "Invalid path")
    parts = value.split("/")
    require(not value.startswith("/") and "\\" not in value, "Unsafe path")
    require(all(part not in ("", ".", "..") for part in parts), "Unsafe path component")
    require(not any(ord(char) < 32 for char in value), "Control character in path")
    require(parts[0] != ".git", "Git metadata is outside inspection scope")
    if not pattern:
        require(not any(char in value for char in "*?[]"), "Glob in literal path")
    return value


def read_file(root, name):
    """Read through no-follow directory descriptors and detect replacement."""
    relative_path(name)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(name).parts
        for part in parts[:-1]:
            next_dir = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = next_dir
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            before = os.fstat(descriptor)
            require(
                stat.S_ISREG(before.st_mode) and before.st_size <= LIMIT,
                "Not a bounded regular file",
            )
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                data = stream.read(LIMIT + 1)
            after = os.fstat(descriptor)
            current = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)

            def identity(item):
                """Compare stable metadata around each read."""
                return (
                    item.st_dev,
                    item.st_ino,
                    item.st_size,
                    item.st_mtime_ns,
                    item.st_ctime_ns,
                )

            require(
                len(data) <= LIMIT
                and identity(before) == identity(after) == identity(current),
                "File changed during inspection",
            )
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def git(root, *arguments):
    """Read Git metadata without executing hooks or repository programs."""
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(root),
            *arguments,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    require(len(result.stdout) <= LIMIT, "Git inventory exceeds limit")
    return result.stdout


def inventory(root):
    """List indexed regular files; reject conflicts, links and submodules."""
    files = []
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, _, stage = metadata.split()
        require(
            mode in (b"100644", b"100755") and stage == b"0",
            "Unsupported Git entry: symlink, submodule or unmerged file",
        )
        files.append(relative_path(name.decode("utf-8")))
    require(
        0 < len(files) <= 20000 and len(set(files)) == len(files),
        "Empty, duplicate or oversized inventory",
    )
    return sorted(files)


def strict_object(pairs):
    """Reject duplicate JSON keys instead of accepting ambiguous policy."""
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate policy key")
        result[key] = value
    return result


def keys(value, required, optional=()):
    """Validate an exact schema object."""
    require(isinstance(value, dict), "Expected policy object")
    require(
        set(required) <= value.keys() <= set(required) | set(optional),
        "Missing or unknown policy field",
    )


def nonempty_text(value):
    """Validate bounded policy metadata, not legal truth."""
    require(
        isinstance(value, str) and 0 < len(value.strip()) <= 2048,
        "Missing or oversized policy text",
    )


def policy_from(data):
    """Parse the only supported schema; no includes or executable settings."""
    require(len(data) <= 1024 * 1024, "Policy exceeds limit")
    policy = json.loads(data, object_pairs_hook=strict_object)
    keys(policy, ("schema", "licenses", "notice", "rules"))
    require(
        type(policy["schema"]) is int and policy["schema"] == 1,
        "Unsupported policy schema",
    )
    require(
        isinstance(policy["licenses"], dict) and bool(policy["licenses"]),
        "No declared licenses",
    )
    for identifier, item in policy["licenses"].items():
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,99}", identifier),
            "Invalid license identifier",
        )
        keys(item, ("path", "sha256"))
        relative_path(item["path"])
        require(
            isinstance(item["sha256"], str)
            and re.fullmatch(r"[a-f0-9]{64}", item["sha256"]),
            "Invalid license digest",
        )
    if policy["notice"] is not None:
        keys(policy["notice"], ("path", "required_text"))
        relative_path(policy["notice"]["path"])
        require(
            isinstance(policy["notice"]["required_text"], list)
            and bool(policy["notice"]["required_text"]),
            "Empty NOTICE requirements",
        )
        for text in policy["notice"]["required_text"]:
            nonempty_text(text)
    require(
        isinstance(policy["rules"], list) and 0 < len(policy["rules"]) <= 1000,
        "No classification rules",
    )
    for rule in policy["rules"]:
        keys(
            rule,
            ("paths", "kind"),
            (
                "license",
                "header",
                "evidence",
                "origin",
                "reason",
                "owner",
                "header_markers",
                "format",
                "required_text",
            ),
        )
        require(
            isinstance(rule["paths"], list) and bool(rule["paths"]), "Empty rule paths"
        )
        for path in rule["paths"]:
            relative_path(path, pattern=True)
        kind = rule["kind"]
        require(
            kind
            in (
                "first_party",
                "third_party",
                "exception",
                "generated_metadata",
                "rights_reserved",
            ),
            "Unknown category",
        )
        if kind in ("first_party", "third_party"):
            require(
                isinstance(rule.get("license"), str)
                and rule["license"] in policy["licenses"],
                "Unknown license reference",
            )
        if kind == "first_party":
            keys(
                rule,
                ("paths", "kind", "license", "header"),
                ("evidence", "header_markers"),
            )
            if "evidence" in rule:
                relative_path(rule["evidence"])
            if "header_markers" in rule:
                require(
                    isinstance(rule["header_markers"], list)
                    and bool(rule["header_markers"]),
                    "Empty header markers",
                )
                for marker in rule["header_markers"]:
                    nonempty_text(marker)
            require(rule["header"] in ("spdx", "root"), "Unknown header policy")
        elif kind == "third_party":
            keys(rule, ("paths", "kind", "license", "evidence", "origin"))
            relative_path(rule["evidence"])
            nonempty_text(rule["origin"])
        elif kind == "generated_metadata":
            keys(rule, ("paths", "kind", "evidence", "reason", "origin", "format"))
            relative_path(rule["evidence"])
            nonempty_text(rule["reason"])
            nonempty_text(rule["origin"])
            require(rule["format"] in ("json", "toml"), "Unsupported metadata format")
        elif kind == "rights_reserved":
            keys(
                rule, ("paths", "kind", "evidence", "reason", "owner", "required_text")
            )
            relative_path(rule["evidence"])
            nonempty_text(rule["reason"])
            nonempty_text(rule["owner"])
            require(
                isinstance(rule["required_text"], list) and bool(rule["required_text"]),
                "Empty reserved-rights evidence markers",
            )
            for marker in rule["required_text"]:
                nonempty_text(marker)
        else:
            keys(rule, ("paths", "kind", "evidence", "reason", "owner"))
            relative_path(rule["evidence"])
            nonempty_text(rule["reason"])
            nonempty_text(rule["owner"])
    return policy


def document(root, files, name, minimum):
    """Require tracked, non-placeholder evidence of adequate size."""
    require(name in files, "Required evidence is not tracked")
    text = read_file(root, name).decode("utf-8")
    require(
        len(text.strip()) >= minimum and not PLACEHOLDER.search(text),
        "Missing, short or placeholder evidence",
    )
    return text


def header_text(data):
    """Validate all UTF-8, then inspect complete characters in the first 8 KiB."""
    data.decode("utf-8")
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    return decoder.decode(data[:8192], final=False)


def inspect(root, policy_name):
    """Inspect every indexed file and report declared evidence or explicit gaps."""
    files = inventory(root)
    require(policy_name in files, "Policy must be tracked")
    raw_policy = read_file(root, policy_name)
    policy = policy_from(raw_policy)
    for item in policy["licenses"].values():
        document(root, files, item["path"], 200)
        require(
            hashlib.sha256(read_file(root, item["path"])).hexdigest() == item["sha256"],
            "License digest mismatch",
        )
    notice = policy["notice"]
    if notice is not None:
        text = document(root, files, notice["path"], 30)
        require(
            all(marker in text for marker in notice["required_text"]),
            "NOTICE lacks required attribution text",
        )
    hits = [[0] * len(rule["paths"]) for rule in policy["rules"]]
    counts = {
        "first_party": 0,
        "third_party": 0,
        "exception": 0,
        "generated_metadata": 0,
        "rights_reserved": 0,
    }
    exceptions = []
    metadata = []
    reserved = []
    for name in files:
        data = read_file(root, name)
        matches = []
        for index, rule in enumerate(policy["rules"]):
            found = False
            for offset, pattern in enumerate(rule["paths"]):
                if fnmatch.fnmatchcase(name, pattern):
                    hits[index][offset] += 1
                    found = True
            if found:
                matches.append(rule)
        require(len(matches) == 1, f"Unclassified or ambiguous path: {name}")
        rule = matches[0]
        counts[rule["kind"]] += 1
        if rule["kind"] == "first_party" and rule["header"] == "spdx":
            header = header_text(data)
            marker = "SPDX-License-Identifier: " + rule["license"]
            require(
                any(
                    line.strip()
                    .removeprefix("# ")
                    .removeprefix("// ")
                    .removeprefix("* ")
                    .strip()
                    == marker
                    for line in header.splitlines()
                ),
                f"Missing SPDX header: {name}",
            )
        if rule["kind"] == "first_party" and "header_markers" in rule:
            header = header_text(data)
            require(
                all(marker in header for marker in rule["header_markers"]),
                f"Required header text missing: {name}",
            )
        if "evidence" in rule:
            evidence = document(root, files, rule["evidence"], 20)
            if rule["kind"] == "first_party":
                require(rule["license"] in evidence, "Evidence lacks license reference")
        if rule["kind"] == "rights_reserved":
            require(
                all(marker in evidence for marker in rule["required_text"]),
                "Reserved-rights evidence lacks required text",
            )
            reserved.append(
                {
                    "path": name,
                    "owner": rule["owner"],
                    "reason": rule["reason"],
                    "evidence": rule["evidence"],
                    "required_text": rule["required_text"],
                    "license_grant": False,
                    "oss_permission": False,
                }
            )
        if rule["kind"] == "generated_metadata":
            require(
                Path(name).suffix in (".json", ".lock", ".toml"),
                "Metadata must be JSON/TOML data",
            )
            parsed = (
                json.loads(data)
                if rule["format"] == "json"
                else tomllib.loads(data.decode("utf-8"))
            )
            require(
                isinstance(parsed, dict) and bool(parsed),
                "Empty or non-object metadata",
            )
            metadata.append(
                {
                    "path": name,
                    "reason": rule["reason"],
                    "origin": rule["origin"],
                    "evidence": rule["evidence"],
                }
            )
        if rule["kind"] == "exception":
            exceptions.append(
                {
                    "path": name,
                    "reason": rule["reason"],
                    "owner": rule["owner"],
                    "evidence": rule["evidence"],
                }
            )
    require(all(all(row) for row in hits), "Stale classification path or empty scope")
    require(
        counts["first_party"] + counts["third_party"] > 0,
        "No license-covered files inspected",
    )
    return {
        "schema": 1,
        "checker_version": VERSION,
        "status": "INCOMPLETE" if exceptions else "PASS",
        "commit": git(root, "rev-parse", "HEAD").decode().strip(),
        "tracked_worktree_dirty": bool(
            git(root, "diff-index", "--name-only", "HEAD", "--")
        ),
        "policy_sha256": hashlib.sha256(raw_policy).hexdigest(),
        "tracked_files": len(files),
        "counts": counts,
        "exceptions": exceptions,
        "metadata_not_license_assessed": metadata,
        "rights_reserved_no_oss_grant": reserved,
        "scope": "Declared evidence only; no ownership, legal compatibility or certification guarantee",
    }


def main(argv=None):
    """Run a bounded check; failures and explicit exceptions are nonzero."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        require(
            args.root.is_absolute() and not args.root.is_symlink(),
            "Unsafe repository root",
        )
        require(
            args.root.resolve() == args.root,
            "Root contains symlink or non-normalized component",
        )
        relative_path(args.policy)
        report = inspect(args.root, args.policy)
    except (
        ValueError,
        TypeError,
        OSError,
        UnicodeError,
        subprocess.SubprocessError,
    ) as error:
        report = {
            "schema": 1,
            "checker_version": VERSION,
            "status": "FAIL",
            "error": str(error)
            if isinstance(error, ValueError)
            else type(error).__name__,
        }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report:
        if args.report.absolute().resolve() != args.report.absolute():
            print("Unsafe report path", file=sys.stderr)
            return 1
        # Never overwrite an existing file or follow a link at the report destination.
        try:
            with args.report.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        except OSError:
            print("Cannot create report without overwriting", file=sys.stderr)
            return 1
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
