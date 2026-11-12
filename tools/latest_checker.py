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

"""Resolve and verify one public release; API digest is integrity, not signature trust."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/i-pp/license-check-ci/releases/latest"
REPO = "https://github.com/i-pp/license-check-ci"
ASSET = "license-check.pyz"
LIMIT = 8 * 1024 * 1024


def require(condition, message):
    """Reject unsupported or incomplete evidence instead of falling back."""
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    """Reject duplicate JSON keys rather than accepting ambiguous metadata."""
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def safe_asset_url(url):
    """Allow only HTTPS GitHub release delivery hosts, without userinfo."""
    parsed = urllib.parse.urlsplit(url)
    require(
        parsed.scheme == "https"
        and parsed.hostname
        in {
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }
        and parsed.port in (None, 443)
        and not parsed.username
        and not parsed.password
        and not parsed.fragment,
        "Unsafe asset URL",
    )


class Redirects(urllib.request.HTTPRedirectHandler):
    """Never redirect an authenticated metadata request; assets carry no token."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        require(request.full_url != API, "Metadata redirect refused")
        require(
            not request.has_header("Authorization"), "Authenticated redirect refused"
        )
        safe_asset_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch(url, limit, token=None):
    """Bound the response; propagate network/rate-limit failures as CI failures."""
    headers = {
        "User-Agent": "license-check-bootstrap",
        "Accept": "application/vnd.github+json",
    }
    if token:
        require(url == API, "Token restricted to fixed metadata API")
        headers["Authorization"] = "Bearer " + token
    if url != API:
        safe_asset_url(url)
        headers["Accept"] = "application/octet-stream"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(Redirects()).open(request, timeout=30) as response:
        require(response.status == 200, "Unexpected HTTP status")
        raw = response.read(limit + 1)
    require(len(raw) <= limit, "Response too large")
    return raw


def resolve(metadata):
    """Validate one stable release and its uniquely named uploaded asset."""
    require(isinstance(metadata, dict), "Release must be an object")
    require(
        metadata.get("draft") is False and metadata.get("prerelease") is False,
        "Release must be stable and published",
    )
    release_id = metadata.get("id")
    require(type(release_id) is int and release_id > 0, "Invalid release ID")
    tag = metadata.get("tag_name")
    require(
        isinstance(tag, str) and re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+", tag),
        "Unsupported stable tag",
    )
    require(
        metadata.get("html_url") == REPO + "/releases/tag/" + tag,
        "Wrong release repository",
    )
    assets = metadata.get("assets")
    require(
        isinstance(assets, list) and all(isinstance(a, dict) for a in assets),
        "Invalid assets",
    )
    matches = [a for a in assets if a.get("name") == ASSET]
    require(len(matches) == 1, "Missing or duplicate exact asset")
    asset = matches[0]
    require(asset.get("state") == "uploaded", "Asset not uploaded")
    require(type(asset.get("id")) is int and asset["id"] > 0, "Invalid asset ID")
    require(
        type(asset.get("size")) is int and 0 < asset["size"] <= LIMIT,
        "Invalid asset size",
    )
    digest = asset.get("digest")
    require(
        isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest),
        "Missing SHA-256 digest",
    )
    url = REPO + "/releases/download/" + tag + "/" + ASSET
    require(
        asset.get("browser_download_url") == url, "Asset repository/tag/name mismatch"
    )
    return {
        "release_id": release_id,
        "tag": tag,
        "asset_id": asset["id"],
        "source": url,
        "digest": digest,
        "size": asset["size"],
    }


def normalize_root(root, workspace=None):
    """Anchor relative checkout paths without resolving symlinks."""
    if root.is_absolute():
        return root
    base = Path(workspace) if workspace else Path.cwd()
    require(base.is_absolute(), "Workspace must be absolute")
    return base / root


def execute(root, policy, fetcher=fetch, runner=subprocess.run):
    """Run exactly the bytes verified against the single metadata snapshot."""
    root = normalize_root(root, os.environ.get("GITHUB_WORKSPACE"))
    release = resolve(parse_json(fetcher(API, 1024 * 1024, os.environ.get("GH_TOKEN"))))
    raw = fetcher(release["source"], LIMIT)  # Deliberately no token argument.
    require(len(raw) == release["size"], "Asset size mismatch")
    require(
        hashlib.sha256(raw).hexdigest() == release["digest"][7:],
        "Asset digest mismatch",
    )
    print(json.dumps({"resolved_checker": release}), flush=True)
    with tempfile.TemporaryDirectory(prefix="license-check-") as temp:
        executable = Path(temp) / ASSET
        report = Path(temp) / "report.json"
        executable.write_bytes(raw)
        env = dict(os.environ)
        # No checkout credentials persisted; do not pass bootstrap auth to checker.
        for name in ("GH_TOKEN", "GITHUB_TOKEN"):
            env.pop(name, None)
        result = runner(
            [
                sys.executable,
                "-I",
                "-B",
                str(executable),
                "--root",
                str(root),
                "--policy",
                policy,
                "--report",
                str(report),
            ],
            env=env,
            timeout=180,
        )
        require(result.returncode == 0, "Checker failed")
        require(
            report.is_file() and report.stat().st_size <= LIMIT,
            "Missing or oversized report",
        )
        data = parse_json(report.read_bytes())
        require(
            isinstance(data, dict)
            and type(data.get("schema")) is int
            and data["schema"] == 1
            and data.get("status") == "PASS",
            "Checker report not PASS/schema 1",
        )
        print(json.dumps({"checker_report": data}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--policy", default=".github/license-policy.json")
    args = parser.parse_args()
    try:
        execute(args.root, args.policy)
    except Exception as exc:
        # Avoid leaking tokens or CDN query strings from transport exceptions.
        print("License bootstrap failed: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
