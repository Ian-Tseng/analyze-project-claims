# Publishing Analyze Project Claims

This guide is for maintainers preparing and publishing a public release. Run
commands from the repository root. The commands create external state only when
you run `gh repo create`, `git push`, or `gh skill publish` without
`--dry-run`.

GitHub CLI 2.90.0 or later is required. The `gh skill` commands are currently
in public preview.

## Release blockers

Resolve these before making the repository public:

- verify that the canonical GitHub owner remains `Ian-Tseng`;
- update every owner reference if the repository is transferred;
- verify the author identity and MIT license in `CITATION.cff` and `LICENSE`;
- scan current files and reachable history for credentials and private data;
- review commit identities, issues, releases, Actions logs, and artifacts;
- verify automatic reports require the private owner API;
- prepare `SECURITY.md` and enable private vulnerability reporting;
- verify the active `Protect version release tags` ruleset blocks update and
  deletion of `refs/tags/v*` with no bypass actor;
- either enable GitHub release immutability before publishing or describe the
  release guarantee as policy-only; GitHub does not apply this setting
  retroactively;
- authenticate GitHub CLI;
- review everything that will be committed.

Changing visibility exposes retained history to cloning and forking. Treat the
switch as a publication event, not a reversible privacy control.

The dated pre-publication scope, accepted history exposure, verified controls,
and remaining limits are recorded in the
[Public Release Security Review](docs/PUBLIC_RELEASE_SECURITY_REVIEW.md).

## Publication order and irreversible checkpoints

Use this order for every versioned release:

1. synchronize version, citation, package metadata, and manifest identities;
2. run focused and full local validation from a clean candidate;
3. merge the reviewed candidate and require CI to pass on the exact `main`
   commit that will be released;
4. verify the `refs/tags/v*` protection ruleset and enable GitHub release
   immutability **before** publication;
5. run `gh skill publish .\skills --dry-run` and review every warning;
6. publish the new SemVer tag exactly once and run `gh release verify`;
7. run public preview, isolated install, registry, manifest, and update tests;
8. record runtime discovery and invocation separately for every target client.

Do not infer a later checkpoint from an earlier pass. In particular, package
discovery is not installation, installation is not client discovery, and an
up-to-date dry-run is not a live replacement.

## 1. Set the release identity

The canonical owner is currently `Ian-Tseng`. If the repository is transferred, set the new owner explicitly and rebuild the package manifest.

```powershell
$Owner = "Ian-Tseng"
$Repository = "analyze-project-claims"
$Version = (Get-Content -Raw .\VERSION).Trim()

gh auth login
gh auth status
```

Find the remaining release placeholders and verify owner references:

```powershell
rg -n "REPLACE_WITH_|github.com/Ian-Tseng|Ian-Tseng/analyze-project-claims" .
```

Verify the owner in `README.md`, `CITATION.cff`, and the packaged schemas. If
the repository is transferred, update those references and rebuild the package
manifest.

## 2. Rebuild and validate the package identity

Changing the schema owner changes the packaged bytes. Rebuild the package
manifest before committing:

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
py -3 -m unittest discover -s tests -p "test_evidence_bound_scan*.py" -v
```

On macOS or Linux, replace `py -3` with `python3`. Remove
`.release-doctor-state` after validation; it is local state and is ignored by
Git.

The expected results are:

- package verification succeeds;
- the complete suite and focused evidence-bound record tests pass;
- both v2 schemas, the v2 template, and the evidence-bound record guide are in
  `references/package-manifest.json`;
- `VERSION`, `CITATION.cff`, and `references/package-version.json` agree;
- no release placeholder remains;
- `git status` contains only intentional files.

When recording `unittest` evidence, the `Ran N tests` total includes skipped
tests. If the summary says `skipped=K`, report `N-K` passed and `K` skipped;
do not report `N` passed plus `K` skipped.

On macOS, a test-owned temporary path may be spelled through the `/var`
symlink while its canonical form begins with `/private/var`. A containment test
may canonicalize its own temporary root before comparing paths. Do not weaken
production rejection of symbolic links, Windows reparse points, or paths that
escape an approved root.

## 3. Initialize and upload the repository

If this directory is not already a Git repository:

```powershell
git init
git branch -M main
git add .
git status
git commit -m "Release v$Version"
```

Inspect `git status` before committing. Do not upload caches, local policy
state, private evaluation snapshots, human annotations, credentials, or other
machine-specific artifacts.

Create and push the repository:

```powershell
gh repo create "$Owner/$Repository" `
  --public `
  --source . `
  --remote origin `
  --push `
  --description "Evidence-bounded project auditing for AI agents and research teams"
```

Use `--private` while release identity or licensing is incomplete. If the
remote repository already exists, add its canonical `origin` and use a normal,
reviewed `git push` instead of running `gh repo create` again.

