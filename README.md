<!--
KISS Open License Version 1.0 (KOL-v1)

SPDX-FileCopyrightText: 2026 I-plusplus Inc.
SPDX-License-Identifier: LicenseRef-KOL-v1

Copyright remains with its respective holders; original copyright and attribution notices must be preserved.
Contributors may add copyright notices for their own original modifications.
Distributed modifications must be identified as required by Section 4(c) of KOL-v1.

Use, modification, distribution, and incorporation into commercial or proprietary software are permitted
without license fees or source disclosure, subject to all terms of the complete KOL-v1 license.

Contributors grant the patent permissions stated in KOL-v1. Outputs are not covered merely because a
KOL-licensed tool produced them; embedded licensed material remains subject to applicable license terms.

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OR LIABILITY TO THE EXTENT PERMITTED BY APPLICABLE LAW.

This header is a summary, not a separate license or an amendment to KOL-v1.
All terms and conditions of KOL-v1 apply. See the accompanying LICENSE file for the complete license text.
-->

# License Check CI

A small, offline checker for declared repository licensing evidence. It does not
decide ownership, license compatibility, infringement, or legal compliance.

## Run

Python 3.11 or newer and Git are required on Linux. The repository must have a
commit and an index containing the files to inspect. Commit the policy as well.

```sh
python3 -I -B src/license_check.py --root "$PWD" \
  --policy .license-policy.json --report /tmp/license-report.json
python3 -B -m unittest discover -s tests -v
python3 -B tools/build_bundle.py --output /tmp/license-check-0.1.1.pyz
```

Use a new report and bundle destination; existing files are never overwritten.
The checker reads indexed paths from the working tree, not an immutable commit
snapshot. Reports expose tracked working-tree dirtiness. Run it on a clean CI checkout. It reads regular files using no-follow
directory descriptors and rejects indexed symlinks, submodules and merge conflicts.
Do not run it against a concurrently modified or hostile host filesystem.

## Policy schema 1

The repository controls its reviewed `.license-policy.json`. This project does
not force KOL or any other license onto another repository. Every tracked file
must match exactly one rule. Patterns use Python `fnmatchcase`: `*` includes path
separators. Each pattern must match at least one tracked file. Overlaps between
rules, unknown fields, duplicate JSON keys, empty inventory and unknown license
references fail. Include the policy itself in the classification.

- `schema`: integer `1`.
- `licenses`: identifier to `{path, sha256}`. Each path must be tracked UTF-8
  license text, at least 200 characters, with the exact approved document digest.
  Known placeholder phrases are rejected. Digests confirm the selected bytes,
  not the authority of the person selecting them.
- `notice`: null when the reviewed policy requires none; otherwise
  `{path, required_text: ["attribution marker"]}`. It must be tracked, at least
  30 characters, and contain every configured marker.
- `rules`: a nonempty list using the categories below.

| Kind | Required fields besides `paths` and `kind` |
| --- | --- |
| `first_party` | `license`, `header` (`root` or `spdx`) |
| `third_party` | `license`, `evidence`, `origin` |
| `generated_metadata` | `evidence`, `reason`, `origin`, `format` (`json` or `toml`) |
| `rights_reserved` | `evidence`, `owner`, `reason`, `required_text` (nonempty markers) |
| `exception` | `evidence`, `reason`, `owner` |

`paths` is a nonempty list of normalized repository-relative patterns. Absolute
paths, parent traversal, Git internals and control characters are rejected.
Evidence paths are literal, tracked, non-placeholder text of at least 20 characters.

First-party rules may additionally specify `evidence` (for an existing exact-path
sidecar or explicit scope document) and `header_markers` (nonempty text markers).
First-party evidence must mention the selected license identifier. `spdx` checks
for the exact identifier line within the first 8192 bytes, supporting hash,
double-slash, star-prefixed and plain text lines. `header_markers` checks all
specified strings in that same region. These are textual evidence checks, not
comment-language parsing or proof of the copyright holder's identity.

`root` means a maintainer has explicitly classified those files as covered by
the declared root license; it is not inferred from a file's location. Third-party
material keeps its independently selected license and provenance evidence.

