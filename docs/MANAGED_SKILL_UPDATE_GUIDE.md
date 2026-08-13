# How to Build Safe Managed Updates for a GitHub Skill

This guide turns the managed update work in `analyze-project-claims` into a
reusable pattern for other GitHub-distributed skills and small agent products.
The goal is an update path that is easy for a user but refuses ambiguous,
modified, pinned, or untracked installations.

## What you are building

The skill completes its normal task first. It then runs a short, consent-gated
maintenance action:

```text
user invokes skill
        |
        v
skill completes substantive task
        |
        v
read local consent and 24-hour lease
        |
        v
bind one GitHub CLI installation
  source + path + scope + version + pin + tree
        |
        v
verify pre-update package manifest
        |
        v
delegate replacement to `gh skill update`
        |
        v
verify post-update identity and manifest
        |
        v
current invocation stays stable; next invocation uses update
```

This is invocation-driven maintenance, not a background service. If the user
does not invoke the skill, no check runs.

## Prerequisites

- GitHub CLI 2.90.0 or later with `gh skill` support;
- an authenticated GitHub account with repository access;
- Python 3 if you reuse this repository's policy helper;
- one canonical skill package in `skills/<skill-name>/`;
- immutable SemVer release tags;
- a clean user-scope installation for automatic replacement.

After installing GitHub CLI for the first time, restart Codex or the terminal so
the running process receives the updated `PATH`.

## 1. Use one canonical package tree

Use this repository shape:

```text
repository/
|-- README.md
|-- PUBLISHING.md
|-- VERSION
|-- skills/
|   `-- <skill-name>/
|       |-- SKILL.md
|       |-- references/
|       |   |-- package-version.json
|       |   `-- package-manifest.json
|       `-- scripts/
|           `-- update_policy.py
`-- tests/
    `-- test_update_policy.py
```

Do not keep installable duplicates under both `skill/` and `skills/`. An
explicit noncanonical path may install successfully while later update
rediscovery fails or becomes ambiguous.

## 2. Define the release identity map

Keep these identities synchronized on every release:

| Identity | Authority | Required relationship |
|---|---|---|
| Repository `VERSION` | Release workflow | Exact SemVer, such as `0.4.2` |
| `package-version.json` | Installed package | Same SemVer and skill name |
| `SKILL.md` metadata | GitHub CLI installation | Canonical source, package path, ref, and tree SHA |
| Git tag | GitHub release | Immutable `v<SemVer>` pointing to the released commit |
| `gh skill list` version | Native install registry | Same SemVer, allowing one leading `v` |
| Package manifest | Released bytes | Exact normalized file set and SHA-256 digests |
| Citation metadata | Public release metadata | Same release version when citation is enabled |

Rebuild the package manifest after any packaged byte changes. Do not rebuild it
inside an installed copy containing injected GitHub metadata.

## 3. Canonicalize only installer-owned changes

GitHub CLI can add source metadata and rewrite `SKILL.md` frontmatter. A managed
installation may therefore differ byte-for-byte from the repository without a
semantic change.

A safe manifest function should:

1. parse closed UTF-8 YAML frontmatter;
2. remove only top-level or nested keys matching `github-*`;
3. preserve every non-GitHub key and value;
4. put stable keys such as `name` and `description` in a canonical order;
5. normalize the one blank line between frontmatter and body;
6. hash every other package file as exact bytes;
7. reject unexpected files, missing files, duplicate paths, path traversal,
   symbolic links, and reparse points.

Do not solve installer variance by excluding all of `SKILL.md` or all metadata.
That would hide real local edits.

## 4. Store a small local policy record

The reusable state machine has four modes:

| Mode | Meaning |
|---|---|
| `unconfigured` | The user has not chosen a policy |
| `off` | Do not check or replace |
| `notify` | Run native dry-run checks only |
| `auto` | Replace only after all eligibility and integrity gates pass |

Store only:

- schema version and selected mode;
- whether the consent prompt was shown;
- hashed source and installation bindings;
- last attempt, last success, and next eligible check timestamps;
- suspension state and last outcome code.

Write state atomically and guard it with a single-flight lock. On Unix, restrict
the state directory and file permissions. Reject state symlinks and unknown
schema fields.

## 5. Gate automatic replacement

Before enabling or running `auto`, require all of the following:

- exactly one installed skill with the target name;
- the listed path is the skill currently running;
- a canonical GitHub source URL with no credentials, query, or fragment;
- GitHub CLI version equals packaged version;
- valid installer-injected Git tree SHA;
- GitHub CLI source equals `SKILL.md` source metadata;
- user scope;
- unpinned installation;
- clean package manifest;
- unchanged source and installation binding since consent.

If scope is project or the install is pinned, degrade to `notify`. If identity
or integrity fails during automatic maintenance, suspend the automatic path and
require explicit repair and re-enablement.

Never use `--force`, `--unpin`, a shell-built command string, or an updater that
downloads and overwrites files itself. Pass an argument array to GitHub CLI and
let it own package replacement.

## 6. Integrate maintenance after the main task

The skill contract should instruct the agent to run maintenance only after its
substantive response is complete. Maintenance failure must not erase, shorten,
or replace the main result.

Map user language to deterministic actions:

| User intent | Policy action |
|---|---|
| Enable automatic updates | `enable --mode auto` |
| Notify only | `enable --mode notify` |
| Disable updates | `disable` |
| Show status | `status` |
| Check now | `check-now` |
| Ordinary substantive invocation | `maintain` |

Use a success lease, such as 24 hours, to avoid a network check on every
invocation. Use a shorter retry delay, such as one hour, after transient native
or network failures.

Only surface maintenance text when the result matters: first consent, an
available or installed update, suspension, or an explicit user-requested check.

## 7. Verify the postcondition

Record the starting version, tree SHA, and manifest digest. After GitHub CLI
returns, rediscover the installation and verify:

- source and installation bindings still match;
- scope and pin policy remain safe;
- the installed package version is valid;
- the new Git tree SHA is valid;
- the full package manifest passes.

Report `UPDATED_NEXT_USE` if the version, tree, or manifest changed. Report
`UP_TO_DATE` only when none changed. If the native command fails but the old
package still verifies, keep the install and retry later. If the postcondition
does not verify, suspend automatic maintenance.

## 8. Validate before publishing

From the repository root, rebuild and verify the package:

```powershell
py -3 .\skills\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skills\analyze-project-claims `
  --state-dir .\.release-doctor-state `
  build-manifest --write

py -3 .\skills\analyze-project-claims\scripts\update_policy.py `
  --skill-root .\skills\analyze-project-claims `
  --state-dir .\.release-doctor-state `
  verify-package

py -3 -m unittest discover -s tests -v
gh skill publish .\skills --dry-run
```

On macOS or Linux, replace `py -3` with `python3` and use `/` path separators.
The discovery dry-run should end with:

```text
Dry run complete. Use without --dry-run to publish.
```

Require CI to pass before the real publish command. `gh skill publish` creates
a GitHub release, so post-publish repair needs a new patch version.

Publish one immutable release:

```powershell
$Version = (Get-Content -Raw .\VERSION).Trim()
gh skill publish .\skills --tag "v$Version"
gh release view "v$Version"
```

## 9. Run a clean installation smoke test

Use an environment with no duplicate skill of the same name. If a manual copy
exists, move it to a backup directory before installing. Do not force a managed
install over it.

```powershell
$Owner = "Ian-Tseng"
$Repository = "analyze-project-claims"

gh skill preview "$Owner/$Repository" `
  skills/analyze-project-claims/SKILL.md

gh skill install "$Owner/$Repository" `
  skills/analyze-project-claims/SKILL.md `
  --agent codex `
  --scope user

gh skill list --agent codex --scope user `
  --json skillName,sourceURL,scope,version,pinned,path

gh skill update analyze-project-claims --dry-run
```

Verify one canonical source, user scope, the expected tagged version, an
unpinned install, and the expected Codex skill directory.

Run installed-user maintenance from a neutral consumer project. Running it
inside the publisher repository can expose both the repository package and the
user copy to discovery, which should fail closed as ambiguous.

## 10. Prove a real replacement with two releases

A complete replacement test needs a baseline release and a later candidate:

1. publish and install `vA`;
2. start a fresh host invocation and record that it loaded `vA`;
3. publish `vB` only after its CI passes;
4. run a dry update check and prove the installed snapshot did not change;
5. enable `auto` and run real maintenance;
6. require `current_version=vA` and `installed_version=vB`;
7. verify the post-update manifest and native install metadata;
8. start a fresh host invocation and record that it loaded `vB`;
9. run another dry check and require an up-to-date result;
10. invoke maintenance within the lease and require `NOT_DUE`.