If `gh pr merge --delete-branch` exits nonzero after attempting a merge, query
the pull request immediately:

```powershell
gh pr view <number> --repo "$Owner/$Repository" `
  --json state,mergedAt,mergeCommit,headRefName,baseRefName
```

The server-side pull-request state is authoritative. When it says `MERGED`, do
not retry the merge merely because local branch deletion failed; another
worktree may still have that branch checked out. Clean up the branch only after
that worktree is detached and the deletion is independently safe.

## 4. Validate and publish the skill release

The installable source currently lives under `skills/`, so pass that directory
to GitHub CLI discovery:

```powershell
gh skill publish .\skills --dry-run
```

The final line should be:

```text
Dry run complete. Use without --dry-run to publish.
```

Review every warning even when the command exits successfully. Then publish the
tagged release exactly once:

```powershell
gh skill publish .\skills --tag "v$Version"
gh release view "v$Version"
```

Publishing creates a GitHub release. If post-publication evidence fails, do not
try to repair the same published tag. Fix the package, increment the version,
rerun validation, and publish a new candidate.

If **Enable release immutability** was turned on in repository Settings before
publication, verify the new release:

```powershell
gh release verify "v$Version"
```

Require that command to succeed before calling the release immutable. The
setting applies only to future releases. When enforcement is unavailable or
was enabled too late, use policy-only language: the maintainer does not move
published version tags, but GitHub has not made that release immutable.

The repository tag ruleset is a separate control: it prevents moving or
deleting `v*` refs, including existing tags, but it does not make release notes
or release assets immutable. A publication dry-run should no longer warn that
tag protection is absent.

## 5. Test the public user journey

Use a clean environment with no duplicate `analyze-project-claims` install.
Preview the package before installing it:

```powershell
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

Run the smoke from a neutral consumer directory outside this repository. Before
accepting the filtered user-scope entry above, inspect the same unfiltered view
used by the updater and require exactly one matching name:

```powershell
$VisibleMatches = gh skill list `
  --json skillName,sourceURL,scope,version,pinned,path |
  ConvertFrom-Json |
  Where-Object skillName -eq "analyze-project-claims"

if (@($VisibleMatches).Count -ne 1) {
  throw "Ambiguous analyze-project-claims installation view."
}
```

A publisher checkout contributes a project-scope package to that unfiltered
view. A filtered `--agent codex --scope user` listing may still show one user
entry there, so it cannot by itself prove that updater discovery is
unambiguous. `AMBIGUOUS_INSTALL` in the publisher checkout is the intended
fail-closed result, not evidence that the installed package is broken.

For a non-destructive Windows smoke test, point all four home variables at one
disposable directory in a fresh PowerShell process:

```powershell
$SmokeHome = Join-Path $env:TEMP "apc-skill-smoke-$Version"
New-Item -ItemType Directory -Force -Path $SmokeHome | Out-Null