Generated metadata is restricted to nonempty JSON/TOML objects in `.json`, `.toml`
or `.lock` files. This category does not apply KOL or assert a license grant to
the dependencies it describes. The report lists these paths under
`metadata_not_license_assessed`. Its reason and evidence must justify why it is
metadata rather than implementation; do not use it to relabel unlicensed source.
Unknown rights remain an `exception`, not generated metadata.

Reserved rights are not unknown rights. `rights_reserved` requires a reviewed,
tracked evidence document and every configured marker in that document. Reports
list these paths under `rights_reserved_no_oss_grant` with `license_grant: false`
and `oss_permission: false`. A PASS confirms only the declared retention evidence;
it grants no use, redistribution or OSS rights and does not authenticate ownership.
Do not use this category to conceal unresolved rights: use `exception` instead.
At least one explicitly license-covered file is still required in the repository.

Any exception produces `INCOMPLETE` and a nonzero exit. A report cannot claim a
complete pass by excluding unresolved files. At least one first-party or
third-party file must be inspected even when metadata is present.

## Supply chain and distribution

The build tool produces a deterministic, uncompressed zipapp containing only
`__main__.py`, `LICENSE` and `NOTICE`, with fixed metadata and no local paths.
No generated archive or binary belongs in Git. The CI workflow tests the checker,
checks this repository with its policy, builds and runs the bundle, then retains
the bundle and checksum as short-lived Actions artifacts.

For durable consumption, maintainers publish a reviewed release with an asset named
`license-check.pyz`. Release publication is not automated here. The composite
action resolves the latest stable release on every run and verifies its GitHub
API SHA-256 digest and size before executing exactly those downloaded bytes.
The action's bootstrap behavior is pinned to a reviewed commit; the checker
version is intentionally not pinned in consuming repositories.

## GitHub Actions integration

Replace `REVIEWED_ACTION_COMMIT_SHA` below with the full reviewed commit SHA of
this action. Keep existing source/test jobs and the always-run `Minimum CI`
aggregate; this action replaces only the license retrieval/execution steps.

```yaml
permissions:
  contents: read
jobs:
  license:
    name: License policy checks
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - uses: i-pp/license-check-ci@REVIEWED_ACTION_COMMIT_SHA
        with:
          policy: .github/license-policy.json
```

The root defaults to `github.workspace`. The policy defaults to
`.github/license-policy.json`; override it for a different reviewed policy path.
Linux and Python 3 are required. The optional `token` input defaults to
`github.token`, using the caller's read-only permissions. Set it to an empty
string for anonymous metadata access, subject to GitHub's lower rate limit.
The token goes only to the fixed GitHub release API, never to asset redirects or
the checker subprocess. No secrets or `id-token` permission are needed.

The bootstrap resolves metadata once, requires a non-draft, non-prerelease tag
and a unique uploaded `license-check.pyz`, and rejects absent digests, oversized
assets, mismatched repository/tag/name, unsafe redirects, download errors and
hash mismatches. It requires both exit zero and a schema 1 / PASS report. It
logs release ID, tag, asset ID, asset URL and digest. There is no fallback to a
cached or pinned checker and no automatic mismatch repair. Network outages and
rate limits fail the job; the job timeout bounds the whole operation.

This is integrity checking against GitHub metadata, not a signature or build
provenance guarantee. The logged source URL identifies the artifact, not an
attested source commit. A compromised publisher could publish a malicious new
release and matching digest. Latest-release selection accepts this publisher
trust and allows checker behavior to change without a consumer commit.

Run consumer workflows on pull requests, merge groups and main pushes, without
path filters. Keep consumer jobs read-only and secret-free for fork PRs.
Required status checks and protected review of workflow/policy changes
must be configured separately; this checker cannot prevent a contributor from
editing an unprotected workflow to remove the check.

## Limits and license

PASS means the declared evidence passed these bounded checks, not a legal audit.
The tool does not scan Git history, dependencies fetched at build time, license
compatibility, generated executable contents, or all possible placeholder prose.
It does not prove origin URLs are genuine. Policy and evidence changes require
human review. Explicit errors and unavailable evidence never become PASS.

Project-authored code and documentation are licensed under the root LICENSE
and NOTICE, including JSON configuration without an inline comment. Third-party
materials retain their own terms. KOL is a custom license, not OSI approval or
an SPDX-listed identifier.
