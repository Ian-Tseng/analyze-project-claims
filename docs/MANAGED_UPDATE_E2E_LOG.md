# Managed Update End-to-End Evidence Log

This append-only record captures dated observations of the
`analyze-project-claims` managed update path. Each result separates live
replacement evidence from behavior covered only by code or tests.

## v0.7.0 to v0.7.1 public replacement result

**PASS ON THE RECORDED WINDOWS CODEX INSTALLATION.** On 2026-08-15
(Asia/Taipei), a canonical GitHub CLI-tracked, user-scope, unpinned v0.7.0
installation with existing `auto` consent replaced itself with immutable public
release v0.7.1. The running invocation retained v0.7.0 and reported
`UPDATED_NEXT_USE`; the installed copy then verified as v0.7.1.

The released commit was
`fd17acc2296763bf7e9ca745b84da97d62fe1495`. Pull request
[#4](https://github.com/Ian-Tseng/analyze-project-claims/pull/4) merged to that
commit, all six jobs in the exact-main [CI
run](https://github.com/Ian-Tseng/analyze-project-claims/actions/runs/31865670854)
passed, and [release
v0.7.1](https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.1)
verified as immutable.

### Observed postconditions

| Check | Observation |
| --- | --- |
| Replacement | `UPDATED_NEXT_USE`; current invocation v0.7.0, installed version v0.7.1 |
| Native registry | Canonical public source, user scope, v0.7.1, unpinned, expected Codex path |
| Package integrity | `PACKAGE_VERIFIED`; normalized digest `2b12f69b30890d2842149e029e74352294c65649f2e692a9b0025707bb35ee1c` |
| Fresh policy-aware check | `UP_TO_DATE` in `auto` mode despite the active lease |
| Stored policy | `auto`, not suspended, next check 24 hours after the successful check |
| Local full suite | 182 tests ran: 181 passed and 1 Windows privilege-dependent symlink test skipped |
| Focused updater suite | 29 tests ran: 28 passed and the same symlink test skipped |

The smoke ran from a neutral consumer directory. Running the same updater
discovery inside the publisher checkout exposed both its project package and
the user installation and correctly returned `AMBIGUOUS_INSTALL`. A filtered
`gh skill list --agent codex --scope user` showed only the user copy, so that
narrow listing was not sufficient to establish the updater's unfiltered view.

### Inconsistency found before release

The first policy-aware implementation read `auto` consent before acquiring the
single-flight lock. A concurrent disable could therefore land while the check
waited and leave the mutating path authorized by stale state. The released fix
reloads policy under the lock, derives dry-run versus replacement from that
state, and rechecks `unconfigured`, `off`, and suspended-auto gates before any
native update.

Regression tests cover both consent directions under lock, locked reloads to
inactive modes, explicit non-auto mode preservation, lease bypass in `auto`,
and the CLI route. The safe claim is limited to the observed Windows Codex
installation plus the deterministic cross-platform test contract; this run
does not establish live Claude Code, macOS, Linux, pinned, project-scope, or
plugin-host replacement.

## Historical v0.4.1 to v0.4.2 private replacement result

The following section records what was observed on 2026-08-12. It remains
historical evidence and is not rewritten by the newer public run.

## Conclusion

A private, GitHub CLI-tracked, unpinned, user-scope Codex skill was updated from
release `v0.4.1` to `v0.4.2`. The updater preserved the version used by the
current invocation, verified the installed replacement, and a fresh Codex
invocation then loaded `v0.4.2`.

This establishes the replacement path for one Windows environment and one
private GitHub repository. It does not establish unattended background updates,
plugin-host updates, public-repository behavior, or live replacement on macOS
and Linux.

## Environment and release identity

| Item | Observed value |
|---|---|
| Host | Codex on Windows |
| GitHub CLI | `2.97.0` |
| Repository | `Ian-Tseng/analyze-project-claims` |
| Repository visibility | Private |
| Branch | `main` |
| Baseline release | `v0.4.1` -> `f37ec457d3b251993d276f5ba623ccc85e374fd1` |
| Candidate release | `v0.4.2` -> `44b3d8706430cc753a73358ec35640c5ad9eb20e` |
| Install surface | Standalone Codex skill |
| Install policy | User scope, unpinned, automatic updates enabled |
| Installed location | The current user's Codex skill directory |

The `v0.4.2` validation workflow passed all six matrix jobs: Windows, macOS,
and Ubuntu on Python 3.10 and 3.12. The run is recorded in
[GitHub Actions](https://github.com/Ian-Tseng/analyze-project-claims/actions/runs/31604099265).

## Observed sequence

1. Install the tagged `v0.4.1` package with GitHub CLI in user scope.
2. Start a fresh Codex invocation and read the packaged version. It reported:

   ```text
   BEFORE_AUTO_UPDATE | package=0.4.1
   ```

3. Run the native update command with `--dry-run`. It reported the `v0.4.2`
   candidate, while a file snapshot confirmed that the installed package had
   not changed.
4. Run the consented automatic maintenance action. It returned:

   ```text
   UPDATED_NEXT_USE
   Current invocation: 0.4.1
   Installed for next invocation: 0.4.2
   ```

5. Verify the post-update package manifest. The normalized package digest was:

   ```text
   aed4f96752933a2273e9f191d697008f8aafed3002d6becf8c6dd9172ab5b71b
   ```

6. Start another fresh Codex invocation. It reported:

   ```text
   AFTER_AUTO_UPDATE | package=0.4.2
   ```

7. Run `gh skill update analyze-project-claims --dry-run` from a neutral
   consumer directory. It reported:

   ```text
   All skills are up to date.
   ```

8. Run automatic maintenance again within the 24-hour lease. It returned
   `NOT_DUE`, confirming that ordinary invocations do not repeat the check
   during the lease.

## What each layer proves

| Evidence | What it proves | What it does not prove |
|---|---|---|
| 66 local tests passed | The tested policy, integrity, lifecycle, and helper contracts pass on the local environment | A real GitHub replacement happened |
| Six CI jobs passed | The standard-library suite passes on three operating systems and two Python versions | Each operating system completed a live install and upgrade |
| `gh skill publish --dry-run` passed | GitHub CLI discovered and validated the canonical package | A release or installation exists |
| Observed unchanged `v0.4.1` and `v0.4.2` tags | Each package version resolved to a stable Git commit during the E2E | A user loaded either package |
| Fresh invocation before and after | Codex loaded the baseline, then the installed candidate | Other hosts or plugin surfaces behave the same way |
| Pre/post manifest checks | The baseline and replacement matched their release manifests | The package is free of every possible security defect |

One Windows test is intentionally skipped because creating symbolic links can
require extra privileges. The equivalent rejection path runs on macOS and
Linux CI.

## Failures found during validation

### Noncanonical publisher layout

An explicit install from `skill/analyze-project-claims/SKILL.md` succeeded, but
later update discovery reported that everything was current. GitHub CLI update
rediscovery expects the conventional `skills/*/SKILL.md` layout. Moving the
single canonical package to `skills/analyze-project-claims/` fixed discovery.

Reusable rule: treat install success and update rediscovery as separate gates.
Keep one canonical package tree under `skills/`; do not publish byte-identical
copies under both `skill/` and `skills/`.

### Installer-owned frontmatter rewrites

GitHub CLI injected `github-*` source metadata and rewrote YAML ordering,
indentation, and the blank line after frontmatter. A raw byte hash therefore
rejected a clean managed installation.

Reusable rule: define one narrow canonicalization function. For this package it
orders `name` and `description`, removes only installer-owned `github-*`
metadata, normalizes the body separator, preserves other metadata, and still
detects semantic or payload changes.

### Missing release tag identity

Before a release tag existed, GitHub CLI described the install version as
`main`. That could not be reconciled with the package SemVer.

Reusable rule: publish versioned `v<package-version>` tags, never move them,
and require the package version, GitHub CLI version, tag, and installed tree
to agree.

### Mixed manual and managed copies

Forcing a GitHub CLI install over a previous manual copy left extra files. The
manifest correctly classified the result as modified.

Reusable rule: migrate by moving the old directory to a recoverable backup,
then perform a clean managed install. Do not use forced installation as a
cleanup mechanism.

### Publisher repository ambiguity

Running an unscoped `gh skill list` inside the publisher repository exposed
both the repository package as a project-scope skill and the user installation.
An update-by-name was therefore intentionally rejected as `AMBIGUOUS_INSTALL`.

Reusable rule: run installed-user maintenance from a neutral consumer project,
and bind the updater to the exact source and installed path before replacement.

### Runtime dependency path refresh

Installing GitHub CLI through a package manager updated the future user `PATH`,
but the already-running Codex process did not necessarily inherit that change.

Reusable rule: document the native dependency as a prerequisite and tell users
to restart the host after first installing it.

### Publishing is a one-way release action

`gh skill publish` creates a GitHub release. A failed check after publication
cannot safely rewrite that release identity.

Reusable rule: run CI, manifest verification, discovery dry-run, and release
identity checks before publishing. Repair a failed published candidate with a
new patch version, not a moved tag.

## Durable product rules

- Ask for consent after the user's substantive task, never before it.
- Update checks are invocation-driven. This implementation has no background
  daemon and cannot update a skill that is never invoked.
- Keep the current invocation stable. Activate a verified replacement only on
  the next invocation.
- Automatic replacement requires exactly one clean, user-scope, unpinned,
  GitHub CLI-tracked copy.
- Bind source URL, installed path, package version, Git tree identity, and
  package manifest before and after replacement.
- Never add `--force` or `--unpin` to the automatic path.
- Treat network and GitHub CLI failures as maintenance failures, not failures of
  the user's main task.
- Suspend automatic replacement after an identity or integrity failure until
  the user repairs and explicitly re-enables it.
- Prove a replacement with two real releases. An up-to-date check or mocked test
  alone is not replacement evidence.

## Evidence boundary

The updater stores local policy state only. It does not send project content,
audit findings, errors, or telemetry to a database. An opt-in problem-reporting
service would be a separate product surface with its own consent, redaction,
authentication, retention, deletion, and abuse controls.

See [How to Build Safe Managed Updates for a GitHub Skill](MANAGED_SKILL_UPDATE_GUIDE.md)
for the reusable implementation and release procedure.