$env:USERPROFILE = $SmokeHome
$env:HOME = $SmokeHome
$env:HOMEDRIVE = [IO.Path]::GetPathRoot($SmokeHome).TrimEnd('\')
$env:HOMEPATH = $SmokeHome.Substring($env:HOMEDRIVE.Length)

gh skill list --agent codex --scope user --json skillName
gh skill list --agent claude-code --scope user --json skillName
```

Require both initial lists to be empty. That precondition proves the following
install and update observations are isolated from the operator's real user
registry. Keep the directory until its evidence is recorded, then remove it
through a separately reviewed cleanup step.

Confirm that the listing shows:

- the canonical GitHub repository;
- user scope;
- the published version;
- an unpinned installation;
- the expected Codex skill path.

Invoke the installed skill once. It should finish the substantive audit before
asking for update consent. Say `enable automatic updates`, invoke it again, and
confirm that an up-to-date check is silent.

Test Claude Code as a separate managed target in a clean environment with no
duplicate skill:

```powershell
gh skill install "$Owner/$Repository" `
  skills/analyze-project-claims/SKILL.md `
  --agent claude-code `
  --scope user

gh skill list --agent claude-code --scope user `
  --json skillName,sourceURL,scope,version,pinned,path
```

From a neutral consumer directory outside the publisher repository, run `gh
skill update analyze-project-claims --dry-run`. Then start Claude Code, confirm
that `/skills` lists `analyze-project-claims`, and invoke
`/analyze-project-claims` on a disposable fixture. Record the Claude Code and
GitHub CLI versions, operating system, source version and tree, installed path,
manifest digest, invocation, and result. Test a manual directory copy
separately when needed; it is host-managed and does not establish managed
update state.

If no authenticated Claude Code CLI is available, restrict the release claim to
structural Agent Skills compatibility. Do not claim Claude Code runtime
validation until the smoke test above has been observed.

Use [How to Validate a GitHub Skill Across Codex and Claude Code](docs/MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md)
as the reusable procedure. Record exact observations and gaps in an evidence
log such as [Claude Code E2E Evidence Log](docs/CLAUDE_CODE_E2E_LOG.md).

A real replacement test requires a later published candidate. During that
test, the current invocation must continue using its starting version and the
next invocation must load the verified new version.

## 6. Record claim-to-evidence links

Keep machine authority, human-readable views, and remote lifecycle evidence
distinct. For v0.7.0, the evidence map is:

| Claim | Supporting authority |
| --- | --- |
| Released package bytes and version | [`package-manifest.json`](skills/analyze-project-claims/references/package-manifest.json), [`package-version.json`](skills/analyze-project-claims/references/package-version.json), and [GitHub release v0.7.0](https://github.com/Ian-Tseng/analyze-project-claims/releases/tag/v0.7.0) |
| Accepted repository structure | [`accepted-map.json`](validation/component-map/accepted-map.json) |
| Formal evidence-bound audit | [`20260814T155937638082Z-c36faabe.json`](validation/history/20260814T155937638082Z-c36faabe.json) |
| Human-readable audit view | [`20260814T155937638082Z-c36faabe.md`](validation/reports/20260814T155937638082Z-c36faabe.md) |
| Cross-platform tests on released `main` | [GitHub Actions run 31817785877](https://github.com/Ian-Tseng/analyze-project-claims/actions/runs/31817785877) |
| Public Codex and Claude-targeted distribution | [`CLAUDE_CODE_E2E_LOG.md`](docs/CLAUDE_CODE_E2E_LOG.md) |

Markdown reports are derived views; do not treat them as a second authority.
When a mapped source fix changes component identity, reconcile the component
map, explicitly accept the intended candidate, run a second unchanged check,
and then append a new validation JSON record and report. Never rewrite an
earlier accepted map event, audit record, or dated E2E observation.

## 7. Verify problem-report operations

Run the reporter and owner-service tests before publishing:

```powershell
py -3 -m unittest discover -s tests -p "test_problem_report.py" -v
py -3 -m unittest discover -s tests -p "test_reporting_service.py" -v
```

For GitHub transport, verify visibility lookup fails closed. A public issue
must require both `--approved` and `--allow-public-issue` for the exact preview.
Verify new and legacy `auto-minimal` GitHub policies stop before delivery;
automatic reports require the private owner API. Security reports must use
private vulnerability reporting.

Configure the desired GitHub notifications. The Issues list or private API is
the authoritative receipt; a notification is convenience, not proof of
ingestion.

Triage the report before changing code. Eligible public reports can use the
owner-gated [Agent Maintainer](docs/AGENT_MAINTAINER.md) to produce an isolated,
validated draft pull request. Never execute issue text or automatically merge,
release, or close a report. Require a regression test, reviewed fix, passing
CI, and a new versioned SemVer release whose tag is not moved. Close the issue
only after the released fix and installed-update evidence exist.

If operating the optional API, follow
[Internal Problem Reporting](docs/PROBLEM_REPORTING.md). Production requires an
HTTPS reverse proxy, hashed scoped tokens, encrypted persistent storage,
backups, explicit retention, and owner monitoring. Test client isolation,
deduplication, triage status, deletion, and retention against the exact build.
The API service is owner infrastructure and is not installed with the skill.

Add report schemas and `problem_report.py` to the package-manifest check. Never
publish a package whose runtime event enum and JSON schema disagree.

If enabling the optional agent-maintainer workflow, follow
[Agent Maintainer for Internal Reports](docs/AGENT_MAINTAINER.md). Create the
owner-only `agent-ready` label and add dedicated `OPENAI_API_KEY` and narrowly
scoped, expiring `AGENT_MAINTAINER_TOKEN` secrets. Verify the exact pinned
Actions revisions before each release. Do not apply the label until the issue's
fixed disclosure and bounded form pass owner review. A successful run creates
only a draft candidate; it never replaces the release checklist above.

If operating installation analytics, follow
[Privacy-Bounded Installation Analytics](docs/INSTALLATION_ANALYTICS.md), run
both analytics test modules, publish the exact fields and retention policy, and
deploy the API behind HTTPS before distributing a scoped client credential.
Never describe repository traffic or the aggregate as downloads, users, or all
installs. If no production endpoint was observed, keep the feature described as
an inactive reference architecture.

## 8. Evidence boundary

A successful dry-run proves package discovery and validation only. It does not
prove that the repository was pushed, that a release was published, that Codex
or Claude Code loaded it, or that automatic replacement works across supported
operating systems. Record those observations separately before claiming
release readiness.