Unit tests should also cover consent, exact path/version binding, pinned and
project degradation, duplicate names, source changes, transient failures,
partial replacement, local edits, dry-run immutability, strict state schema,
argument arrays, bounded native output, and lock contention.

## Troubleshooting

| Symptom | Likely cause | Repair |
|---|---|---|
| Explicit install works, update says current forever | Package is outside canonical `skills/*/SKILL.md` discovery | Move the only canonical tree under `skills/`, publish a new patch release, and reinstall cleanly |
| `VERSION_MISMATCH` | Install resolved to `main` or metadata files disagree | Publish `v<SemVer>` and synchronize the release identity map |
| `PACKAGE_MODIFIED` immediately after install | Installer metadata normalization is incomplete, or a forced install left extra files | Update the narrow canonicalizer; otherwise back up and reinstall into an empty target |
| `AMBIGUOUS_INSTALL` | More than one matching copy is visible | Remove the duplicate or run maintenance from a neutral consumer context |
| `INSTALL_PATH_MISMATCH` | The updater is running from a different copy than GitHub CLI tracks | Invoke the tracked copy or reinstall it |
| `PINNED` or `PROJECT_SCOPE` | Automatic replacement is intentionally disallowed | Keep notify mode or update manually |
| `NATIVE_GH_UNAVAILABLE` | GitHub CLI is missing or the live process has stale `PATH` | Install a supported CLI, restart the host, and retry |
| `TRANSIENT_FAILURE` | Network or native update command failed, but the old package still verifies | Retry after backoff; do not break the user's main task |
| `INVALID_POSTCONDITION` | Replacement left an unverifiable identity or package | Reinstall a known release and explicitly re-enable updates |
| `SOURCE_OR_INSTALL_CHANGED` | Source or path changed after consent | Inspect the new identity, then explicitly bind and enable it |

## Keep problem reporting separate

Automatic updates and automatic problem reporting have different trust
boundaries. Do not hide diagnostic upload inside the update consent.

If another product needs agent-found problems sent to a database, build a
separate opt-in flow:

```text
agent finds a candidate problem
        |
        v
local schema validation and secret/path redaction
        |
        v
user-approved reporting policy
        |
        v
authenticated HTTPS ingestion endpoint
        |
        v
append-only report store -> triage -> status visible to user
```

At minimum, define:

- separate consent for reports and for optional attachments;
- a versioned report schema with product version, anonymous installation ID,
  error code, reproduction summary, and redacted diagnostics;
- allowlisted fields and size limits;
- local redaction before network transmission;
- authenticated, rate-limited ingestion rather than direct database access;
- encryption in transit and at rest;
- retention, deletion, export, and abuse-handling policies;
- user-visible delivery status and a way to disable reporting;
- tests proving secrets, repository contents, and raw prompts are not sent by
  default.

This repository now implements that separate path in
`scripts/problem_report.py`, with the owner service in
`reporting_service/server.py`. The reporting policy remains separate from the
update-policy file and defaults to local preview plus per-report approval. See
[Internal Problem Reporting](PROBLEM_REPORTING.md).

## Reuse checklist

- [ ] One canonical `skills/<name>/` package tree
- [ ] Explicit install path and successful update rediscovery
- [ ] Immutable tag matching package SemVer
- [ ] Synchronized version and citation files
- [ ] Deterministic manifest with narrow installer normalization
- [ ] Separate modes for off, notify, and auto
- [ ] Exact source, path, version, tree, scope, and pin binding
- [ ] Pre- and post-replacement integrity verification
- [ ] No force, unpin, or in-process self-overwrite
- [ ] Current-invocation stability and next-invocation activation
- [ ] Backoff, lease, lock, and bounded native output
- [ ] CI before publication
- [ ] Clean two-release E2E with fresh host invocations
- [ ] Honest evidence boundary by host, operating system, and repository type
- [ ] Separate consent and data path for optional problem reporting

The concrete implementation is
[`skills/analyze-project-claims/scripts/update_policy.py`](../skills/analyze-project-claims/scripts/update_policy.py).
The exact observed validation is in
[Managed Update End-to-End Evidence Log](MANAGED_UPDATE_E2E_LOG.md).
